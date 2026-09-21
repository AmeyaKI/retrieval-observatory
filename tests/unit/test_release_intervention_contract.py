"""Release comparability must permit a declared, legitimate model change.

Recorded in T01 as the regression input for T15. Two runs share identical
query/corpus/qrel identity, labeling, attempt counts, and metric values; they
differ only in ``release_identity.reranker_model_revision`` — the intended
experimental intervention. Blanket revision equality once turned this into a
``release_identity_mismatch`` BLOCK. T15 replaced it with the evaluation-invariant /
declared-intervention split: the change is recorded provenance that never blocks
on its own, HOLDs for review until the policy declares it, and can PASS once declared.
"""

from __future__ import annotations

import asyncio

import retrieval_observatory
from retrieval_observatory.release.policy import ReleasePolicy
from retrieval_observatory.store.sqlite import SQLiteStore


def _manifest(*, deployment: str, reranker_model_revision: str) -> dict:
    identity = {
        "service_id": "search",
        "deployment_revision": deployment,
        "corpus_revision": "corpus-v1",
        "index_build_id": "index-v1",
        "chunking_revision": "chunk-v1",
        "embedding_model_revision": "embed-v1",
        "reranker_model_revision": reranker_model_revision,
    }
    return {
        "dataset": {"query_hash": "queries", "corpus_hash": "corpus", "qrel_hash": "qrels"},
        "labeling": {"method": "gold", "judge": None, "model": None, "version": None},
        "counts": {"attempted": 6, "completed": 6, "labeled": 6, "metric_eligible": 6},
        "evaluation": {"unit": "document", "boundary": "final_retrieval", "k": 10, "relevance_threshold": 1},
        "release_identity": identity,
        "evidence_profile": {
            "release_identity": identity,
            "run_window": {"started_at": "2026-09-21T12:00:00Z", "finished_at": "2026-09-21T12:05:00Z"},
            "lineage": {
                "trace_coverage": 1.0, "identity_continuity_coverage": 1.0,
                "document_identity_coverage": 1.0, "input_output_coverage": 1.0,
                "recorded_exit_reason_coverage": 1.0, "topology_edge_coverage": 1.0,
                "qrel_to_chunk_mapping_coverage": 1.0, "legacy_inferred_count": 0,
                "partial_trace_count": 0,
            },
            "topologies": [{
                "topology_hash": "topology-v1",
                "operators": [{"op_id": "retrieve", "op_type": "SOURCE", "parent_ids": []}],
                "lineage_schema_versions": [1],
            }],
            "telemetry": None,
        },
    }


def _policy(*, expected_changes: list[str] | None = None) -> ReleasePolicy:
    return ReleasePolicy.model_validate({
        "id": "reranker-change", "schema_version": 2,
        "evidence": {
            "promotion": {"required_manifest_fields": ["release_identity.corpus_revision"], "min_label_coverage": 1.0},
        },
        "intervention": {"expected_changes": expected_changes or []},
        "statistics": {"confidence_level": 0.95, "familywise_alpha": 0.05, "resamples": 100, "seed": 17},
        "metrics": [{
            "metric": "pipeline|stage0|recall@10", "direction": "higher_is_better",
            "max_regression": 0.05, "min_paired_n": 2,
        }],
    })


async def _seed(db_path: str) -> None:
    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    for run_id, deployment, reranker in (
        ("baseline", "deploy-a", "reranker-v1"),
        ("candidate", "deploy-b", "reranker-v2"),
    ):
        await store.save_run(run_id, run_id, "{}")
        await store.save_run_manifest(run_id, _manifest(deployment=deployment, reranker_model_revision=reranker))
        await store.save_metrics_batch([{
            "run_id": run_id, "pipeline_id": "pipeline", "query_id": f"q-{index}",
            "stage_index": 0, "metric_name": "recall", "k": 10, "value": 1.0,
            "branch_id": None, "query_metadata_json": {"query_text": "REDACTED"},
        } for index in range(6)])


def _compare(tmp_path, policy: ReleasePolicy):
    db_path = str(tmp_path / "reranker.db")
    asyncio.run(_seed(db_path))
    return retrieval_observatory.compare("baseline", "candidate", db_path=db_path, policy=policy)


def test_reranker_revision_change_alone_does_not_block_comparison(tmp_path):
    report = _compare(tmp_path, _policy())

    decision = report.comparison["release_decision"]
    aggregate = decision["readiness"]["aggregate_or_slice_evaluation"]
    codes = [item["code"] for item in aggregate["findings"]]
    assert "release_identity_mismatch" not in codes, codes
    assert decision["status"] != "BLOCK", decision["reasons"]
    # The changed field must still be surfaced as recorded provenance, not hidden.
    provenance = report.comparison["release_provenance"]
    assert provenance["baseline"]["release_identity"]["reranker_model_revision"] == "reranker-v1"
    assert provenance["candidate"]["release_identity"]["reranker_model_revision"] == "reranker-v2"


def test_declared_reranker_change_can_pass_with_identical_metrics(tmp_path):
    report = _compare(tmp_path, _policy(expected_changes=["reranker_model_revision"]))

    decision = report.comparison["release_decision"]
    codes = [item["code"] for scope in decision["readiness"].values() for item in scope["findings"]]
    assert "undeclared_intervention" not in codes, codes
    assert decision["status"] == "PASS", decision["reasons"]
    reranker = next(
        item for item in decision["provenance_assessment"]["interventions"]
        if item["field"] == "release_identity.reranker_model_revision"
    )
    assert (reranker["baseline"], reranker["candidate"], reranker["equal"]) == ("reranker-v1", "reranker-v2", False)
    assert reranker["classification"] == "expected"


def test_undeclared_reranker_change_holds_for_review(tmp_path):
    report = _compare(tmp_path, _policy())

    decision = report.comparison["release_decision"]
    assert decision["status"] == "HOLD", decision["reasons"]
    promotion = decision["readiness"]["promotion"]
    finding = next(item for item in promotion["findings"] if item["code"] == "undeclared_intervention")
    assert finding["status"] == "HOLD"
    assert finding["observed"] == {"reranker_model_revision": ["reranker-v1", "reranker-v2"]}
    assert "intervention.expected_changes" in finding["next_action"]
    reranker = next(
        item for item in decision["provenance_assessment"]["interventions"]
        if item["field"] == "release_identity.reranker_model_revision"
    )
    assert reranker["classification"] == "unexpected"
    assert reranker["finding_code"] == "undeclared_intervention"
