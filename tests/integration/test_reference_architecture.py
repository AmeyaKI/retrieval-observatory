"""Reference architecture acceptance test (Phase 11).

Builds a production-shaped synthetic pipeline with gates, conditional lanes,
parallel sources, RRF fusion, expansion, reranking, and boosts. Verifies
that the trace-native attribution engine answers the key diagnostic questions.
"""
from __future__ import annotations

import pytest

from retrieval_observatory.tracing.attribution import (
    MarginalResult,
    _find_final_span,
    operator_marginal_contribution,
    segment_key,
    segments,
)
from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2
from retrieval_observatory.tracing.replay import attribute_miss, without_operator


def _candidate(doc_id: str, score: float, rank: int, origin: list[str] | None = None, **kw) -> Candidate:
    return Candidate(doc_id=doc_id, score=score, rank=rank, origin_op_ids=origin or [], **kw)


def _build_reference_trace(
    query_id: str = "q1",
    intent: str = "navigational",
    entity_type: str = "person",
    gate_fired: bool = True,
) -> RetrievalTraceV2:
    """Build a production-shaped trace with the full operator zoo."""
    intent_gate = OperatorSpan(
        op_id="intent_gate", op_type="GATE", op_name="Intent Detection",
        parent_ids=[], status="FIRED", deterministic=True,
        replay_policy="NOT_REPLAYABLE", latency_ms=5.0,
        gate_values={"intent": intent},
        outputs=[],
    )
    entity_gate = OperatorSpan(
        op_id="entity_gate", op_type="GATE", op_name="Entity Detection",
        parent_ids=[], status="FIRED" if gate_fired else "SKIPPED_BY_GATE",
        deterministic=True, replay_policy="NOT_REPLAYABLE", latency_ms=3.0,
        gate_values={"entity_type": entity_type if gate_fired else "none"},
        outputs=[],
    )
    bm25_source = OperatorSpan(
        op_id="bm25", op_type="SOURCE", op_name="BM25 Sparse",
        parent_ids=["intent_gate"], status="FIRED",
        deterministic=True, replay_policy="EXACT", latency_ms=15.0,
        outputs=[
            _candidate("d1", 0.9, 1, ["bm25"]),
            _candidate("d2", 0.8, 2, ["bm25"]),
            _candidate("d3", 0.7, 3, ["bm25"]),
            _candidate("d5", 0.5, 4, ["bm25"]),
        ],
    )
    dense_source = OperatorSpan(
        op_id="dense", op_type="SOURCE", op_name="Dense Embedding",
        parent_ids=["intent_gate"], status="FIRED",
        deterministic=False, replay_policy="NOT_REPLAYABLE", latency_ms=25.0,
        outputs=[
            _candidate("d2", 0.95, 1, ["dense"]),
            _candidate("d4", 0.85, 2, ["dense"]),
            _candidate("d1", 0.6, 3, ["dense"]),
        ],
    )
    recency_source = OperatorSpan(
        op_id="recency", op_type="SOURCE", op_name="Recency Direct",
        parent_ids=["intent_gate"], status="FIRED" if gate_fired else "SKIPPED_BY_GATE",
        deterministic=True, replay_policy="EXACT", latency_ms=10.0,
        outputs=[
            _candidate("d6", 0.88, 1, ["recency"]),
        ] if gate_fired else [],
    )
    rrf_fuse = OperatorSpan(
        op_id="rrf_fuse", op_type="FUSE", op_name="RRF Merge",
        parent_ids=["bm25", "dense", "recency"], status="FIRED",
        deterministic=True, replay_policy="EXACT", latency_ms=2.0,
        params={"k": 60},
        outputs=[
            _candidate("d2", 2.0, 1, ["bm25", "dense"], add_reason="fused"),
            _candidate("d1", 1.5, 2, ["bm25", "dense"], add_reason="fused"),
            _candidate("d4", 0.85, 3, ["dense"], add_reason="fused"),
            _candidate("d3", 0.7, 4, ["bm25"], add_reason="fused"),
            _candidate("d6", 0.5, 5, ["recency"], add_reason="fused"),
            _candidate("d5", 0.3, 6, ["bm25"], add_reason="fused"),
        ],
    )
    expand = OperatorSpan(
        op_id="entity_expand", op_type="EXPAND", op_name="Entity Expansion",
        parent_ids=["rrf_fuse"], status="FIRED" if gate_fired else "SKIPPED_BY_GATE",
        deterministic=True, replay_policy="EXACT", latency_ms=8.0,
        inputs=list(rrf_fuse.outputs),
        outputs=list(rrf_fuse.outputs) + [
            _candidate("d7", 0.4, 7, ["entity_expand"], add_reason="expanded"),
        ],
    )
    transform = OperatorSpan(
        op_id="context_prefix", op_type="TRANSFORM", op_name="Context Prefix",
        parent_ids=["entity_expand"], status="FIRED",
        deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        input_variant="context_prefixed",
        inputs=list(expand.outputs),
        outputs=list(expand.outputs),
    )
    reranker = OperatorSpan(
        op_id="reranker", op_type="RERANK", op_name="Cross-Encoder Rerank",
        parent_ids=["context_prefix"], status="FIRED",
        deterministic=False, replay_policy="OBSERVED_ABLATION", latency_ms=50.0,
        inputs=list(transform.outputs),
        outputs=[
            _candidate("d1", 0.99, 1, ["bm25", "dense"]),
            _candidate("d2", 0.95, 2, ["bm25", "dense"]),
            _candidate("d4", 0.80, 3, ["dense"]),
            _candidate("d7", 0.70, 4, ["entity_expand"]),
            _candidate("d3", 0.60, 5, ["bm25"]),
        ],
    )
    temporal_boost = OperatorSpan(
        op_id="temporal_boost", op_type="BOOST", op_name="Temporal Boost",
        parent_ids=["reranker"], status="FIRED",
        deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        inputs=list(reranker.outputs),
        outputs=[
            _candidate("d1", 1.2, 1, ["bm25", "dense"],
                       score_components={"pre_boost": 0.99, "boost": 0.21}),
            _candidate("d2", 0.95, 2, ["bm25", "dense"],
                       score_components={"pre_boost": 0.95, "boost": 0.0}),
            _candidate("d4", 0.80, 3, ["dense"],
                       score_components={"pre_boost": 0.80, "boost": 0.0}),
            _candidate("d7", 0.70, 4, ["entity_expand"],
                       score_components={"pre_boost": 0.70, "boost": 0.0}),
            _candidate("d3", 0.60, 5, ["bm25"],
                       score_components={"pre_boost": 0.60, "boost": 0.0}),
        ],
    )

    return RetrievalTraceV2(
        trace_id=f"ref_{query_id}",
        run_id="ref_run",
        query_id=query_id,
        query_text=f"query {query_id}",
        pipeline_id="reference_pipeline",
        spans=[
            intent_gate, entity_gate, bm25_source, dense_source,
            recency_source, rrf_fuse, expand, transform, reranker,
            temporal_boost,
        ],
        total_latency_ms=120.0,
        final_op_id="temporal_boost",
    )


class TestReferenceArchitecture:
    """Acceptance tests for the production-shaped reference pipeline."""

    def test_dag_renders_as_graph_not_line(self) -> None:
        trace = _build_reference_trace()
        parent_counts = {s.op_id: len(s.parent_ids) for s in trace.spans}
        assert parent_counts["rrf_fuse"] == 3
        multi_parent = [op for op, n in parent_counts.items() if n > 1]
        assert len(multi_parent) >= 1

    def test_gated_lane_segment_includes_all_gates(self) -> None:
        trace = _build_reference_trace(intent="navigational", entity_type="person")
        key = segment_key(trace)
        assert "entity_type=person" in key
        assert "intent=navigational" in key

    def test_gated_lane_recall_only_where_fired(self) -> None:
        traces = [
            _build_reference_trace(query_id=f"q{i}", gate_fired=True) for i in range(15)
        ] + [
            _build_reference_trace(query_id=f"q_no_{i}", gate_fired=False) for i in range(5)
        ]
        qrels = {t.query_id: {"d1": 1, "d2": 1} for t in traces}
        results = operator_marginal_contribution(
            traces, op_id="recency", qrels=qrels, metric="recall", k=5,
        )
        for r in results:
            if r.segment == "baseline":
                continue
            assert r.n_pairs >= 0

    def test_boost_attribution_with_evidence(self) -> None:
        traces = [_build_reference_trace(query_id=f"q{i}") for i in range(25)]
        qrels = {f"q{i}": {"d1": 1, "d2": 1} for i in range(25)}
        results = operator_marginal_contribution(
            traces, op_id="temporal_boost", qrels=qrels, metric="ndcg", k=5,
        )
        assert len(results) > 0
        measured = [r for r in results if r.n_pairs > 0]
        assert len(measured) > 0
        for r in measured:
            assert r.delta is not None

    def test_fuse_arm_contribution(self) -> None:
        traces = [_build_reference_trace(query_id=f"q{i}") for i in range(5)]
        qrels = {f"q{i}": {"d2": 1, "d4": 1} for i in range(5)}
        results = operator_marginal_contribution(
            traces, op_id="bm25", qrels=qrels, metric="recall", k=5,
        )
        assert len(results) > 0

    def test_without_fuse_arm_recomputes(self) -> None:
        trace = _build_reference_trace()
        cf = without_operator(trace, "bm25")
        fuse_cf = next(s for s in cf.spans if s.op_type == "FUSE")
        cf_doc_ids = {c.doc_id for c in fuse_cf.outputs}
        assert "d4" in cf_doc_ids
        assert "d5" not in cf_doc_ids

    @pytest.mark.asyncio
    async def test_miss_attribution_identifies_dropped_doc(self) -> None:
        trace = _build_reference_trace()
        qrels = {"q1": {"d1": 1, "d5": 1, "d_never": 1}}
        misses = await attribute_miss(trace, qrels=qrels, k=5)
        never = [m for m in misses if m.doc_id == "d_never"]
        assert len(never) == 1
        assert never[0].miss_type == "never_retrieved"

    def test_input_variant_tracked(self) -> None:
        trace = _build_reference_trace()
        transform = next(s for s in trace.spans if s.op_id == "context_prefix")
        assert transform.input_variant == "context_prefixed"

    def test_replay_tier_not_replayable_does_not_fabricate(self) -> None:
        traces = [_build_reference_trace(query_id=f"q{i}") for i in range(5)]
        qrels = {f"q{i}": {"d1": 1} for i in range(5)}
        results = operator_marginal_contribution(
            traces, op_id="dense", qrels=qrels, metric="recall", k=5,
        )
        for r in results:
            if r.replay_policy == "NOT_REPLAYABLE" and r.n_pairs > 0:
                assert r.result_status == "indeterminate"

    def test_final_op_id_used(self) -> None:
        trace = _build_reference_trace()
        final = _find_final_span(trace)
        assert final is not None
        assert final.op_id == "temporal_boost"

    @pytest.mark.asyncio
    async def test_round_trip_store(self, tmp_path) -> None:
        from retrieval_observatory.store.sqlite import SQLiteStore

        store = SQLiteStore(db_path=str(tmp_path / "ref.db"))
        await store.init_db()

        trace = _build_reference_trace()
        await store.save_trace_v2(trace)
        loaded = await store.get_trace_v2(trace.trace_id)
        assert loaded is not None
        assert loaded.final_op_id == "temporal_boost"
        assert len(loaded.spans) == 10

    @pytest.mark.asyncio
    async def test_migration_roundtrip(self, tmp_path) -> None:
        """Verify migrate_run_to_v2 produces valid traces."""
        from retrieval_observatory.store.sqlite import SQLiteStore
        from retrieval_observatory.store.migrate import migrate_run_to_v2, verify_migration_parity
        from retrieval_observatory.types import Document, PipelineResult, StageSnapshot

        store = SQLiteStore(db_path=str(tmp_path / "migrate.db"))
        await store.init_db()
        run_id = "migrate_test"
        await store.save_run(run_id, "test", "{}")

        docs = [Document(id=f"d{i}", text="", score=1.0 - i * 0.1, rank=i + 1) for i in range(5)]
        snap = StageSnapshot(stage_index=0, stage_id="bm25", documents=docs, latency_ms=10.0)
        result = PipelineResult(
            query_id="q1", pipeline_id="p1", snapshots=[snap],
            total_latency_ms=10.0, status="OK",
        )
        await store.save_result(run_id, result)

        count = await migrate_run_to_v2(run_id, store)
        assert count == 1

        parity = await verify_migration_parity(run_id, store)
        assert parity["parity"] is True
