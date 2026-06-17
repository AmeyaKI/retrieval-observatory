from __future__ import annotations

from typing import Any, Dict, List, Optional

from retrieval_observatory.advisor.types import Recommendation, ReliabilityScore
from retrieval_observatory.metrics.diagnostics import aggregate_diagnostics
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.store.base import BaseStore

_LABEL_ACTIONS = {
    "candidate_miss": (
        "Increase first-stage k or add an additional retriever",
        "High candidate_miss rate — relevant docs never enter the candidate pool",
    ),
    "reranker_drop": (
        "Tune or replace the reranker — it is dropping relevant docs",
        "High reranker_drop rate — first stage finds relevant docs but reranker removes them",
    ),
    "late_stage_drop": (
        "Inspect late-stage filtering — relevant docs survive to penultimate stage but not final",
        "High late_stage_drop rate",
    ),
    "lexical_mismatch": (
        "Add a dense retriever (go hybrid)",
        "BM25 misses queries where dense retrieval succeeds — lexical mismatch pattern",
    ),
    "semantic_mismatch": (
        "Add lexical/BM25 retrieval",
        "Dense retrieval misses queries where BM25 succeeds — semantic mismatch pattern",
    ),
}

_LABEL_THRESHOLD = 0.15
_LATENCY_BUDGET_HEADROOM = 0.8


def _final_stage_metrics(agg: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    """Group final-stage metrics by pipeline_id."""
    by_pipeline: Dict[str, Dict[str, float]] = {}
    max_stage: Dict[str, int] = {}
    for key, entry in agg.items():
        pid = entry["pipeline_id"]
        stage = entry["stage_index"]
        if stage < 0:
            continue
        max_stage[pid] = max(max_stage.get(pid, -1), stage)

    for key, entry in agg.items():
        pid = entry["pipeline_id"]
        if entry["stage_index"] != max_stage.get(pid, -1):
            continue
        by_pipeline.setdefault(pid, {})[entry["metric_name"]] = entry["mean"]
    return by_pipeline


async def recommend(
    run_id: str,
    store: BaseStore,
    *,
    hotspots: Optional[List[Dict[str, Any]]] = None,
    engine: MetricsEngine | None = None,
) -> List[Recommendation]:
    engine = engine or MetricsEngine()
    agg = await engine.aggregate(run_id, store)
    diagnostics_rows = await store.get_query_diagnostics(run_id)
    diag = aggregate_diagnostics(diagnostics_rows)
    manifest = await store.get_run_manifest(run_id) or {}
    recommendations: List[Recommendation] = []
    priority = 1

    n = max(diag.get("n", 1), 1)
    for label, count in diag.get("failure_labels", {}).items():
        rate = count / n
        if rate < _LABEL_THRESHOLD:
            continue
        action_tpl = _LABEL_ACTIONS.get(label)
        if not action_tpl:
            continue
        action, rationale = action_tpl
        recommendations.append(
            Recommendation(
                action=action,
                rationale=rationale,
                evidence=[
                    f"failure_label={label} appears in {count}/{n} diagnostic rows ({rate:.0%})",
                ],
                priority=priority,
            )
        )
        priority += 1

    latency_budget = manifest.get("latency_budget_ms")
    if latency_budget:
        for key, entry in agg.items():
            if entry.get("metric_name") != "latency_p95":
                continue
            p95 = entry["mean"]
            if p95 > latency_budget:
                recommendations.append(
                    Recommendation(
                        action="Reduce k, use a smaller reranker, or add caching to meet latency budget",
                        rationale=f"Latency p95 ({p95:.0f} ms) exceeds budget ({latency_budget} ms)",
                        evidence=[f"pipeline={entry['pipeline_id']}", f"latency_p95={p95:.1f}ms", f"budget={latency_budget}ms"],
                        priority=priority,
                    )
                )
                priority += 1

    forge_dataset_id = manifest.get("forge_dataset_id")
    if forge_dataset_id and hasattr(store, "get_forge_scenarios"):
        await _forge_scenario_recommendations(
            store, forge_dataset_id, run_id, agg, recommendations, priority
        )

    if hotspots:
        for hs in hotspots[:3]:
            label = hs.get("label") or hs.get("failure_label")
            if not label:
                continue
            recommendations.append(
                Recommendation(
                    action=f"Investigate production hotspot: {label}",
                    rationale="TraceLens hotspot correlates with this failure pattern in live traffic",
                    evidence=[f"hotspot_label={label}", f"trace_count={hs.get('count', '?')}"],
                    priority=priority,
                )
            )
            priority += 1

    # Adaptive routing hint: hard queries failing disproportionately
    hard_fail = sum(
        1 for row in diagnostics_rows
        if row.get("difficulty_bucket") in ("hard", "extreme")
        and row.get("failure_labels")
    )
    hard_total = sum(1 for row in diagnostics_rows if row.get("difficulty_bucket") in ("hard", "extreme"))
    if hard_total >= 5 and hard_fail / hard_total > 0.4:
        recommendations.append(
            Recommendation(
                action="Route hard/extreme queries to a stronger pipeline (hybrid + rerank)",
                rationale="Hard queries fail at a high rate — consider difficulty-based routing",
                evidence=[
                    f"hard_query_failure_rate={hard_fail / hard_total:.0%}",
                    f"hard_queries={hard_total}",
                ],
                priority=priority,
            )
        )

    recommendations.sort(key=lambda r: r.priority)
    return recommendations


async def _forge_scenario_recommendations(
    store: BaseStore,
    forge_dataset_id: str,
    run_id: str,
    agg: Dict[str, Any],
    recommendations: List[Recommendation],
    priority: int,
) -> None:
    scenarios = await store.get_forge_scenarios(forge_dataset_id)
    if not scenarios:
        return
    queries = await store.get_forge_queries(forge_dataset_id, limit=10000)
    scenario_by_id = {s["scenario_id"]: s for s in scenarios}
    scenario_queries: Dict[str, List[str]] = {}
    for q in queries:
        scenario_queries.setdefault(q["scenario_id"], []).append(q["query_id"])

    metrics = await store.get_metrics(run_id)
    recall_by_query = {
        row["query_id"]: row["value"]
        for row in metrics
        if row["metric_name"] == "recall" and row["k"] == 10
    }
    if not recall_by_query:
        return
    overall_recall = sum(recall_by_query.values()) / len(recall_by_query)

    by_type: Dict[str, List[float]] = {}
    for scenario_id, qids in scenario_queries.items():
        stype = scenario_by_id.get(scenario_id, {}).get("scenario_type", "unknown")
        for qid in qids:
            if qid in recall_by_query:
                by_type.setdefault(stype, []).append(recall_by_query[qid])

    for stype, recalls in by_type.items():
        if len(recalls) < 2:
            continue
        type_recall = sum(recalls) / len(recalls)
        if type_recall >= overall_recall * 0.7:
            continue
        recommendations.append(
            Recommendation(
                action=f"Add targeted retrieval for '{stype}' scenarios (e.g. temporal recency boost)",
                rationale=f"Forge scenario_type '{stype}' Recall@10 ({type_recall:.2f}) is well below overall ({overall_recall:.2f})",
                evidence=[
                    f"scenario_type={stype}",
                    f"recall@10={type_recall:.3f}",
                    f"overall_recall@10={overall_recall:.3f}",
                    "Consider forging more queries of this scenario type",
                ],
                priority=priority,
            )
        )


async def compute_reliability(
    run_id: str,
    store: BaseStore,
    *,
    engine: MetricsEngine | None = None,
) -> ReliabilityScore:
    """Composite reliability score with named, explainable components (0–1 each)."""
    engine = engine or MetricsEngine()
    agg = await engine.aggregate(run_id, store)
    diagnostics_rows = await store.get_query_diagnostics(run_id)
    diag = aggregate_diagnostics(diagnostics_rows)
    manifest = await store.get_run_manifest(run_id) or {}
    notes: List[str] = []

    recall_vals = [e["mean"] for e in agg.values() if e.get("metric_name") == "recall" and e.get("k") == 10]
    recall_component = min(max(sum(recall_vals) / len(recall_vals), 0.0), 1.0) if recall_vals else 0.5
    if not recall_vals:
        notes.append("No Recall@10 metrics found; recall component defaulted to 0.5")

    n = max(diag.get("n", 1), 1)
    failure_count = sum(diag.get("failure_labels", {}).values())
    failure_rate = failure_count / n
    low_failure_component = max(0.0, 1.0 - min(failure_rate, 1.0))

    latency_budget = manifest.get("latency_budget_ms")
    latency_vals = [e["mean"] for e in agg.values() if e.get("metric_name") == "latency_p95"]
    if latency_budget and latency_vals:
        worst_p95 = max(latency_vals)
        latency_component = max(0.0, min(1.0, 1.0 - (worst_p95 - latency_budget * _LATENCY_BUDGET_HEADROOM) / latency_budget))
    elif latency_vals:
        latency_component = 0.7
        notes.append("No latency budget set; latency component uses neutral default 0.7")
    else:
        latency_component = 0.5
        notes.append("No latency metrics found")

    unstable = diag.get("failure_labels", {}).get("unstable", 0)
    diagnostic_health = max(0.0, 1.0 - unstable / n)

    components = {
        "recall_at_10": round(recall_component, 3),
        "low_failure_rate": round(low_failure_component, 3),
        "latency_headroom": round(latency_component, 3),
        "diagnostic_health": round(diagnostic_health, 3),
    }
    value = round(sum(components.values()) / len(components), 3)
    score = ReliabilityScore(value=value, components=components, notes=notes)
    if hasattr(store, "save_reliability_snapshot"):
        await store.save_reliability_snapshot(run_id, score.value, score.components)
    return score
