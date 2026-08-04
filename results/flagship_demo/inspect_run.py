#!/usr/bin/env python3
"""Summarize a persisted demo Run: per-stage quality, routing, and candidate lineage.

Reads only what retobs stored. Nothing here recomputes retrieval.

Usage:
    python inspect_run.py                        # latest run in the demo database
    python inspect_run.py --run-id 5201e4bf
    python inspect_run.py --trace <query_id>     # full stage-by-stage read-out for one query
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from pathlib import Path

from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.lineage import build_candidate_lineage
from retrieval_observatory.tracing.lineage_accounting import build_stage_loss_accounting

HERE = Path(__file__).parent
DEFAULT_DB = str(HERE / ".retobs" / "demo.db")

OUTCOMES = (
    "relevant_retained",
    "relevant_dropped_at_stage",
    "relevant_lost_upstream",
    "irrelevant_removed",
    "irrelevant_retained",
    "unknown_relevance",
    "lineage_incomplete",
)


async def _load(db_path: str, run_id: str | None):
    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    runs = await store.list_runs()
    if not runs:
        raise SystemExit(f"no runs in {db_path}")
    if run_id is None:
        run_id = runs[0]["run_id"]
    metrics = await store.get_metrics(run_id)
    traces = await store.get_traces(run_id)
    qrels = await store.get_qrels(run_id) if hasattr(store, "get_qrels") else {}
    manifest = await store.get_run_manifest(run_id) or {}
    queries = {row["query_id"]: row for row in await store.get_run_queries(run_id)}
    return run_id, metrics, traces, qrels, manifest, queries


def summarize_quality(metrics: list[dict]) -> None:
    grouped: dict[tuple, list[float]] = defaultdict(list)
    for row in metrics:
        if row["metric_name"] not in ("recall", "ndcg"):
            continue
        grouped[(row["stage_index"], row.get("branch_id"), row["metric_name"], row["k"])].append(row["value"])

    print("\nPER-STAGE QUALITY")
    print(f"  {'stage':<7}{'operator / branch':<22}{'recall@10':>11}{'ndcg@10':>10}{'n':>6}")
    stages: dict[tuple, dict] = defaultdict(dict)
    for (stage, branch, metric, _k), values in grouped.items():
        stages[(stage, branch)][metric] = (sum(values) / len(values), len(values))
    for (stage, branch) in sorted(stages, key=lambda key: (key[0], key[1] or "")):
        cell = stages[(stage, branch)]
        recall, n = cell.get("recall", (float("nan"), 0))
        ndcg, _ = cell.get("ndcg", (float("nan"), 0))
        print(f"  {stage:<7}{(branch or '(spine)'):<22}{recall:>11.4f}{ndcg:>10.4f}{n:>6}")


def summarize_routing(traces: list) -> None:
    routes: dict[str, Counter] = defaultdict(Counter)
    statuses: Counter = Counter()
    outputs: dict[str, list[int]] = defaultdict(list)
    for trace in traces:
        for span in trace.spans:
            statuses[(span.op_id, span.status)] += 1
            if span.status == "FIRED":
                outputs[span.op_id].append(len(span.outputs))
            if span.op_type == "GATE" and span.status == "FIRED":
                routes[span.op_id][str(span.gate_values.get("selected_route"))] += 1

    print("\nROUTING")
    for gate, counts in routes.items():
        total = sum(counts.values())
        detail = "  ".join(f"{route}={n} ({n / total:.0%})" for route, n in counts.most_common())
        print(f"  {gate:<20}{detail}")

    print("\nOPERATOR ACTIVITY")
    print(f"  {'operator':<20}{'fired':>7}{'skipped':>9}{'mean candidates out':>22}")
    seen: list[str] = []
    for trace in traces:
        for span in trace.spans:
            if span.op_id not in seen:
                seen.append(span.op_id)
    for op_id in seen:
        fired = statuses[(op_id, "FIRED")]
        skipped = statuses[(op_id, "SKIPPED_BY_GATE")]
        counts = outputs.get(op_id, [])
        mean = f"{sum(counts) / len(counts):.1f}" if counts else "-"
        print(f"  {op_id:<20}{fired:>7}{skipped:>9}{mean:>22}")


def summarize_lineage(traces: list, qrels: dict) -> None:
    totals: Counter = Counter()
    by_operator: dict[str, Counter] = defaultdict(Counter)
    for trace in traces:
        graph = build_candidate_lineage(
            trace,
            qrels_for_query=qrels.get(trace.query_id, {}),
            qrel_chunk_mapping_complete=True,
        )
        accounting = build_stage_loss_accounting(graph)
        for outcome in OUTCOMES:
            totals[outcome] += getattr(accounting, outcome)
        for op_id, counts in accounting.by_operator.items():
            for outcome in OUTCOMES:
                by_operator[op_id][outcome] += getattr(counts, outcome)

    grand = sum(totals.values()) or 1
    print("\nCANDIDATE LINEAGE OUTCOMES (all candidates, all queries)")
    for outcome in OUTCOMES:
        n = totals[outcome]
        if n:
            print(f"  {outcome:<28}{n:>8,}  {n / grand:>6.1%}")
    incomplete = totals["lineage_incomplete"] / grand
    print(f"\n  tracing health: lineage_incomplete = {incomplete:.1%}"
          f"  {'(healthy)' if incomplete < 0.02 else '(INVESTIGATE)'}")
    print("  note: unknown_relevance is high by construction — HotpotQA labels only the")
    print("        supporting paragraphs, so every other retrieved paragraph is unjudged.")


def pick_lineage_example(traces: list, qrels: dict, metrics: list[dict]) -> str | None:
    """Choose one query for the lineage deep-dive, by evidence rather than by eye.

    Wanted: a two-hop (bridge) question, at HotpotQA's `hard` level, whose trace is complete
    enough to trust — no candidate left `lineage_incomplete` — and which actually lost a gold
    document somewhere in the pipeline. A query that simply succeeded has nothing to explain.
    """
    metadata: dict[str, dict] = {}
    for row in metrics:
        value = row.get("query_metadata_json") or row.get("query_metadata")
        if isinstance(value, str):
            value = json.loads(value)
        if isinstance(value, dict):
            metadata.setdefault(row["query_id"], value)

    complete_bridge: list[str] = []
    for trace in traces:
        meta = metadata.get(trace.query_id, {})
        if meta.get("type") != "bridge" or meta.get("level") != "hard":
            continue
        graph = build_candidate_lineage(
            trace, qrels_for_query=qrels.get(trace.query_id, {}), qrel_chunk_mapping_complete=True
        )
        outcomes = [passport.outcome.kind for passport in graph.candidates.values()]
        if "lineage_incomplete" in outcomes:
            continue
        complete_bridge.append(trace.query_id)
        if build_stage_loss_accounting(graph).relevant_dropped_at_stage:
            return trace.query_id
    # Small samples may contain no query that lost a gold document. Any completely traced
    # bridge query still shows the full read-out; it just has less to explain.
    return complete_bridge[0] if complete_bridge else None


def print_trace(traces: list, qrels: dict, queries: dict, query_id: str, metrics: list[dict]) -> None:
    trace = next((t for t in traces if t.query_id == query_id), None)
    if trace is None:
        raise SystemExit(f"query {query_id} not in this run")
    row = queries.get(query_id, {})
    metadata = next(
        (m.get("query_metadata_json") or m.get("query_metadata")
         for m in metrics if m["query_id"] == query_id),
        None,
    )
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    relevant = {doc_id for doc_id, grade in qrels.get(query_id, {}).items() if grade > 0}

    print("=" * 96)
    print(f"QUERY {query_id}")
    print(f"  text     {row.get('query_text', trace.query_text)}")
    # `run_queries` stores only ids and text; the slice metadata lives on the metric rows.
    print(f"  metadata {json.dumps(metadata, sort_keys=True) if metadata else '(none)'}")
    print(f"  gold     {sorted(relevant)}")
    print(f"  status   {trace.status}   wall {trace.timing.wall_clock_ms:.0f}ms")
    print("=" * 96)

    graph = build_candidate_lineage(trace, qrels_for_query=qrels.get(query_id, {}),
                                    qrel_chunk_mapping_complete=True)

    for span in trace.spans:
        gate = ""
        if span.op_type == "GATE" and span.gate_values:
            gate = f"  -> route '{span.gate_values.get('selected_route')}'"
        n_in = sum(len(group) for group in span.input_groups.values())
        print(f"\n  {span.op_id}  [{span.op_type}]  {span.status}{gate}")
        print(f"    in {n_in:>4}  out {len(span.outputs):>4}   {span.latency_ms:>7.1f}ms")
        if span.status != "FIRED":
            continue
        hits = [c for c in span.outputs if c.doc_id in relevant]
        print(f"    gold candidates present in output: {len(hits)}/{len(relevant)}"
              + (f"   ranks {[c.output_rank or c.rank for c in hits]}" if hits else ""))
        dropped_gold = [
            c.doc_id
            for group in span.input_groups.values()
            for c in group
            if c.doc_id in relevant and c.output_rank is None
        ]
        if dropped_gold:
            print(f"    !! gold candidate dropped here: {dropped_gold}")

    print("\n  CANDIDATE OUTCOMES FOR THIS QUERY")
    accounting = build_stage_loss_accounting(graph)
    for outcome in OUTCOMES:
        n = getattr(accounting, outcome)
        if n:
            print(f"    {outcome:<28}{n:>6}")
    print("\n  BY OPERATOR")
    for op_id, counts in accounting.by_operator.items():
        parts = [f"{o}={getattr(counts, o)}" for o in OUTCOMES if getattr(counts, o)]
        print(f"    {op_id:<22}{'  '.join(parts)}")

    print("\n  GOLD CANDIDATE JOURNEYS")
    for passport in graph.candidates.values():
        if passport.logical_chunk_id not in relevant:
            continue
        route = passport.routes[0] if passport.routes else None
        path = " -> ".join(f"{s.op_id}#{s.output_rank or s.rank}" for s in route.stages) if route else "(none)"
        print(f"    {passport.logical_chunk_id}")
        print(f"      outcome  {passport.outcome.kind}"
              + (f"  at {passport.outcome.operator_id}" if passport.outcome.operator_id else ""))
        print(f"      path     {path}")
        print(f"      in final result: {passport.final_context_member}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--trace", default=None, help="query_id to print a full stage read-out for")
    parser.add_argument(
        "--pick",
        action="store_true",
        help="select a bridge / level=hard query with complete tracing that lost a gold document",
    )
    args = parser.parse_args()

    run_id, metrics, traces, qrels, manifest, queries = asyncio.run(_load(args.db, args.run_id))

    if args.pick:
        print(pick_lineage_example(traces, qrels, metrics) or "no matching query")
        return 0

    if args.trace:
        print_trace(traces, qrels, queries, args.trace, metrics)
        return 0

    identity = manifest.get("release_identity", {})
    print(f"RUN {run_id}  ({manifest.get('normalized_config', {}).get('experiment', {}).get('name', '?')})")
    print(f"  queries {manifest.get('counts', {}).get('attempted')}"
          f"  completed {manifest.get('counts', {}).get('completed')}"
          f"  metric-eligible {manifest.get('counts', {}).get('metric_eligible')}")
    print("  release identity:")
    for key in ("corpus_revision", "index_build_id", "chunking_revision",
                "embedding_model_revision", "reranker_model_revision"):
        print(f"    {key:<26}{identity.get(key)}")

    summarize_quality(metrics)
    summarize_routing(traces)
    summarize_lineage(traces, qrels)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
