from __future__ import annotations

from dataclasses import replace
from fastapi.testclient import TestClient
import pytest

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.lineage import build_candidate_lineage
from retrieval_observatory.tracing.model import CaptureMetadata, Candidate, OperatorSpan, RetrievalTrace


def _candidate(candidate_id: str, *, revision: str = "rev-1", preview: str = "PRIVATE-CHUNK") -> Candidate:
    return Candidate(
        "doc-1", 1.0, 1, output_rank=1, candidate_id=candidate_id,
        logical_chunk_id="chunk-1", document_id="doc-1", document_revision=revision,
        metadata={"preview": preview},
    )


def _linear_trace(run_id: str, *, revision: str = "rev-1", redacted: bool = False) -> RetrievalTrace:
    candidate = _candidate(f"candidate-{run_id}", revision=revision)
    return RetrievalTrace(
        trace_id=f"trace-{run_id}", service_id="search", run_id=run_id,
        query_id="q-1", query_text="PRIVATE-QUERY", pipeline_id="pipeline",
        spans=(OperatorSpan.source("retrieve", "retrieve", (candidate,)),),
        final_op_ids=("retrieve",),
        capture=CaptureMetadata(redacted_field_count=1 if redacted else 0),
    )


def _manifest(trace: RetrievalTrace) -> dict:
    return {
        "dataset": {"query_hash": "queries", "corpus_hash": "corpus", "qrel_hash": "qrels"},
        "labeling": {"method": "gold", "judge": None, "model": None, "version": None},
        "evidence_profile": {
            "release_identity": {"service_id": "search", "deployment_revision": trace.run_id, "corpus_revision": "corpus", "index_build_id": "index"},
            "run_window": {"started_at": None, "finished_at": None},
            "lineage": {"trace_coverage": 1.0, "identity_continuity_coverage": 1.0, "document_identity_coverage": 1.0, "input_output_coverage": 1.0, "recorded_exit_reason_coverage": 1.0, "topology_edge_coverage": 1.0, "qrel_to_chunk_mapping_coverage": 1.0, "legacy_inferred_count": 0, "partial_trace_count": 0},
            "topologies": [{"topology_hash": trace.topology_hash(), "operators": [{"op_id": "retrieve", "op_type": "SOURCE", "parent_ids": []}], "lineage_schema_versions": [1]}],
            "telemetry": None,
        },
    }


@pytest.mark.asyncio
async def test_document_revision_mismatch_blocks_diff_and_preserves_both_paths(tmp_path):
    store = SQLiteStore(db_path=str(tmp_path / "lineage.db")); await store.init_db()
    baseline = _linear_trace("baseline", revision="rev-a")
    candidate = _linear_trace("candidate", revision="rev-b")
    for trace in (baseline, candidate):
        await store.save_run(trace.run_id, trace.run_id, "{}")
        await store.save_trace(trace)
        await store.save_run_manifest(trace.run_id, _manifest(trace))
    registry = DbRegistry([store.db_path]); db_id = registry.list_db_ids()[0]
    client = TestClient(create_app(registry=registry, enable_uploads=False))

    payload = client.get(f"/dbs/{db_id}/runs/candidate/queries/q-1/candidate-lineage-diff?against=baseline").json()

    assert payload["readiness"]["status"] == "BLOCK"
    assert payload["diffs"][0]["status"] == "BLOCK"
    assert payload["diffs"][0]["baseline"]["candidates"]
    assert payload["diffs"][0]["candidate"]["candidates"]


@pytest.mark.asyncio
async def test_redacted_preview_never_leaves_local_lineage_api(tmp_path):
    trace = _linear_trace("run-a", redacted=True)
    store = SQLiteStore(db_path=str(tmp_path / "redacted.db")); await store.init_db()
    await store.save_run("run-a", "run-a", "{}"); await store.save_trace(trace); await store.save_run_manifest("run-a", _manifest(trace))
    registry = DbRegistry([store.db_path]); db_id = registry.list_db_ids()[0]
    payload = TestClient(create_app(registry=registry, enable_uploads=False)).get(f"/dbs/{db_id}/runs/run-a/queries/q-1/candidate-lineage").json()

    assert "PRIVATE-CHUNK" not in str(payload)
    assert payload["graph"]["nodes"][0]["source"]["preview"] is None


@pytest.mark.asyncio
async def test_ambiguous_trace_instances_block_diff_without_selecting_one(tmp_path):
    store = SQLiteStore(db_path=str(tmp_path / "ambiguous.db")); await store.init_db()
    baseline = _linear_trace("baseline")
    duplicate = replace(baseline, trace_id="trace-baseline-duplicate")
    candidate = _linear_trace("candidate")
    for run_id, traces in (("baseline", (baseline, duplicate)), ("candidate", (candidate,))):
        await store.save_run(run_id, run_id, "{}")
        await store.save_traces(traces)
        await store.save_run_manifest(run_id, _manifest(traces[0]))
    registry = DbRegistry([store.db_path]); db_id = registry.list_db_ids()[0]

    payload = TestClient(create_app(registry=registry, enable_uploads=False)).get(
        f"/dbs/{db_id}/runs/candidate/queries/q-1/candidate-lineage-diff?against=baseline"
    ).json()

    assert payload["readiness"]["status"] == "BLOCK"
    assert payload["diffs"] == []
    assert len(payload["unpaired"]["baseline"]) == 2
    assert len(payload["unpaired"]["candidate"]) == 1


def test_routed_fusion_unknown_production_and_partial_capture_boundaries():
    lexical = _candidate("lexical")
    dense = _candidate("dense")
    fused = Candidate(
        "doc-1", 1.2, 1, output_rank=1, candidate_id="fused", logical_chunk_id="chunk-1",
        document_id="doc-1", document_revision="rev-1", parent_candidate_ids=("lexical", "dense"),
        decision_reason="fused", decision_evidence="recorded",
    )
    fusion = RetrievalTrace(
        trace_id="fusion", service_id="search", run_id=None, query_id="q-1", query_text="",
        pipeline_id="hybrid", spans=(
            OperatorSpan.source("lexical", "lexical", (lexical,)),
            OperatorSpan.source("dense", "dense", (dense,)),
            OperatorSpan("fuse", "FUSE", "fuse", ("lexical", "dense"), "FIRED", 1.0, input_groups={"lexical": (lexical,), "dense": (dense,)}, outputs=(fused,)),
        ), final_op_ids=("fuse",),
    )
    graph = build_candidate_lineage(fusion, qrels_for_query={})
    assert len(graph.candidates["fused"].routes) == 2
    assert graph.candidates["fused"].outcome.kind == "unknown_relevance"

    temporal_candidate = _candidate("temporal")
    temporal_candidate.decision_reason = "outside effective date"
    temporal_candidate.decision_evidence = "recorded"
    temporal = RetrievalTrace(
        trace_id="temporal", service_id="search", run_id="run", query_id="q-1", query_text="",
        pipeline_id="pipeline", spans=(
            OperatorSpan.source("retrieve", "retrieve", (temporal_candidate,)),
            OperatorSpan("temporal-filter", "FILTER", "temporal-filter", ("retrieve",), "FIRED", 1.0, input_groups={"retrieve": (temporal_candidate,)}, outputs=()),
        ), final_op_ids=("temporal-filter",),
    )
    temporal_passport = build_candidate_lineage(
        temporal, qrels_for_query={"chunk-1": 1}, qrel_chunk_mapping_complete=True
    ).candidates["temporal"]
    assert temporal_passport.outcome.kind == "relevant_dropped_at_stage"
    assert temporal_passport.removed_at == "temporal-filter"

    partial_candidate = _candidate("partial")
    partial_input = Candidate(**{**partial_candidate.__dict__, "output_rank": None, "decision_evidence": "unavailable"})
    partial = RetrievalTrace(
        trace_id="partial", service_id="search", run_id="run", query_id="q-1", query_text="",
        pipeline_id="pipeline", spans=(
            OperatorSpan.source("retrieve", "retrieve", (partial_candidate,)),
            OperatorSpan("temporal-filter", "FILTER", "temporal-filter", ("retrieve",), "FIRED", 1.0, input_groups={"retrieve": (partial_input,)}, outputs=()),
        ), final_op_ids=("temporal-filter",), capture=CaptureMetadata(candidates_truncated=True, lineage_evidence="partial"),
    )
    passport = build_candidate_lineage(partial, qrels_for_query={"chunk-1": 1}, qrel_chunk_mapping_complete=True).candidates["partial"]
    assert passport.outcome.kind == "lineage_incomplete"
    assert passport.outcome.kind != "relevant_dropped_at_stage"
