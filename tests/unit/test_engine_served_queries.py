"""Metrics engine: gate-skipped spans score served queries only, failures are attributed
per pipeline and emitted per query, and `_std` is a sample standard deviation."""
from __future__ import annotations

import math

import pytest

from retrieval_observatory.metrics.comparison import rank_metric_keys
from retrieval_observatory.metrics.engine import MetricsEngine, _std
from retrieval_observatory.sdk.report import _headline_metrics
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming


class MemStore:
    def __init__(self, status_counts_by_pipeline=None):
        self.rows = []
        self._by_pipeline = status_counts_by_pipeline

    async def save_metrics_batch(self, rows):
        self.rows += rows

    async def get_metrics(self, run_id):
        return list(self.rows)

    async def get_run_status_counts(self, run_id):
        return {}

    async def get_run_status_counts_by_pipeline(self, run_id):
        return dict(self._by_pipeline or {})


def _cands(*ids):
    return tuple(Candidate(doc_id=d, score=1.0, rank=i + 1) for i, d in enumerate(ids))


def _gated_trace(qid, route, status="OK"):
    """src -> gate -> (fast | rerank): the gate routes each query down exactly one branch."""
    src = OperatorSpan("src", "SOURCE", "src", (), "FIRED", 1.0, outputs=_cands("rel", "x"))
    gate = OperatorSpan(
        "gate", "GATE", "gate", ("src",), "FIRED", 0.1,
        input_groups={"src": src.outputs}, outputs=src.outputs, gate_values={"route": route},
    )
    fast = OperatorSpan(
        "fast", "SELECT", "fast", ("gate",), "FIRED" if route == "fast" else "SKIPPED_BY_GATE", 0.1,
        input_groups={"gate": gate.outputs} if route == "fast" else {},
        outputs=_cands("rel") if route == "fast" else (),
    )
    rerank = OperatorSpan(
        "rerank", "RERANK", "rerank", ("gate",), "FIRED" if route == "rerank" else "SKIPPED_BY_GATE", 5.0,
        input_groups={"gate": gate.outputs} if route == "rerank" else {},
        outputs=_cands("rel") if route == "rerank" else (),
    )
    spans = (src, gate, fast, rerank)
    return RetrievalTrace(
        f"t{qid}", "svc", "run", qid, "q", "p", spans,
        final_op_ids=("fast", "rerank"), timing=TraceTiming.from_spans(spans), status=status,
    )


def _engine():
    return MetricsEngine(recall_at_k_values=[10], ndcg_at_k_values=[], compute_mrr=False, compute_map=False)


@pytest.mark.asyncio
async def test_gate_skipped_branch_is_scored_on_served_queries_only():
    """Three queries routed to `fast`, one to `rerank`; every served query has recall 1.0.

    A SKIPPED_BY_GATE span has no outputs, so scoring it wrote recall 0 for every query
    routed elsewhere and diluted each branch mean by the routing fraction (0.75 / 0.25).
    """
    traces = [_gated_trace("q1", "fast"), _gated_trace("q2", "fast"), _gated_trace("q3", "fast"), _gated_trace("q4", "rerank")]
    qrels = {q: {"rel"} for q in ("q1", "q2", "q3", "q4")}
    store = MemStore()
    engine = _engine()
    await engine.compute_from_traces("run", store, traces, qrels)
    agg = await engine.aggregate("run", store, n_bootstrap=10)

    fast = agg["p|stage2|recall@10|branch=fast"]
    rerank = agg["p|stage2|recall@10|branch=rerank"]
    assert (fast["mean"], fast["n"], fast["zero_count"]) == (1.0, 3, 0)
    assert (rerank["mean"], rerank["n"], rerank["zero_count"]) == (1.0, 1, 0)
    # The spine still covers every query, and the CI is computed on each key's own n.
    assert agg["p|stage0|recall@10"]["n"] == 4
    assert fast["ci_low"] == fast["ci_high"] == 1.0
    skipped_rows = [r for r in store.rows if r["metric_name"] == "recall" and r["stage_index"] == 2]
    assert len(skipped_rows) == 4  # one row per served (query, branch), none for skipped spans


@pytest.mark.asyncio
async def test_failure_and_timeout_rates_are_attributed_per_pipeline():
    """pipeA: 10 OK. pipeB: 5 OK + 5 ERROR. Run-wide counts must not be stamped on pipeA."""
    store = MemStore(status_counts_by_pipeline={"pipeA": {"OK": 10}, "pipeB": {"OK": 5, "ERROR": 5}})
    for pid, n in (("pipeA", 10), ("pipeB", 5)):
        store.rows += [
            {"pipeline_id": pid, "stage_index": 0, "metric_name": "recall", "k": 10, "value": 1.0, "query_id": f"q{i}", "branch_id": None}
            for i in range(n)
        ]
    agg = await MetricsEngine().aggregate("r", store, n_bootstrap=50)

    assert agg["pipeA|stage-1|failure_rate@0"]["mean"] == 0.0
    assert agg["pipeB|stage-1|failure_rate@0"]["mean"] == 0.5
    assert agg["pipeA|stage-1|timeout_rate@0"]["mean"] == 0.0
    assert agg["pipeB|stage-1|dropout_count@0"]["mean"] == 5.0
    assert agg["pipeB|stage-1|failure_rate@0"]["n"] == 10
    assert agg["pipeA|stage-1|failure_rate@0"]["n"] == 10
    # A count has no sampling distribution: no fake zero-width CI.
    count_row = agg["pipeB|stage-1|dropout_count@0"]
    assert count_row["ci_low"] is None and count_row["ci_high"] is None and count_row["std"] is None
    # A rate is a mean of indicators and gets a real bootstrap interval around it.
    rate_row = agg["pipeB|stage-1|failure_rate@0"]
    assert rate_row["ci_low"] <= 0.5 <= rate_row["ci_high"]
    assert rate_row["ci_low"] < rate_row["ci_high"]


@pytest.mark.asyncio
async def test_run_wide_counts_are_not_stamped_onto_every_pipeline():
    """A store offering only run-wide counts cannot attribute them across two pipelines."""

    class RunWideStore(MemStore):
        async def get_run_status_counts(self, run_id):
            return {"OK": 15, "TIMEOUT": 5}

        get_run_status_counts_by_pipeline = None  # type: ignore[assignment]

    store = RunWideStore()
    for pid, n in (("bm25", 10), ("dense", 5)):
        store.rows += [
            {"pipeline_id": pid, "stage_index": 0, "metric_name": "recall", "k": 10, "value": 1.0, "query_id": f"q{i}", "branch_id": None}
            for i in range(n)
        ]
    agg = await MetricsEngine().aggregate("r", store, n_bootstrap=10)
    assert not [k for k in agg if "failure_rate" in k or "timeout_rate" in k or "dropout_count" in k]

    # With a single pipeline the run-wide counts are that pipeline's counts.
    single = RunWideStore()
    single.rows = [r for r in store.rows if r["pipeline_id"] == "bm25"]
    agg = await MetricsEngine().aggregate("r", single, n_bootstrap=10)
    assert agg["bm25|stage-1|failure_rate@0"]["mean"] == 0.25


@pytest.mark.asyncio
async def test_sqlite_status_counts_by_pipeline(tmp_path):
    store = SQLiteStore(db_path=str(tmp_path / "status.db"))
    await store.init_db()
    await store.save_run("run", "exp", "{}")
    await store.save_traces([
        _gated_trace("q1", "fast"),
        _gated_trace("q2", "fast", status="TIMEOUT"),
        RetrievalTrace("t3", "svc", "run", "q1", "q", "other", (), final_op_ids=(), status="ERROR"),
    ])

    assert await store.get_run_status_counts_by_pipeline("run") == {
        "p": {"OK": 1, "TIMEOUT": 1},
        "other": {"ERROR": 1},
    }
    assert await store.get_run_status_counts("run") == {"OK": 1, "TIMEOUT": 1, "ERROR": 1}


@pytest.mark.asyncio
async def test_failed_traces_emit_per_query_failure_indicator_rows():
    traces = [
        _gated_trace("q1", "fast"),
        _gated_trace("q2", "fast", status="TIMEOUT"),
        _gated_trace("q3", "fast", status="ERROR"),
        _gated_trace("q4", "fast"),  # no qrels: not scoreable, no rows at all
    ]
    qrels = {q: {"rel"} for q in ("q1", "q2", "q3")}
    store = MemStore()
    await _engine().compute_from_traces("run", store, traces, qrels)

    def value(qid, name):
        return [r["value"] for r in store.rows if r["query_id"] == qid and r["metric_name"] == name and r["stage_index"] == -1]

    assert value("q1", "failure") == [0.0] and value("q1", "timeout") == [0.0]
    assert value("q2", "failure") == [1.0] and value("q2", "timeout") == [1.0]
    assert value("q3", "failure") == [1.0] and value("q3", "timeout") == [0.0]
    assert value("q4", "failure") == []
    # Failed traces contribute nothing else.
    assert not [r for r in store.rows if r["query_id"] in ("q2", "q3") and r["metric_name"] == "recall"]
    agg = await _engine().aggregate("run", store, n_bootstrap=10)
    assert agg["p|stage-1|failure@0"]["mean"] == pytest.approx(2 / 3)
    assert agg["p|stage-1|failure@0"]["n"] == 3


def test_failure_indicator_keys_rank_and_classify_as_operational():
    keys = ["p|stage-1|failure@0", "p|stage-1|timeout@0", "p|stage0|recall@10", "p|stage1|ndcg@10"]
    ranked = rank_metric_keys(keys)
    assert ranked[:2] == ["p|stage1|ndcg@10", "p|stage0|recall@10"]
    assert set(ranked[2:]) == {"p|stage-1|failure@0", "p|stage-1|timeout@0"}

    metrics = {k: {"mean": 0.5} for k in keys}
    metrics["p|stage-1|latency_p50@0"] = {"mean": 3.0}
    headline = _headline_metrics(metrics)
    assert "p|stage1|ndcg@10" in headline
    assert "p|stage-1|failure@0" not in headline  # operational, never a quality headline


def test_std_is_sample_standard_deviation():
    assert _std([1.0, 2.0, 3.0, 4.0]) == pytest.approx(math.sqrt(5 / 3))
    assert _std([1.0]) == 0.0
    assert _std([]) == 0.0
