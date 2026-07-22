from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from retrieval_observatory.cli import app
from retrieval_observatory.integrations.manifest import write_manifest
from retrieval_observatory.integrations.model import IntegrationManifest, OperatorMapping
from retrieval_observatory.integrations.verify import verify_project
from retrieval_observatory.release.policy import ReleasePolicy
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace


def _policy(*, require_recorded_exits: bool = False) -> ReleasePolicy:
    return ReleasePolicy.model_validate(
        {
            "id": "integration-preflight",
            "schema_version": 2,
            "evidence": {
                "lineage_diagnosis": {
                    "require_stable_candidate_identity": True,
                    "min_input_output_coverage": 1.0,
                    "require_recorded_exit_reasons": require_recorded_exits,
                }
            },
            "statistics": {
                "confidence_level": 0.95,
                "familywise_alpha": 0.05,
                "resamples": 100,
                "seed": 7,
            },
            "metrics": [
                {
                    "metric": "pipeline|stage1|ndcg@10",
                    "direction": "higher_is_better",
                    "max_regression": 0.0,
                    "min_paired_n": 2,
                }
            ],
        }
    )


def _manifest() -> IntegrationManifest:
    return IntegrationManifest(
        1,
        "plan",
        "service",
        "pipeline",
        (
            OperatorMapping("source", "SOURCE", "source", "app.py"),
            OperatorMapping("filter", "FILTER", "filter", "app.py", ("source",)),
        ),
        {"doc_id": "id"},
        (),
    )


def _trace_without_recorded_exit() -> RetrievalTrace:
    candidate = Candidate(
        "doc-1",
        1.0,
        1,
        candidate_id="candidate-1",
        logical_chunk_id="chunk-1",
        origin_op_ids=("source",),
    )
    return RetrievalTrace(
        trace_id="trace-1",
        service_id="service",
        run_id="run-1",
        query_id="query-1",
        query_text="private query",
        pipeline_id="pipeline",
        spans=(
            OperatorSpan.source("source", "source", (candidate,)),
            OperatorSpan(
                "filter",
                "FILTER",
                "filter",
                ("source",),
                "FIRED",
                1.0,
                input_groups={"source": (candidate,)},
                outputs=(),
            ),
        ),
        final_op_ids=("filter",),
    )


@pytest.mark.asyncio
async def test_verify_blocks_only_lineage_diagnosis_when_exits_are_missing(tmp_path) -> None:
    write_manifest(tmp_path, _manifest())
    store = SQLiteStore(db_path=str(tmp_path / "results.db"))
    await store.init_db()
    await store.save_trace(_trace_without_recorded_exit())

    result = await verify_project(tmp_path, store, policy=_policy(require_recorded_exits=True))

    assert result.release_readiness["lineage_diagnosis"]["status"] == "BLOCK"
    assert result.release_readiness["promotion"]["status"] == "HOLD"
    assert {
        finding["code"]
        for finding in result.release_readiness["lineage_diagnosis"]["findings"]
    } == {"lineage_exit_reason_unrecorded"}
    assert result.release_readiness["promotion"]["findings"][0]["code"] == "paired_metrics_unavailable"


@pytest.mark.asyncio
async def test_verify_reports_capture_ready_without_promoting(tmp_path) -> None:
    write_manifest(tmp_path, _manifest())
    store = SQLiteStore(db_path=str(tmp_path / "results.db"))
    await store.init_db()
    await store.save_trace(_trace_without_recorded_exit())

    result = await verify_project(tmp_path, store, policy=_policy())

    assert result.release_readiness["lineage_diagnosis"]["status"] == "READY"
    assert result.release_readiness["promotion"]["status"] == "HOLD"


def test_integrate_verify_accepts_only_an_explicit_local_policy_path(tmp_path) -> None:
    write_manifest(tmp_path, _manifest())
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(_policy().model_dump_json(), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "integrate",
            str(tmp_path),
            "--phase",
            "verify",
            "--db",
            str(tmp_path / "results.db"),
            "--policy",
            str(policy_path),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["release_readiness"]["promotion"]["status"] == "HOLD"
    assert payload["release_readiness"]["lineage_diagnosis"]["status"] == "BLOCK"
