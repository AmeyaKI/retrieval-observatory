"""Release policy schema 3: semantic selectors, strict validation, explicit v2 conversion, and
the selector resolution that binds a policy to the metric keys two runs record."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import retrieval_observatory
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.release.policy import ReleasePolicy, ReleasePolicyV3, load_release_policy
from retrieval_observatory.release.resolution import (
    METRIC_SELECTOR_UNRESOLVED,
    POLICY_SELECTOR_AMBIGUOUS,
    RunEvidence,
    convert_v2_policy,
    family_size,
    operator_depths_from_traces,
    operator_ids_from_traces,
    resolve_policy,
)
from retrieval_observatory.store.sqlite import SQLiteStore
from tests.fixtures.investigation_cases import run_fixture


FIXTURES = Path(__file__).parents[1] / "fixtures"
V3_FIXTURE = FIXTURES / "release_policy_v3.yaml"
V2_FIXTURE = FIXTURES / "release_policy.yaml"


# --------------------------------------------------------------------------- builders


def _check(**changes):
    check = {
        "id": "final-recall",
        "metric": "recall",
        "target": "final_retrieval",
        "direction": "higher_is_better",
        "max_regression": 0.01,
        "min_paired_n": 2,
    }
    check.update(changes)
    return check


def _statistics(**changes):
    statistics = {"confidence_level": 0.95, "familywise_alpha": 0.05, "resamples": 4000, "seed": 17}
    statistics.update(changes)
    return statistics


def _payload(**changes):
    payload = {
        "schema_version": 3,
        "id": "support-search-release",
        "evaluation": {"unit": "document", "k": 10},
        "statistics": _statistics(),
        "metrics": [_check()],
    }
    payload.update(changes)
    return payload


def _v3(**changes) -> ReleasePolicyV3:
    return ReleasePolicyV3.model_validate(_payload(**changes))


def _rows(run_id: str, pipeline: str, stages: list[int], *, metric: str = "recall", k: int = 10, queries: int = 6, latency: bool = True, branch_stage: int | None = None):
    rows = []
    for stage in stages:
        for index in range(queries):
            rows.append({
                "run_id": run_id, "pipeline_id": pipeline, "query_id": f"q-{index}", "stage_index": stage,
                "metric_name": metric, "k": k, "value": 1.0, "branch_id": None, "query_metadata": {},
            })
    if branch_stage is not None:
        for branch in ("a", "b"):
            rows.append({
                "run_id": run_id, "pipeline_id": pipeline, "query_id": "q-0", "stage_index": branch_stage,
                "metric_name": metric, "k": k, "value": 1.0, "branch_id": branch, "query_metadata": {},
            })
    if latency:
        for index in range(queries):
            rows.append({
                "run_id": run_id, "pipeline_id": pipeline, "query_id": f"q-{index}", "stage_index": -1,
                "metric_name": "latency_ms", "k": 0, "value": 10.0, "branch_id": None, "query_metadata": {},
            })
    return rows


def _evidence(run_id: str, stages: list[int], *, pipeline: str = "pipeline", depths=None, operator_ids=None, manifest=None, **row_changes) -> RunEvidence:
    return RunEvidence(
        run_id=run_id,
        manifest=manifest if manifest is not None else {"normalized_config": {"pipelines": [{"id": pipeline}]}},
        metric_rows=_rows(run_id, pipeline, stages, **row_changes),
        operator_depths=depths,
        operator_ids=operator_ids,
    )


@pytest.fixture(scope="module")
def golden():
    traces = run_fixture().traces
    return operator_depths_from_traces(traces), operator_ids_from_traces(traces)


# --------------------------------------------------------------------------- schema


def test_sample_policy_parses_with_digest():
    policy = load_release_policy(V3_FIXTURE)

    assert isinstance(policy, ReleasePolicyV3)
    assert policy.schema_version == 3
    assert policy.digest.startswith("sha256:")
    assert [check.id for check in policy.metrics] == ["final-recall", "query-latency"]
    assert policy.metrics[1].estimator == "p95"
    assert policy.slices[0].metric_ids == ["final-recall"]
    assert policy.statistics.min_pair_coverage == 1.0
    assert policy.execution.max_failure_rate == 0.0
    assert ReleasePolicyV3.model_validate(policy.model_dump()).digest == policy.digest


def test_load_release_policy_dispatches_on_schema_version(tmp_path):
    assert isinstance(load_release_policy(V2_FIXTURE), ReleasePolicy)
    assert isinstance(load_release_policy(V3_FIXTURE), ReleasePolicyV3)

    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(_payload(schema_version=4)), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported policy schema_version"):
        load_release_policy(path)


def test_v3_digest_never_equals_v2_digest():
    v2 = load_release_policy(V2_FIXTURE)
    v3 = load_release_policy(V3_FIXTURE)

    assert v2.digest != v3.digest


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"metrics": [_check(metric="hit_rate")]}, "unknown metric name"),
        ({"metrics": [_check(), _check(direction="lower_is_better")]}, "metric check ids must be unique"),
        ({"slices": [{"id": "s", "field": "tier", "value": "pro"}, {"id": "s", "field": "tier", "value": "pro"}]}, "slice ids must be unique"),
        ({"slices": [{"id": "s", "field": "tier", "value": "pro", "metric_ids": ["missing"]}]}, "unknown metric ids"),
        ({"metrics": [_check(estimator="p95")]}, "estimator applies only to latency_ms"),
        ({"metrics": [_check(id="lat", metric="latency_ms", target="query", direction="lower_is_better", k=10)]}, "k applies only to"),
        ({"metrics": [_check(id="fail", metric="failure_rate", target="query", direction="lower_is_better", k=10)]}, "k applies only to"),
        ({"metrics": [_check(target="query")]}, "target query cannot carry the ranking metric"),
        ({"metrics": [_check(id="lat", metric="latency_ms", direction="lower_is_better")]}, "query-level metric"),
        ({"metrics": [_check(max_regression=-0.01)]}, "greater than or equal to 0"),
        ({"statistics": _statistics(confidence_level=0.97, familywise_alpha=0.05)}, "contradictory"),
        ({"statistics": _statistics(repeated_trials="mean_of_attempts")}, "repeated-trial aggregation is not supported"),
        ({"evaluation": {"unit": "document", "k": 10, "boundary": "stage3"}}, "operator:<operator_id>"),
        ({"evidence": {"require_corpus_identity": False}}, "cannot be disabled"),
        ({"unexpected": True}, "Extra inputs are not permitted"),
        ({"metrics": [_check(surprise=1)]}, "Extra inputs are not permitted"),
    ],
)
def test_v3_rejects_inconsistent_selectors_and_unknown_keys(change, message):
    with pytest.raises(ValidationError, match=message):
        _v3(**change)


def test_bootstrap_resolution_floor_reports_minimum_resamples():
    checks = [_check(), _check(id="ndcg", metric="ndcg"), _check(id="mrr", metric="mrr")]

    with pytest.raises(ValidationError, match="at least 2400 resamples are required") as info:
        _v3(metrics=checks, statistics=_statistics(resamples=100))
    assert "resamples 100" in str(info.value)
    assert _v3(metrics=checks, statistics=_statistics(resamples=2400)).digest.startswith("sha256:")


def test_family_size_counts_slice_metric_ids():
    checks = [_check(), _check(id="lat", metric="latency_ms", target="query", direction="lower_is_better")]

    assert family_size(_v3(metrics=checks)) == 2
    assert family_size(_v3(metrics=checks, slices=[{"id": "s", "field": "f", "value": 1, "metric_ids": ["final-recall"]}])) == 3
    assert family_size(_v3(metrics=checks, slices=[{"id": "s", "field": "f", "value": 1}])) == 4


# --------------------------------------------------------------------------- resolution


def test_final_retrieval_resolves_to_the_last_stage_in_both_runs(golden):
    policy = load_release_policy(V3_FIXTURE)
    resolved = resolve_policy(policy, _evidence("baseline", [0, 1, 2]), _evidence("candidate", [0, 1, 2]))

    recall, latency = resolved.checks
    assert recall.status == "resolved"
    assert recall.metric_key_by_run == {"baseline": "pipeline|stage2|recall@10", "candidate": "pipeline|stage2|recall@10"}
    assert recall.k == 10 and recall.pipeline_id == "pipeline"
    assert latency.status == "resolved"
    assert latency.metric_key_by_run == {"baseline": "pipeline|stage-1|latency_ms@0", "candidate": "pipeline|stage-1|latency_ms@0"}
    assert latency.k is None and latency.estimator == "p95"
    assert resolved.slices[0].metric_ids == ("final-recall",)
    assert resolved.findings == ()
    assert resolved.to_dict()["policy_digest"] == policy.digest
    assert resolved.to_dict()["schema_version"] == 3


def test_operator_selector_with_two_invocations_is_ambiguous(golden):
    depths, operator_ids = golden
    policy = _v3(metrics=[_check(target="operator:rerank")])
    runs = [_evidence(run, [0, 1, 2, 3], depths=depths, operator_ids=operator_ids) for run in ("baseline", "candidate")]

    check = resolve_policy(policy, *runs).checks[0]

    assert check.status == "ambiguous"
    assert "operator 'rerank' has 2 invocations at stages 1 (branch rerank@dense), 2" in check.detail
    assert "pin one or use final_retrieval" in check.detail


def test_operator_selector_resolves_to_the_engines_stage(golden):
    depths, operator_ids = golden
    assert depths["fuse"] == (3, None)
    policy = _v3(metrics=[_check(target="operator:fuse")])
    runs = [_evidence(run, [0, 1, 2, 3], depths=depths, operator_ids=operator_ids) for run in ("baseline", "candidate")]

    check = resolve_policy(policy, *runs).checks[0]

    assert check.status == "resolved"
    assert set(check.metric_key_by_run.values()) == {"pipeline|stage3|recall@10"}


def test_operator_selector_without_traces_is_unsupported():
    policy = _v3(metrics=[_check(target="operator:fuse")])

    check = resolve_policy(policy, _evidence("baseline", [0, 1]), _evidence("candidate", [0, 1])).checks[0]

    assert check.status == "unsupported"
    assert "traces not loaded" in check.detail


def test_absent_metric_blocks_with_a_selector_finding():
    policy = _v3(metrics=[_check(id="ndcg", metric="ndcg")])

    resolved = resolve_policy(policy, _evidence("baseline", [0, 1]), _evidence("candidate", [0, 1]))

    assert resolved.checks[0].status == "absent"
    assert resolved.checks[0].metric_key_by_run == {"baseline": None, "candidate": None}
    finding = resolved.findings[0]
    assert (finding["code"], finding["status"], finding["scope"], finding["check_id"]) == (
        METRIC_SELECTOR_UNRESOLVED, "BLOCK", "aggregate_or_slice_evaluation", "ndcg",
    )


def test_differing_final_stages_record_both_keys_and_carry_no_finding():
    policy = _v3()

    resolved = resolve_policy(policy, _evidence("baseline", [0, 1]), _evidence("candidate", [0, 1, 2]))

    check = resolved.checks[0]
    assert check.status == "resolved"
    assert check.metric_key_by_run == {"baseline": "pipeline|stage1|recall@10", "candidate": "pipeline|stage2|recall@10"}
    assert "runs resolve to different metric keys" in check.detail
    assert resolved.findings == ()


def test_pipeline_ambiguity_requires_an_explicit_pipeline():
    policy = _v3()
    manifest = {"normalized_config": {"pipelines": [{"id": "dense"}], "graphs": [{"id": "hybrid"}]}}
    runs = [_evidence(run, [0, 1], pipeline="dense", manifest=manifest) for run in ("baseline", "candidate")]

    check = resolve_policy(policy, *runs).checks[0]
    assert check.status == "ambiguous"
    assert "several pipelines (dense, hybrid)" in check.detail

    pinned = resolve_policy(_v3(metrics=[_check(pipeline="dense")]), *runs).checks[0]
    assert pinned.status == "resolved"
    assert pinned.pipeline_id == "dense"

    unknown = resolve_policy(_v3(metrics=[_check(pipeline="sparse")]), *runs).checks[0]
    assert unknown.status == "absent"
    assert "'sparse' is not recorded" in unknown.detail


def test_pipeline_ids_fall_back_to_metric_rows():
    runs = [_evidence(run, [0, 1], manifest={}) for run in ("baseline", "candidate")]

    check = resolve_policy(_v3(), *runs).checks[0]

    assert check.status == "resolved" and check.pipeline_id == "pipeline"


def test_evaluation_boundary_operator_selector_applies_to_final_checks(golden):
    depths, operator_ids = golden
    policy = _v3(evaluation={"unit": "document", "k": 10, "boundary": "operator:fuse"})
    runs = [_evidence(run, [0, 1, 2, 3, 4], depths=depths, operator_ids=operator_ids) for run in ("baseline", "candidate")]

    check = resolve_policy(policy, *runs).checks[0]

    assert check.target == "final_retrieval"
    assert check.status == "resolved"
    assert set(check.metric_key_by_run.values()) == {"pipeline|stage3|recall@10"}
    assert "evaluation.boundary operator:fuse applied" in check.detail


def test_v2_policy_resolves_positionally():
    policy = load_release_policy(V2_FIXTURE)
    runs = [_evidence(run, [0, 1], pipeline="hybrid__rerank", metric="ndcg") for run in ("baseline", "candidate")]

    resolved = resolve_policy(policy, *runs)

    assert resolved.schema_version == 2
    check = resolved.checks[0]
    assert check.id == check.target == "hybrid__rerank|stage1|ndcg@10"
    assert check.status == "resolved"
    assert resolved.to_dict()["evaluation"] == {}


# --------------------------------------------------------------------------- v2 conversion


def _linear_depths():
    return {"retrieve": (0, None), "rerank": (1, None), "select": (2, None)}


def test_v2_guard_converts_to_an_operator_selector_when_the_stage_is_unique():
    policy = load_release_policy(V2_FIXTURE)
    runs = [
        _evidence(run, [0, 1, 2], pipeline="hybrid__rerank", metric="ndcg", depths=_linear_depths())
        for run in ("baseline", "candidate")
    ]

    result = convert_v2_policy(policy, *runs)

    assert result.unresolved == () and result.findings == ()
    check = result.policy.metrics[0]
    assert (check.metric, check.target, check.k, check.pipeline) == ("ndcg", "operator:rerank", 10, "hybrid__rerank")
    assert check.id == "hybrid__rerank-stage1-ndcg-10"
    assert result.policy.statistics.min_pair_coverage == 0.95
    assert result.policy.evidence.require_lineage_for_decision is False
    assert result.policy.digest != policy.digest


def test_v2_guard_converts_to_final_retrieval_when_the_stage_is_final_in_both_runs():
    policy = load_release_policy(V2_FIXTURE)
    runs = [
        _evidence(run, [0, 1], pipeline="hybrid__rerank", metric="ndcg", depths={"retrieve": (0, None), "rerank": (1, None)})
        for run in ("baseline", "candidate")
    ]

    result = convert_v2_policy(policy, *runs)

    assert result.policy.metrics[0].target == "final_retrieval"
    assert result.to_dict()["policy"]["schema_version"] == 3


def test_v2_guard_with_branching_stage_is_unresolved():
    policy = load_release_policy(V2_FIXTURE)
    depths = {"retrieve": (0, None), "a": (1, "a"), "b": (1, "b"), "select": (2, None)}
    runs = [
        _evidence(run, [0, 2], pipeline="hybrid__rerank", metric="ndcg", depths=depths, branch_stage=1)
        for run in ("baseline", "candidate")
    ]

    result = convert_v2_policy(policy, *runs)

    assert result.policy is None
    assert result.unresolved[0]["metric"] == "hybrid__rerank|stage1|ndcg@10"
    assert "no operator" in result.unresolved[0]["reason"]
    finding = result.findings[0]
    assert (finding["code"], finding["status"], finding["check_id"]) == (
        POLICY_SELECTOR_AMBIGUOUS, "BLOCK", "hybrid__rerank|stage1|ndcg@10",
    )


def test_v2_run_level_latency_converts_to_a_query_check():
    policy = ReleasePolicy.model_validate({
        "id": "latency", "schema_version": 2,
        "statistics": {"confidence_level": 0.95, "familywise_alpha": 0.05, "resamples": 4000, "seed": 1},
        "metrics": [{
            "metric": "pipeline|stage-1|latency_p95@0", "direction": "lower_is_better",
            "max_regression": 50.0, "min_paired_n": 2,
        }],
    })

    check = convert_v2_policy(policy, _evidence("baseline", [0]), _evidence("candidate", [0])).policy.metrics[0]

    assert (check.metric, check.target, check.estimator, check.k) == ("latency_ms", "query", "p95", None)


# --------------------------------------------------------------------------- engine agreement


def test_operator_depths_agree_with_the_metric_engine(tmp_path):
    fixture = run_fixture()
    depths = operator_depths_from_traces(fixture.traces)
    qrels = {
        trace.query_id: {candidate.doc_id for span in trace.spans for candidate in span.outputs}
        for trace in fixture.traces
    }

    async def _rows():
        store = SQLiteStore(db_path=str(tmp_path / "engine.db"))
        await store.init_db()
        await MetricsEngine().compute_from_traces("golden-run", store, fixture.traces, qrels)
        return await store.get_metrics("golden-run")

    rows = asyncio.run(_rows())
    engine_slots = {
        (row["stage_index"], row["branch_id"]) for row in rows if row["stage_index"] >= 0 and row["metric_name"] == "recall"
    }
    fired = {span.op_id for trace in fixture.traces for span in trace.spans if span.status == "FIRED"}

    assert engine_slots == {depths[op_id] for op_id in fired}
    assert depths["rerank@dense"] == (1, "rerank@dense") and depths["rerank@lexical"] == (2, None)


# --------------------------------------------------------------------------- report binding


def _manifest(*, reranker: str) -> dict:
    identity = {
        "service_id": "search", "deployment_revision": f"deploy-{reranker}", "corpus_revision": "corpus-v1",
        "index_build_id": "index-v1", "chunking_revision": "chunk-v1", "embedding_model_revision": "embed-v1",
        "reranker_model_revision": reranker,
    }
    return {
        "dataset": {"query_hash": "queries", "corpus_hash": "corpus", "qrel_hash": "qrels"},
        "labeling": {"method": "gold", "judge": None, "model": None, "version": None},
        "counts": {"attempted": 6, "completed": 6, "labeled": 6, "metric_eligible": 6},
        "evaluation": {"unit": "document", "boundary": "final_retrieval", "k": 10, "relevance_threshold": 1},
        "normalized_config": {"pipelines": [{"id": "pipeline"}]},
        "release_identity": identity,
    }


async def _seed(db_path: str, *, latency: bool) -> None:
    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    for run_id, reranker in (("baseline", "reranker-v1"), ("candidate", "reranker-v2")):
        await store.save_run(run_id, run_id, "{}")
        await store.save_run_manifest(run_id, _manifest(reranker=reranker))
        rows = _rows(run_id, "pipeline", [0, 1], latency=latency)
        await store.save_metrics_batch([{**row, "query_metadata_json": row.pop("query_metadata")} for row in rows])


def _report_policy() -> ReleasePolicyV3:
    return _v3(
        intervention={"expected_changes": ["reranker_model_revision"]},
        metrics=[
            _check(),
            _check(id="query-latency", metric="latency_ms", target="query", estimator="p95", direction="lower_is_better", max_regression=50.0),
        ],
    )


def test_comparison_report_binds_v3_resolution(tmp_path):
    db_path = str(tmp_path / "v3.db")
    asyncio.run(_seed(db_path, latency=True))
    policy = _report_policy()

    report = retrieval_observatory.compare("baseline", "candidate", db_path=db_path, policy=policy)

    decision = report.comparison["release_decision"]
    assert decision["policy"] == {"configured": True, "id": policy.id, "schema_version": 3, "digest": policy.digest}
    resolution = decision["policy_resolution"]
    assert [(check["id"], check["status"]) for check in resolution["checks"]] == [
        ("final-recall", "resolved"), ("query-latency", "resolved"),
    ]
    assert resolution["checks"][0]["metric_key_by_run"] == {
        "baseline": "pipeline|stage1|recall@10", "candidate": "pipeline|stage1|recall@10",
    }
    assert resolution["findings"] == []
    assert "policy_conversion" not in decision
    assert decision["status"] != "BLOCK", decision["reasons"]
    assert [guard["metric"] for guard in decision["aggregate_guards"]] == [
        "pipeline|stage1|recall@10", "pipeline|stage-1|latency_p95@0",
    ]
    assert decision["aggregate_guards"][1]["estimator"] == "p95"


def test_comparison_report_blocks_when_a_v3_check_is_absent(tmp_path):
    db_path = str(tmp_path / "v3-absent.db")
    asyncio.run(_seed(db_path, latency=False))

    report = retrieval_observatory.compare("baseline", "candidate", db_path=db_path, policy=_report_policy())

    decision = report.comparison["release_decision"]
    assert decision["status"] == "BLOCK"
    assert METRIC_SELECTOR_UNRESOLVED in decision["reasons"]
    aggregate = decision["readiness"]["aggregate_or_slice_evaluation"]
    finding = next(item for item in aggregate["findings"] if item["code"] == METRIC_SELECTOR_UNRESOLVED)
    assert finding["status"] == "BLOCK" and finding["observed"] == {"check_id": "query-latency"}
    assert decision["policy_resolution"]["checks"][1]["status"] == "absent"
    assert decision["policy"]["schema_version"] == 3


def test_comparison_report_attaches_v2_conversion(tmp_path):
    db_path = str(tmp_path / "v2.db")
    asyncio.run(_seed(db_path, latency=True))
    policy = ReleasePolicy.model_validate({
        "id": "positional", "schema_version": 2,
        "intervention": {"expected_changes": ["reranker_model_revision"]},
        "statistics": {"confidence_level": 0.95, "familywise_alpha": 0.05, "resamples": 4000, "seed": 1},
        "metrics": [{
            "metric": "pipeline|stage1|recall@10", "direction": "higher_is_better",
            "max_regression": 0.05, "min_paired_n": 2,
        }],
    })

    report = retrieval_observatory.compare("baseline", "candidate", db_path=db_path, policy=policy)

    decision = report.comparison["release_decision"]
    assert decision["policy"]["schema_version"] == 2 and decision["policy"]["digest"] == policy.digest
    assert decision["policy_resolution"]["checks"][0]["status"] == "resolved"
    conversion = decision["policy_conversion"]
    assert conversion["policy"]["metrics"][0]["target"] == "final_retrieval"
    assert conversion["policy"]["digest"] != policy.digest
    assert decision["status"] == "PASS", decision["reasons"]
