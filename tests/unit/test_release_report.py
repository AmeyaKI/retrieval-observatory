from __future__ import annotations

from retrieval_observatory.release.policy import ReleasePolicy
from retrieval_observatory.sdk.report import load_comparison_report
from retrieval_observatory.store.sqlite import SQLiteStore


def _policy() -> ReleasePolicy:
    return ReleasePolicy.model_validate(
        {
            "id": "report-policy-v2",
            "schema_version": 2,
            "statistics": {
                "confidence_level": 0.95,
                "familywise_alpha": 0.05,
                "resamples": 100,
                "seed": 7,
            },
            "metrics": [
                {
                    "metric": "pipeline|stage0|recall@10",
                    "direction": "higher_is_better",
                    "max_regression": 0.05,
                    "min_paired_n": 2,
                }
            ],
        }
    )


def _manifest(deployment: str) -> dict:
    return {
        "dataset": {"query_hash": "queries", "corpus_hash": "corpus", "qrel_hash": "qrels"},
        "labeling": {"method": "gold", "judge": None, "model": None, "version": None},
        "counts": {"attempted": 2, "completed": 2, "labeled": 2, "metric_eligible": 2},
        "release_identity": {
            "service_id": "support-search",
            "deployment_revision": deployment,
            "corpus_revision": "corpus-v1",
            "index_build_id": "index-v1",
        },
        "evidence_profile": {
            "release_identity": {
                "service_id": "support-search",
                "deployment_revision": deployment,
                "corpus_revision": "corpus-v1",
                "index_build_id": "index-v1",
            },
            "run_window": {
                "started_at": "2026-07-22T12:00:00Z",
                "finished_at": "2026-07-22T12:05:00Z",
            },
            "lineage": {
                "trace_coverage": 1.0,
                "identity_continuity_coverage": 1.0,
                "document_identity_coverage": 1.0,
                "input_output_coverage": 1.0,
                "recorded_exit_reason_coverage": 1.0,
                "topology_edge_coverage": 1.0,
                "qrel_to_chunk_mapping_coverage": 1.0,
                "legacy_inferred_count": 0,
                "partial_trace_count": 0,
            },
            "topologies": [
                {
                    "topology_hash": "topology-a",
                    "operators": [{"op_id": "source", "op_type": "SOURCE", "parent_ids": []}],
                    "lineage_schema_versions": [1],
                }
            ],
            "telemetry": None,
        },
    }


async def _prepare(db_path: str) -> None:
    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    for run_id, deployment, value in (("base", "deploy-1", 1.0), ("candidate", "deploy-2", 0.0)):
        await store.save_run(run_id, run_id, "{}")
        await store.save_run_manifest(run_id, _manifest(deployment))
        await store.save_metrics_batch(
            [
                {
                    "run_id": run_id,
                    "pipeline_id": "pipeline",
                    "query_id": query_id,
                    "stage_index": 0,
                    "metric_name": "recall",
                    "k": 10,
                    "value": value,
                    "branch_id": None,
                    "query_metadata_json": {"query_text": "private query", "tier": "enterprise"},
                }
                for query_id in ("q-1", "q-2")
            ]
        )


async def test_report_contains_overall_decision_and_lineage_readiness(tmp_path):
    db_path = str(tmp_path / "report.db")
    await _prepare(db_path)

    report = await load_comparison_report("base", "candidate", db_path, policy=_policy())
    payload = report.to_dict()["comparison"]["release_decision"]

    assert payload["schema_version"] == 1
    assert payload["status"] == "FAIL"
    assert payload["readiness"]["lineage_diagnosis"]["status"] == "READY"
    assert report.verdict == "FAIL"
    assert "private query" not in report.to_json()
    markdown = report.to_markdown()
    paired_index = markdown.index("## Paired results")
    assert markdown.index("## Release decision") < paired_index
    assert markdown.index("### Investigation references") < paired_index
    assert markdown.index("## Provenance") < paired_index
    assert markdown.index("## Next action") < paired_index
    assert markdown.index("## Reproduce and inspect") < paired_index
    assert "Artifact schema: `1`" in markdown
    assert "#/runs/candidate/queries/q-1/diff?against=base" in report.to_json()
    assert "<!doctype html>" in report.to_html()


async def test_no_policy_report_holds_without_removing_existing_comparison_fields(tmp_path):
    db_path = str(tmp_path / "report.db")
    await _prepare(db_path)

    payload = (await load_comparison_report("base", "candidate", db_path)).to_dict()["comparison"]

    assert payload["release_decision"]["status"] == "HOLD"
    assert payload["release_decision"]["policy"]["configured"] is False
    assert "validity" in payload
    assert "results" in payload
