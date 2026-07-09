"""Unit tests for the Advisor MVP."""
import os
import tempfile

import pytest

from retrieval_observatory.advisor.regression import detect_regressions
from retrieval_observatory.advisor.recommend import recommend, compute_reliability
from retrieval_observatory.metrics.diagnostics import build_query_diagnostics
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.types import Document, PipelineResult, StageSnapshot


def _snap(docs, idx=0):
    return StageSnapshot(stage_index=idx, stage_id=f"s{idx}", documents=docs, latency_ms=10.0)


@pytest.mark.asyncio
async def test_regression_detects_quality_drop():
    d = tempfile.mkdtemp()
    store = SQLiteStore(os.path.join(d, "adv.db"))
    await store.init_db()

    await store.save_run("base", "exp", "{}")
    await store.save_run("cand", "exp", "{}")

    for i in range(20):
        qid = f"q{i}"
        good = PipelineResult(qid, "bm25", [_snap([Document("d1", "", 0.9, 1)])], 10.0, "OK")
        bad = PipelineResult(qid, "bm25", [_snap([])], 10.0, "OK")
        await store.save_result("base", good)
        await store.save_result("cand", bad)
        await store.save_metric("base", "bm25", qid, 0, "recall", 10, 1.0)
        await store.save_metric("cand", "bm25", qid, 0, "recall", 10, 0.0)

    findings = await detect_regressions("base", "cand", store)
    assert findings
    assert findings[0].delta < 0


@pytest.mark.asyncio
async def test_regression_quiet_on_identical_runs():
    d = tempfile.mkdtemp()
    store = SQLiteStore(os.path.join(d, "adv2.db"))
    await store.init_db()
    result = PipelineResult("q1", "bm25", [_snap([Document("d1", "", 0.9, 1)])], 10.0, "OK")
    for rid in ("base", "cand"):
        await store.save_run(rid, "exp", "{}")
        await store.save_result(rid, result)
        await store.save_metric(rid, "bm25", "q1", 0, "recall", 10, 0.8)
    findings = await detect_regressions("base", "cand", store)
    assert findings == []


@pytest.mark.asyncio
async def test_recommend_candidate_miss():
    d = tempfile.mkdtemp()
    store = SQLiteStore(os.path.join(d, "adv3.db"))
    await store.init_db()
    await store.save_run("r1", "exp", "{}")
    await store.save_run_manifest("r1", {})
    qrels = {"q1": {"d1": 2}, "q2": {"d2": 2}}
    results = [
        PipelineResult("q1", "bm25", [_snap([])], 10.0, "OK"),
        PipelineResult("q2", "bm25", [_snap([Document("d2", "", 0.9, 1)])], 10.0, "OK"),
    ]
    rows = build_query_diagnostics("r1", results, qrels)
    await store.save_query_diagnostics(rows)
    await store.save_metric("r1", "bm25", "q1", 0, "recall", 10, 0.0)
    await store.save_metric("r1", "bm25", "q2", 0, "recall", 10, 1.0)
    recs = await recommend("r1", store)
    actions = " ".join(r.action for r in recs)
    assert "retriever" in actions.lower() or "first-stage" in actions.lower()
    # Advisor Evolution: the candidate_miss recommendation carries grounded estimates.
    cand = next(r for r in recs if "candidate_miss" in r.affected_query_categories)
    assert cand.estimated_quality_improvement is not None
    assert cand.quality_metric == "recall@10"
    assert cand.confidence is not None
    assert cand.expected_value is not None
    assert cand.priority == 1  # highest expected value ranks first


@pytest.mark.asyncio
async def test_recommendations_ranked_by_expected_value():
    from retrieval_observatory.advisor.types import Recommendation
    from retrieval_observatory.advisor.recommend import _prioritize

    low = Recommendation("a", "r", [], 99, estimated_quality_improvement=0.05, confidence=0.5,
                         implementation_effort="M")
    high = Recommendation("b", "r", [], 99, estimated_quality_improvement=0.30, confidence=0.8,
                          implementation_effort="S")
    unest = Recommendation("c", "r", [], 99)  # no estimate -> tail
    ordered = _prioritize([low, unest, high])
    assert [r.action for r in ordered] == ["b", "a", "c"]
    assert ordered[0].priority == 1
    assert ordered[-1].expected_value is None


def test_simulate_operator_removal_reranker_hurts():
    from retrieval_observatory.advisor.simulate import simulate_operator_removal
    from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2

    def _trace(qid):
        # SOURCE surfaces gold d_gold at rank 1; a bad RERANK buries it below the good doc.
        source = OperatorSpan(
            op_id="src", op_type="SOURCE", op_name="bm25", parent_ids=[],
            status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=1.0,
            outputs=[
                Candidate(doc_id="d_gold", score=1.0, rank=1, origin_op_ids=["src"]),
                Candidate(doc_id="d_bad", score=0.5, rank=2, origin_op_ids=["src"]),
            ],
        )
        rerank = OperatorSpan(
            op_id="rr", op_type="RERANK", op_name="bad_rerank", parent_ids=["src"],
            status="FIRED", deterministic=False, replay_policy="OBSERVED_ABLATION", latency_ms=1.0,
            inputs=source.outputs,
            outputs=[Candidate(doc_id="d_bad", score=2.0, rank=1, origin_op_ids=["rr"])],
        )
        return RetrievalTraceV2(trace_id=f"t{qid}", run_id="r", query_id=qid, query_text="q",
                                pipeline_id="p", spans=[source, rerank], total_latency_ms=2.0,
                                final_op_id="rr")

    traces = [_trace(f"q{i}") for i in range(5)]
    qrels = {f"q{i}": {"d_gold": 1} for i in range(5)}
    result = simulate_operator_removal(traces, qrels, "rr", metric="recall", k=1)
    assert result is not None
    assert result.n_queries == 5
    # Removing the bad reranker restores the gold doc -> positive delta (removal helps).
    assert result.delta > 0
    assert result.assumptions is not None


@pytest.mark.asyncio
async def test_query_lineage_for_forge_query():
    d = tempfile.mkdtemp()
    store = SQLiteStore(os.path.join(d, "lin.db"))
    await store.init_db()
    import json

    await store.save_forge_dataset("ds1", json.dumps({"n_queries": 1}), "", "/tmp/out")
    await store.save_forge_scenarios("ds1", json.dumps([{
        "scenario_id": "sc1", "scenario_type": "temporal", "anchor_doc_ids": [], "evidence_summary": "test",
    }]))
    await store.save_forge_queries("ds1", json.dumps([{
        "query_id": "fq1", "text": "when did X happen", "scenario_id": "sc1",
        "query_type": "temporal", "difficulty_label": "hard", "failure_category": "temporal",
        "validated": False, "positive_doc_ids": ["d1"],
    }]))
    await store.save_run("run1", "exp", "{}")
    await store.save_run_queries("run1", [type("Q", (), {"query_id": "fq1", "text": "when did X happen"})()], "custom")

    lineage = await store.get_query_lineage("fq1")
    assert lineage["origin"]["source"] == "forge"
    assert lineage["origin"]["forge"]["dataset_id"] == "ds1"
    assert len(lineage["evaluations"]) == 1


@pytest.mark.asyncio
async def test_reliability_score_has_components():
    d = tempfile.mkdtemp()
    store = SQLiteStore(os.path.join(d, "rel.db"))
    await store.init_db()
    await store.save_run("r1", "exp", "{}")
    await store.save_run_manifest("r1", {"latency_budget_ms": 500})
    await store.save_metric("r1", "bm25", "q1", 0, "recall", 10, 0.9)
    score = await compute_reliability("r1", store)
    assert 0 <= score.value <= 1
    assert "recall_at_10" in score.components
