from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from retrieval_observatory.runner.execute import BenchmarkArtifacts


@dataclass
class ReportModel:
    """Deterministic, renderer-neutral evaluation report contract."""

    kind: str
    run_id: str
    title: str
    verdict: str
    conclusion: str
    evidence_health: str
    evidence_reasons: list[str]
    metrics: Dict[str, Any]
    dominant_issue: Optional[Dict[str, Any]]
    affected_queries: list[Dict[str, Any]]
    provenance: Dict[str, Any]
    next_action: str
    reproduce: str
    dashboard_url: str
    schema_version: int = 1
    comparison: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True, default=str) + "\n"

    def to_markdown(self) -> str:
        if self.kind == "comparison" and self.comparison:
            return self._comparison_markdown()
        lines = [
            f"# {self.title}",
            "",
            f"**Verdict:** `{self.verdict}`  ",
            f"**Evidence:** `{self.evidence_health}`  ",
            f"**Run:** `{self.run_id}`",
            "",
            self.conclusion,
            "",
        ]
        if self.evidence_reasons:
            lines.extend(["## Evidence health", ""])
            lines.extend(f"- {reason}" for reason in self.evidence_reasons)
            lines.append("")
        if self.dominant_issue:
            lines.extend([
                "## Dominant issue",
                "",
                f"`{self.dominant_issue['label']}` affects {self.dominant_issue['query_count']} evaluated query records.",
                "",
            ])
        lines.extend(["## Headline metrics", "", "| Metric | Mean | 95% CI |", "|---|---:|---:|"])
        for key, value in sorted(self.metrics.items()):
            if isinstance(value, dict):
                mean = _format_number(value.get("mean"))
                ci = f"{_format_number(value.get('ci_low'))} to {_format_number(value.get('ci_high'))}"
            else:
                mean, ci = _format_number(value), "unavailable"
            lines.append(f"| `{key}` | {mean} | {ci} |")
        lines.append("")
        if self.affected_queries:
            lines.extend(["## Affected queries", "", "| Query | Pipeline | Findings |", "|---|---|---|"])
            for query in self.affected_queries:
                findings = ", ".join(query.get("failure_labels", [])) or "none"
                lines.append(f"| `{query.get('query_id')}` | `{query.get('pipeline_id')}` | {findings} |")
            lines.append("")
        lines.extend([
            "## Next action",
            "",
            self.next_action,
            "",
            "## Reproduce and inspect",
            "",
            f"- `{self.reproduce}`",
            f"- Dashboard: {self.dashboard_url}",
            "",
        ])
        return "\n".join(lines)

    def _comparison_markdown(self) -> str:
        comparison = self.comparison or {}
        validity = comparison.get("validity", {})
        baseline = comparison.get("baseline_run_id", "unavailable")
        candidate = comparison.get("candidate_run_id", "unavailable")
        lines = [
            f"# {self.title}",
            "",
            f"**Verdict:** `{self.verdict}`  ",
            f"**Validity:** `{validity.get('outcome', 'unavailable')}`  ",
            f"**Baseline:** `{baseline}`  ",
            f"**Candidate:** `{candidate}`",
            "",
            self.conclusion,
            "",
        ]
        differences = validity.get("differences", [])
        if differences:
            lines.extend(["## Validity evidence", ""])
            lines.extend(f"- `{item.get('axis')}`: {item.get('detail')}" for item in differences)
            lines.append("")
        lines.extend([
            "## Paired results",
            "",
            "| Metric | Baseline | Candidate | Effect | q-value | n | Decision |",
            "|---|---:|---:|---:|---:|---:|---|",
        ])
        for key, result in sorted(comparison.get("results", {}).items()):
            lines.append(
                f"| `{key}` | {_format_number(result.get('baseline_mean'))} | "
                f"{_format_number(result.get('candidate_mean'))} | {_format_number(result.get('effect'))} | "
                f"{_format_number(result.get('q_value'))} | {result.get('paired_n', 0)} | "
                f"{result.get('decision', 'no_decision')} |"
            )
        lines.append("")
        if self.affected_queries:
            metric = comparison.get("query_diff_metric", "metric")
            lines.extend([
                "## Most affected queries",
                "",
                f"Candidate minus baseline for `{metric}`.",
                "",
                "| Query | Baseline | Candidate | Delta |",
                "|---|---:|---:|---:|",
            ])
            for query in self.affected_queries:
                lines.append(
                    f"| `{query.get('query_id')}` | {_format_number(query.get('baseline'))} | "
                    f"{_format_number(query.get('candidate'))} | {_format_number(query.get('delta'))} |"
                )
            lines.append("")
        lines.extend([
            "## Next action",
            "",
            self.next_action,
            "",
            "## Reproduce and inspect",
            "",
            f"- `{self.reproduce}`",
            f"- Dashboard: {self.dashboard_url}",
            "",
        ])
        return "\n".join(lines)

    def to_html(self) -> str:
        markdown = self.to_markdown()
        payload = self.to_json(indent=2)
        return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
body{{font:15px/1.55 system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#172033}}
pre{{white-space:pre-wrap;background:#f5f7fa;border:1px solid #d7dde8;border-radius:8px;padding:1rem}}
details{{margin-top:2rem}}code{{font-family:ui-monospace,monospace}}
</style></head><body><pre>{markdown}</pre><details><summary>Machine-readable report</summary><pre>{payload}</pre></details></body></html>
""".format(
            title=html.escape(self.title),
            markdown=html.escape(markdown),
            payload=html.escape(payload),
        )

    def write(self, path: str | Path, *, format: Optional[str] = None) -> Path:
        target = Path(path)
        selected = (format or target.suffix.lstrip(".") or "json").lower()
        renderers = {
            "json": self.to_json,
            "md": self.to_markdown,
            "markdown": self.to_markdown,
            "html": self.to_html,
        }
        if selected not in renderers:
            raise ValueError("Report format must be json, markdown/md, or html.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(renderers[selected](), encoding="utf-8")
        return target


def _format_number(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, (int, float)):
        return f"{value:.4f}"
    return str(value)


def _headline_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    end_to_end = {key: value for key, value in metrics.items() if "|stage-1|" in key}
    selected = end_to_end or metrics
    quality = [key for key in selected if not any(token in key for token in ("latency", "cost", "profile"))]
    operational = [key for key in selected if any(token in key for token in ("latency", "cost"))]
    keys = (quality[:3] + operational[:2]) or list(selected)[:5]
    return {key: selected[key] for key in keys}


def build_run_report(
    *,
    run_id: str,
    experiment_name: str,
    db_path: str,
    metrics: Dict[str, Any],
    diagnostics: list[Dict[str, Any]],
    manifest: Optional[Dict[str, Any]],
) -> ReportModel:
    manifest = manifest or {}
    counts = manifest.get("counts", {})
    attempted = counts.get("attempted")
    completed = counts.get("completed")
    failures = Counter(
        label
        for row in diagnostics
        for label in row.get("failure_labels", [])
    )
    dominant = None
    if failures:
        label, count = failures.most_common(1)[0]
        dominant = {"label": label, "query_count": count}

    evidence_reasons = []
    dataset = manifest.get("dataset", {})
    for key in ("query_hash", "corpus_hash", "qrel_hash"):
        if not dataset.get(key):
            evidence_reasons.append(f"Dataset {key} is unavailable.")
    if not manifest.get("labeling", {}).get("method"):
        evidence_reasons.append("Label provenance is unavailable.")
    if attempted is None or completed is None:
        evidence_reasons.append("Attempted/completed query counts are unavailable.")
    evidence_health = "ready" if not evidence_reasons else "limited"

    if attempted is not None and completed is not None and completed < attempted:
        verdict = "partial"
        conclusion = f"{completed}/{attempted} queries completed; inspect terminal partial traces before drawing a run-level conclusion."
    elif dominant:
        verdict = "needs_attention"
        conclusion = f"The dominant diagnosed issue is {dominant['label']}, affecting {dominant['query_count']} evaluated query records."
    else:
        verdict = "no_diagnosed_failures"
        conclusion = "No retrieval failure label was diagnosed in the evaluated queries; this is not a claim about answer quality."

    affected = [
        {
            "query_id": row.get("query_id"),
            "pipeline_id": row.get("pipeline_id"),
            "failure_labels": sorted(row.get("failure_labels", [])),
        }
        for row in diagnostics
        if row.get("failure_labels")
    ]
    affected.sort(key=lambda row: (str(row["query_id"]), str(row["pipeline_id"])))
    affected = affected[:20]
    next_action = (
        f"Open an affected query and locate the first operator where `{dominant['label']}` appears."
        if dominant else
        "Compare this run with an explicit baseline before accepting a retrieval change."
    )
    return ReportModel(
        kind="run",
        run_id=run_id,
        title=f"retobs evaluation — {experiment_name}",
        verdict=verdict,
        conclusion=conclusion,
        evidence_health=evidence_health,
        evidence_reasons=evidence_reasons,
        metrics=_headline_metrics(metrics),
        dominant_issue=dominant,
        affected_queries=affected,
        provenance={
            "manifest_schema_version": manifest.get("schema_version"),
            "dataset": dataset,
            "labeling": manifest.get("labeling"),
            "models": manifest.get("models"),
            "git_commit": manifest.get("git_commit"),
            "git_dirty": manifest.get("git_dirty"),
        },
        next_action=next_action,
        reproduce=f"retobs report {run_id} --db {db_path}",
        dashboard_url=f"http://127.0.0.1:4000/#/runs/{run_id}/overview",
    )


async def load_run_report(run_id: str, db_path: str) -> ReportModel:
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    runs = await store.list_runs()
    run = next((item for item in runs if item["run_id"] == run_id), None)
    if run is None:
        raise ValueError(f"Run not found: {run_id}")
    return build_run_report(
        run_id=run_id,
        experiment_name=run.get("experiment_name", run_id),
        db_path=db_path,
        metrics=await MetricsEngine().aggregate(run_id, store),
        diagnostics=await store.get_query_diagnostics(run_id),
        manifest=await store.get_run_manifest(run_id),
    )


async def load_comparison_report(baseline_run_id: str, candidate_run_id: str, db_path: str) -> ReportModel:
    """Build one validity-gated report for CLI, SDK, MCP, CI, and HTML artifacts."""
    from retrieval_observatory.metrics.comparison import (
        _scores_for,
        compare_paired_metrics,
        comparison_validity,
        parse_metric_key,
    )
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    runs = {item["run_id"]: item for item in await store.list_runs()}
    missing = [run_id for run_id in (baseline_run_id, candidate_run_id) if run_id not in runs]
    if missing:
        raise ValueError(f"Run not found: {', '.join(missing)}")

    baseline_manifest = await store.get_run_manifest(baseline_run_id)
    candidate_manifest = await store.get_run_manifest(candidate_run_id)
    validity = comparison_validity([baseline_manifest, candidate_manifest])
    baseline_rows = await store.get_metrics(baseline_run_id)
    candidate_rows = await store.get_metrics(candidate_run_id)
    engine = MetricsEngine()
    baseline_aggregate = await engine.aggregate(baseline_run_id, store)
    candidate_aggregate = await engine.aggregate(candidate_run_id, store)
    keys = sorted(set(baseline_aggregate) | set(candidate_aggregate))
    results = compare_paired_metrics(baseline_rows, candidate_rows, keys, validity)

    regressions = [result for result in results.values() if result.decision == "candidate_worse"]
    improvements = [result for result in results.values() if result.decision == "candidate_better"]
    if not validity.decision_allowed:
        verdict = "no_decision"
        conclusion = "Comparison validity failed, so no winner or regression decision is reported."
    elif regressions:
        verdict = "regression"
        conclusion = f"The candidate has {len(regressions)} decision-bearing regression(s) after correction and effect thresholds."
    elif improvements:
        verdict = "pass"
        conclusion = f"No decision-bearing regression was found; {len(improvements)} metric(s) improved."
    else:
        verdict = "no_decision"
        conclusion = "No paired metric produced a sufficiently powered, significant, and practically meaningful decision."

    selected = (regressions or improvements or list(results.values()))[:1]
    affected_queries: list[Dict[str, Any]] = []
    query_diff_metric = None
    if validity.decision_allowed and selected:
        query_diff_metric = selected[0].metric
        pipeline_id, stage_index, metric_name, k, branch_id = parse_metric_key(query_diff_metric)
        baseline_scores = _scores_for(baseline_rows, pipeline_id, stage_index, metric_name, k, branch_id=branch_id)
        candidate_scores = _scores_for(candidate_rows, pipeline_id, stage_index, metric_name, k, branch_id=branch_id)
        for query_id in set(baseline_scores) & set(candidate_scores):
            affected_queries.append({
                "query_id": query_id,
                "baseline": baseline_scores[query_id],
                "candidate": candidate_scores[query_id],
                "delta": candidate_scores[query_id] - baseline_scores[query_id],
            })
        affected_queries.sort(key=lambda row: abs(row["delta"]), reverse=True)
        affected_queries = affected_queries[:20]

    results_dict = {key: value.to_dict() for key, value in results.items()}
    validity_dict = validity.to_dict()
    next_action = (
        "Fix the manifest differences and rerun before interpreting metric deltas."
        if not validity.decision_allowed else
        f"Inspect the first affected query for `{regressions[0].metric}` and locate its first candidate divergence."
        if regressions else
        "Review no-decision reasons and add paired queries before changing the retrieval configuration."
        if verdict == "no_decision" else
        "Validate the candidate on an independent Test Set before promotion."
    )
    return ReportModel(
        kind="comparison",
        run_id=f"{baseline_run_id}..{candidate_run_id}",
        title="Run Comparison",
        verdict=verdict,
        conclusion=conclusion,
        evidence_health="ready" if validity.decision_allowed else "invalid",
        evidence_reasons=[difference.detail for difference in validity.differences],
        metrics=results_dict,
        dominant_issue={"label": regressions[0].metric, "query_count": len(affected_queries)} if regressions else None,
        affected_queries=affected_queries,
        provenance={"baseline_manifest": baseline_manifest, "candidate_manifest": candidate_manifest},
        next_action=next_action,
        reproduce=f"retobs compare {baseline_run_id} {candidate_run_id} --db {db_path}",
        dashboard_url="http://127.0.0.1:4000/#/compare",
        comparison={
            "baseline_run_id": baseline_run_id,
            "candidate_run_id": candidate_run_id,
            "effect_orientation": "candidate_minus_baseline",
            "validity": validity_dict,
            "results": results_dict,
            "query_diff_metric": query_diff_metric,
        },
    )


class BenchmarkReport:
    """Result of a callable or config evaluation."""

    def __init__(self, artifacts: BenchmarkArtifacts, db_path: str, experiment_name: str):
        self._artifacts = artifacts
        self.db_path = db_path
        self.experiment_name = experiment_name
        self._report_model: Optional[ReportModel] = None

    @property
    def run_id(self) -> str:
        return self._artifacts.run_id

    @property
    def metrics(self) -> Dict[str, Any]:
        return self._artifacts.aggregated

    @property
    def diagnostics(self) -> list:
        return self._artifacts.diagnostics

    @property
    def pipeline_ids(self) -> list:
        return self._artifacts.pipeline_ids

    @property
    def report(self) -> ReportModel:
        if self._report_model is None:
            self._report_model = _run_sync(load_run_report(self.run_id, self.db_path))
        return self._report_model

    @property
    def manifest(self) -> Dict[str, Any]:
        from retrieval_observatory.store.sqlite import SQLiteStore

        async def _load() -> Dict[str, Any]:
            store = SQLiteStore(db_path=self.db_path)
            return await store.get_run_manifest(self.run_id) or {}

        return _run_sync(_load())

    def to_dict(self) -> Dict[str, Any]:
        return self.report.to_dict()

    def to_json(self) -> str:
        return self.report.to_json()

    def to_markdown(self) -> str:
        return self.report.to_markdown()

    def to_html(self) -> str:
        return self.report.to_html()

    def write(self, path: str | Path, *, format: Optional[str] = None) -> Path:
        return self.report.write(path, format=format)

    def export_config(self, path: str | Path) -> Path:
        import yaml

        target = Path(path)
        normalized = self.manifest.get("normalized_config")
        if not normalized:
            raise ValueError("This run does not include a normalized configuration.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(normalized, sort_keys=False), encoding="utf-8")
        return target

    def to_pandas(self):
        import pandas as pd

        rows = []
        for key, values in self.metrics.items():
            parts = key.split("|")
            row = {"pipeline": parts[0], "metric": parts[-1] if len(parts) > 1 else key}
            row.update(values if isinstance(values, dict) else {"value": values})
            rows.append(row)
        return pd.DataFrame(rows)

    def show(self) -> "BenchmarkReport":
        print(self.to_markdown())
        return self

    def serve(self, host: str = "0.0.0.0", port: int = 4000) -> None:
        import uvicorn

        from retrieval_observatory.dashboard.api import create_app
        from retrieval_observatory.dashboard.registry import DbRegistry

        app = create_app(registry=DbRegistry([self.db_path]))
        display_host = "localhost" if host in ("0.0.0.0", "::") else host
        print(f"Dashboard: http://{display_host}:{port}/#/runs/{self.run_id}/overview")
        uvicorn.run(app, host=host, port=port)

    def assert_no_regression(
        self,
        baseline: "BenchmarkReport | str",
        *,
        metric: Optional[str] = None,
        latency_regression_pct: float = 0.2,
    ) -> "BenchmarkReport":
        baseline_run = baseline.run_id if isinstance(baseline, BenchmarkReport) else str(baseline)
        findings = _run_sync(self._regressions(baseline_run, latency_regression_pct))
        if metric:
            findings = [finding for finding in findings if metric in finding.metric]
        if findings:
            lines = "\n".join(
                f"  - {finding.metric}: {finding.before:.4f} -> {finding.after:.4f} "
                f"(delta {finding.delta:+.4f}, q={finding.q_value:.3f}, {finding.severity})"
                for finding in findings
            )
            raise AssertionError(
                f"Retrieval regression vs baseline {baseline_run} (candidate {self.run_id}):\n{lines}"
            )
        return self

    async def _regressions(self, baseline_run: str, latency_regression_pct: float):
        from retrieval_observatory.advisor.regression import detect_regressions
        from retrieval_observatory.store.sqlite import SQLiteStore

        store = SQLiteStore(db_path=self.db_path)
        return await detect_regressions(
            baseline_run, self.run_id, store, latency_regression_pct=latency_regression_pct
        )

    def compare(self, baseline: "BenchmarkReport") -> Dict[str, Any]:
        """Validity-gated paired comparison with explicit baseline/candidate roles."""
        from retrieval_observatory.metrics.comparison import compare_paired_metrics, comparison_validity
        from retrieval_observatory.store.sqlite import SQLiteStore

        async def _compare() -> Dict[str, Any]:
            store = SQLiteStore(db_path=self.db_path)
            baseline_manifest = await store.get_run_manifest(baseline.run_id)
            candidate_manifest = await store.get_run_manifest(self.run_id)
            validity = comparison_validity([baseline_manifest, candidate_manifest])
            baseline_rows = await store.get_metrics(baseline.run_id)
            candidate_rows = await store.get_metrics(self.run_id)
            keys = sorted(set(baseline.metrics) & set(self.metrics))
            results = compare_paired_metrics(baseline_rows, candidate_rows, keys, validity)
            return {
                "baseline_run_id": baseline.run_id,
                "candidate_run_id": self.run_id,
                "validity": validity.to_dict(),
                "results": {key: value.to_dict() for key, value in results.items()},
            }

        return _run_sync(_compare())


def _run_sync(coro):
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()
