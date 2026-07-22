from __future__ import annotations

import pytest

from retrieval_observatory.release.policy import ReleasePolicy
from retrieval_observatory.sdk.report import load_comparison_report
from retrieval_observatory.store.sqlite import SQLiteStore


def _manifest(*, deployment: str, corpus_revision: str | None = "corpus-v1", exit_coverage: float = 1.0) -> dict:
    return {
        "dataset": {"query_hash": "queries", "corpus_hash": "corpus", "qrel_hash": "qrels"},
        "labeling": {"method": "gold", "judge": None, "model": None, "version": None},
        "counts": {"attempted": 6, "completed": 6, "labeled": 6, "metric_eligible": 6},
        "release_identity": {
            "service_id": "search", "deployment_revision": deployment,
            "corpus_revision": corpus_revision, "index_build_id": "index-v1",
        },
        "evidence_profile": {
            "release_identity": {
                "service_id": "search", "deployment_revision": deployment,
                "corpus_revision": corpus_revision, "index_build_id": "index-v1",
            },
            "run_window": {"started_at": "2026-07-22T12:00:00Z", "finished_at": "2026-07-22T12:05:00Z"},
            "lineage": {
                "trace_coverage": 1.0, "identity_continuity_coverage": 1.0,
                "input_output_coverage": 1.0, "recorded_exit_reason_coverage": exit_coverage,
                "topology_edge_coverage": 1.0, "qrel_to_chunk_mapping_coverage": 1.0,
                "legacy_inferred_count": 0, "partial_trace_count": 0,
            },
            "topologies": [{
                "topology_hash": "topology-v1",
                "operators": [{"op_id": "retrieve", "op_type": "SOURCE", "parent_ids": []}],
                "lineage_schema_versions": [1],
            }],
            "telemetry": None,
        },
    }


def _policy(*, min_paired_n: int = 2, max_regression: float = 0.05, with_slice: bool = False) -> ReleasePolicy:
    return ReleasePolicy.model_validate({
        "id": "workflow-v2", "schema_version": 2,
        "evidence": {
            "promotion": {"required_manifest_fields": ["release_identity.corpus_revision"], "min_label_coverage": 1.0},
            "lineage_diagnosis": {"require_recorded_exit_reasons": True},
        },
        "statistics": {"confidence_level": 0.95, "familywise_alpha": 0.05, "resamples": 100, "seed": 17},
        "metrics": [{
            "metric": "pipeline|stage0|recall@10", "direction": "higher_is_better",
            "max_regression": max_regression, "min_paired_n": min_paired_n,
        }],
        "slices": [{"id": "temporal", "field": "scenario", "value": "temporal"}] if with_slice else [],
    })


async def _run_fixture_and_compare(tmp_path, fixture_name: str):
    db_path = str(tmp_path / f"{fixture_name}.db")
    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    temporal = fixture_name in {"held_underpowered_slice", "failed_temporal_filter_slice"}
    values = {
        "pass_with_lineage_blocked": ([1.0] * 6, [1.0] * 6),
        "held_underpowered_slice": ([1.0] * 6, [1.0] * 6),
        "blocked_corpus_identity": ([1.0] * 6, [1.0] * 6),
        "failed_temporal_filter_slice": ([1.0] * 6, [0.0, 0.0, 1.0, 1.0, 1.0, 1.0]),
    }[fixture_name]
    for run_id, deployment, run_values in (
        ("baseline", "deploy-a", values[0]), ("candidate", "deploy-b", values[1])
    ):
        await store.save_run(run_id, run_id, "{}")
        await store.save_run_manifest(
            run_id,
            _manifest(
                deployment=deployment,
                corpus_revision=None if fixture_name == "blocked_corpus_identity" and run_id == "candidate" else "corpus-v1",
                exit_coverage=0.5 if fixture_name == "pass_with_lineage_blocked" else 1.0,
            ),
        )
        await store.save_metrics_batch([{
            "run_id": run_id, "pipeline_id": "pipeline", "query_id": f"q-{index}",
            "stage_index": 0, "metric_name": "recall", "k": 10, "value": value,
            "branch_id": None,
            "query_metadata_json": {"scenario": "temporal" if index < 2 else "standard", "query_text": "REDACTED-RAW-QUERY"},
        } for index, value in enumerate(run_values)])
    policy = _policy(
        min_paired_n=3 if fixture_name == "held_underpowered_slice" else 2,
        max_regression=0.4 if fixture_name == "failed_temporal_filter_slice" else 0.05,
        with_slice=temporal,
    )
    return await load_comparison_report("baseline", "candidate", db_path, policy=policy)


@pytest.mark.asyncio
@pytest.mark.parametrize(("fixture_name", "expected"), [
    ("pass_with_lineage_blocked", "PASS"),
    ("held_underpowered_slice", "HOLD"),
    ("blocked_corpus_identity", "BLOCK"),
    ("failed_temporal_filter_slice", "FAIL"),
])
async def test_release_workflow_emits_expected_status(tmp_path, fixture_name, expected):
    report = await _run_fixture_and_compare(tmp_path, fixture_name)
    decision = report.comparison["release_decision"]
    assert decision["status"] == expected
    if fixture_name == "pass_with_lineage_blocked":
        assert decision["readiness"]["lineage_diagnosis"]["status"] == "BLOCK"


@pytest.mark.asyncio
async def test_no_policy_cannot_pass_and_artifacts_remain_local_and_redacted(tmp_path):
    report = await _run_fixture_and_compare(tmp_path, "pass_with_lineage_blocked")
    no_policy = await load_comparison_report("baseline", "candidate", report.reproduce.split(" --db ", 1)[1].split(" --policy", 1)[0])

    assert no_policy.verdict == "HOLD"
    assert "REDACTED-RAW-QUERY" not in report.to_json()
    html = report.to_html()
    assert "<script src=" not in html
    assert "<link rel=" not in html
