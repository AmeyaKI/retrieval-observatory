from dataclasses import replace
from datetime import datetime, timedelta, timezone

from retrieval_observatory.release.evidence import EvidenceProfile
from retrieval_observatory.store.base import InstrumentationHealth
from retrieval_observatory.tracing.model import Candidate, CaptureMetadata, OperatorSpan, RetrievalTrace


STARTED = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
FINISHED = STARTED + timedelta(minutes=5)


def _manifest() -> dict:
    return {
        "release_identity": {
            "service_id": "support-search",
            "deployment_revision": "deploy-7",
            "corpus_revision": "corpus-3",
            "index_build_id": "index-9",
        },
        "run_window": {
            "started_at": STARTED.isoformat(),
            "finished_at": FINISHED.isoformat(),
        },
        "counts": {"attempted": 2},
        "normalized_config": {"pipelines": [{"id": "hybrid"}], "graphs": []},
    }


def _trace(trace_id: str, *, recorded_exit: bool, timestamp: datetime | None = None) -> RetrievalTrace:
    source_candidate = Candidate(
        "chunk:1",
        1.0,
        1,
        candidate_id=f"{trace_id}:source",
        logical_chunk_id="chunk:1",
    )
    dropped_candidate = Candidate(
        "chunk:1",
        1.0,
        1,
        output_rank=None,
        candidate_id=f"{trace_id}:source",
        logical_chunk_id="chunk:1",
        decision_reason="filtered" if recorded_exit else None,
        decision_evidence="recorded" if recorded_exit else "legacy_inferred",
    )
    return RetrievalTrace(
        trace_id=trace_id,
        service_id="support-search",
        run_id="run-1",
        query_id=trace_id,
        query_text="private query",
        pipeline_id="hybrid",
        spans=(
            OperatorSpan.source("source", "Source", (source_candidate,)),
            OperatorSpan(
                op_id="filter",
                op_type="FILTER",
                op_name="Filter",
                parent_ids=("source",),
                status="FIRED",
                latency_ms=1.0,
                input_groups={"source": (dropped_candidate,)},
                outputs=(),
            ),
        ),
        final_op_ids=("filter",),
        timestamp=timestamp or STARTED + timedelta(minutes=1),
    )


def test_profile_counts_recorded_exit_coverage_not_inferred_exits():
    profile = EvidenceProfile.from_run(
        _manifest(),
        [_trace("q-1", recorded_exit=True), _trace("q-2", recorded_exit=False)],
        None,
    )

    assert profile.lineage.recorded_exit_reason_coverage == 0.5
    assert profile.lineage.identity_continuity_coverage == 1.0
    assert profile.lineage.document_identity_coverage == 0.0
    assert profile.lineage.trace_coverage == 1.0
    assert profile.lineage.legacy_inferred_count == 1


def test_profile_keeps_health_outside_run_window_unknown():
    health = InstrumentationHealth(
        service_id="support-search",
        accepted=10,
        exported=10,
        observed_at=FINISHED + timedelta(seconds=1),
    )

    profile = EvidenceProfile.from_run(_manifest(), [_trace("q-1", recorded_exit=True)], health)

    assert profile.telemetry is None


def test_profile_excludes_traces_outside_run_window():
    profile = EvidenceProfile.from_run(
        _manifest(),
        [
            _trace("inside", recorded_exit=True),
            _trace("outside", recorded_exit=False, timestamp=FINISHED + timedelta(seconds=1)),
        ],
        None,
    )

    assert profile.lineage.recorded_exit_reason_coverage == 1.0
    assert profile.lineage.trace_coverage == 0.5


def test_profile_preserves_unknown_coverage_and_counts_partial_capture():
    empty = EvidenceProfile.from_run(_manifest(), [], None)
    partial_trace = replace(
        _trace("partial", recorded_exit=True),
        capture=CaptureMetadata(candidates_truncated=True),
    )
    partial = EvidenceProfile.from_run(_manifest(), [partial_trace], None)

    assert empty.lineage.identity_continuity_coverage is None
    assert empty.lineage.recorded_exit_reason_coverage is None
    assert empty.lineage.topology_edge_coverage is None
    assert partial.lineage.partial_trace_count == 1


def test_profile_emits_sorted_topology_descriptor_without_raw_content():
    profile = EvidenceProfile.from_run(_manifest(), [_trace("q-1", recorded_exit=True)], None)

    assert [operator.op_id for operator in profile.topologies[0].operators] == ["filter", "source"]
    assert profile.topologies[0].lineage_schema_versions == [2]
    assert "private query" not in profile.model_dump_json()
