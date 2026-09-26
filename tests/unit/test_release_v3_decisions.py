"""Direct evaluation of a resolved v3 policy: per-run keys, quantile resampling, family-adjusted
intervals, frozen slices, execution accounting, and BLOCK > FAIL > HOLD > PASS precedence."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from retrieval_observatory.release.assessment import EvidenceAssessment
from retrieval_observatory.release.decision import ReleaseDecision, decide_release, decide_release_v3
from retrieval_observatory.release.policy import ReleasePolicyV3, load_release_policy
from retrieval_observatory.release.readiness import ClaimReadiness
from retrieval_observatory.release.resolution import RunEvidence, resolve_policy
from retrieval_observatory.release.slices import evaluate_declared_slices, evaluate_resolved_slices
from retrieval_observatory.release.statistics import (
    ATTEMPT_ACCOUNTING_UNKNOWN,
    FAILURE_RATE_EXCEEDED,
    CheckResult,
    evaluate_execution,
    evaluate_metric_guards,
    evaluate_resolved_checks,
)


V2_FIXTURE = Path(__file__).parents[1] / "fixtures" / "release_policy.yaml"
PIPELINE = "pipeline"


# --------------------------------------------------------------------------- builders


def _check(**changes):
    check = {
        "id": "final-recall", "metric": "recall", "target": "final_retrieval",
        "direction": "higher_is_better", "max_regression": 0.25, "min_paired_n": 2,
    }
    check.update(changes)
    return check


def _latency_check(**changes):
    check = _check(id="query-latency", metric="latency_ms", target="query", estimator="p95", direction="lower_is_better", max_regression=50.0)
    check.update(changes)
    return check


def _policy(**changes) -> ReleasePolicyV3:
    payload = {
        "schema_version": 3,
        "id": "v3-decisions",
        "evaluation": {"unit": "document", "k": 10},
        "statistics": {"confidence_level": 0.95, "familywise_alpha": 0.05, "resamples": 4000, "seed": 17},
        "metrics": [_check()],
    }
    payload.update(changes)
    return ReleasePolicyV3.model_validate(payload)


def _row(query_id: str, stage: int, metric: str, value: float, *, k: int = 10, metadata: dict | None = None) -> dict:
    return {
        "pipeline_id": PIPELINE, "query_id": query_id, "stage_index": stage, "metric_name": metric,
        "k": k, "value": float(value), "branch_id": None, "query_metadata": metadata or {},
    }


def _recall_rows(values, *, stages=(0, 1), metadata=None, ids=None):
    """Recall rows at every stage in ``stages`` (the last is the final stage), plus OK failure indicators."""
    ids = ids or [f"q-{index}" for index in range(len(values))]
    rows = []
    for query_id, value in zip(ids, values):
        meta = (metadata or {}).get(query_id)
        rows.extend(_row(query_id, stage, "recall", value, metadata=meta) for stage in stages)
        rows.append(_row(query_id, -1, "failure", 0.0, k=0, metadata=meta))
        rows.append(_row(query_id, -1, "timeout", 0.0, k=0, metadata=meta))
    return rows


def _failed_rows(ids, *, timeout=False, metadata=None):
    rows = []
    for query_id in ids:
        meta = (metadata or {}).get(query_id)
        rows.append(_row(query_id, -1, "failure", 1.0, k=0, metadata=meta))
        rows.append(_row(query_id, -1, "timeout", 1.0 if timeout else 0.0, k=0, metadata=meta))
    return rows


def _latency_rows(values):
    return [_row(f"q-{index}", -1, "latency_ms", value, k=0) for index, value in enumerate(values)]


def _evidence(run_id: str, rows, *, attempted: int | None = "rows") -> RunEvidence:
    manifest = {"normalized_config": {"pipelines": [{"id": PIPELINE}]}}
    if attempted != "rows":
        manifest["counts"] = {"attempted": attempted, "completed": None}
    return RunEvidence(run_id=run_id, manifest=manifest, metric_rows=rows)


def _assessment(*, promotion: str = "READY", aggregate: str = "READY") -> EvidenceAssessment:
    statuses = {
        "promotion": promotion, "aggregate_or_slice_evaluation": aggregate,
        "lineage_diagnosis": "BLOCK", "lineage_diff": "BLOCK", "production_trace": "READY",
    }
    return EvidenceAssessment(readiness={
        scope: ClaimReadiness(scope=scope, status=status, findings=[]) for scope, status in statuses.items()
    })


def _evaluate(policy, baseline_rows, candidate_rows, *, expected=None, baseline_attempted="rows", candidate_attempted="rows"):
    baseline = _evidence("baseline", baseline_rows, attempted=baseline_attempted)
    candidate = _evidence("candidate", candidate_rows, attempted=candidate_attempted)
    resolved = resolve_policy(policy, baseline, candidate)
    checks = evaluate_resolved_checks(resolved, baseline, candidate, expected_query_ids=expected)
    slices = evaluate_resolved_slices(resolved, baseline, candidate, expected_query_ids=expected)
    operational = evaluate_execution(resolved, baseline, candidate)
    return resolved, checks, slices, operational


def _decide(policy, baseline_rows, candidate_rows, **kwargs) -> ReleaseDecision:
    resolved, checks, slices, operational = _evaluate(policy, baseline_rows, candidate_rows, **kwargs)
    return decide_release_v3(resolved, _assessment(), checks, slices, operational)


# --------------------------------------------------------------------------- direction and sign


def test_higher_is_better_boundary_is_inclusive_then_crossing_then_beyond():
    baseline = _recall_rows([1.0] * 8)
    at_boundary = _evaluate(_policy(), baseline, _recall_rows([0.75] * 8))[1][0]
    crossing = _evaluate(_policy(), baseline, _recall_rows([0.7, 0.8] * 4))[1][0]
    beyond = _evaluate(_policy(), baseline, _recall_rows([0.5] * 8))[1][0]

    assert (at_boundary.effect, at_boundary.ci_low, at_boundary.status) == (-0.25, -0.25, "PASS")
    assert crossing.ci_low < -0.25 <= crossing.ci_high and crossing.status == "HOLD"
    assert beyond.ci_high < -0.25 and beyond.status == "FAIL"
    assert beyond.effect == -0.5  # candidate minus baseline: negative when the candidate is worse
    assert beyond.affected_query_ids[:2] == ["q-0", "q-1"]


def test_lower_is_better_mirrors_the_boundary():
    policy = _policy(metrics=[_latency_check(estimator="mean")])
    baseline = _latency_rows([100.0] * 8)
    at_boundary = _evaluate(policy, baseline, _latency_rows([150.0] * 8))[1][0]
    crossing = _evaluate(policy, baseline, _latency_rows([140.0, 160.0] * 4))[1][0]
    beyond = _evaluate(policy, baseline, _latency_rows([200.0] * 8))[1][0]

    assert (at_boundary.effect, at_boundary.ci_high, at_boundary.status) == (50.0, 50.0, "PASS")
    assert crossing.ci_low <= 50.0 < crossing.ci_high and crossing.status == "HOLD"
    assert beyond.ci_low > 50.0 and beyond.status == "FAIL"
    assert beyond.metric == "pipeline|stage-1|latency_ms@0" and beyond.estimator == "mean"


def test_p95_check_resamples_the_quantile_not_the_mean():
    policy = _policy(metrics=[_latency_check()])
    baseline = _latency_rows([0.0] * 9 + [10.0])  # mean 1.0, p95 5.5
    candidate = _latency_rows([1.0] * 10)  # mean 1.0, p95 1.0

    check = _evaluate(policy, baseline, candidate)[1][0]

    assert check.estimator == "p95"
    assert check.metric == "pipeline|stage-1|latency_p95@0"
    assert (check.baseline_estimate, check.candidate_estimate) == (pytest.approx(5.5), 1.0)
    assert check.effect == pytest.approx(-4.5)
    # A 10-sample p95 is a distribution statistic: resamples without the outlier flip the sign,
    # so the interval is wide and honest, and clears the 50 ms tolerance from below.
    assert check.ci_low < 0.0 and check.ci_low <= check.effect <= check.ci_high
    assert check.ci_high <= 50.0 and check.status == "PASS"


# --------------------------------------------------------------------------- family and resolution


def test_family_size_counts_slice_metric_ids_and_records_the_adjusted_confidence():
    policy = _policy(
        metrics=[_check(), _latency_check(estimator="mean")],
        slices=[{"id": "critical", "field": "critical", "value": True, "metric_ids": ["final-recall"]}],
    )
    metadata = {"q-0": {"critical": True}, "q-1": {"critical": True}, "q-2": {"critical": False}}
    rows = _recall_rows([1.0, 1.0, 1.0], metadata=metadata) + _latency_rows([10.0, 10.0, 10.0])

    resolved, checks, slices, _ = _evaluate(policy, rows, rows)

    assert {check.family_size for check in checks} == {3}
    assert {check.adjusted_confidence_level for check in checks} == {1 - 0.05 / 3}
    assert {check.confidence_level for check in checks} == {0.95}
    assert slices[0].check_ids == ["final-recall"]
    assert slices[0].guards[0].adjusted_confidence_level == 1 - 0.05 / 3
    assert (checks[0].resamples, checks[0].seed) == (4000, 17)


def test_bootstrap_floor_at_evaluation_blocks_with_the_minimum_resamples():
    baseline = _evidence("baseline", _recall_rows([1.0] * 4))
    candidate = _evidence("candidate", _recall_rows([1.0] * 4))
    resolved = resolve_policy(_policy(), baseline, candidate)
    starved = replace(resolved, statistics={**resolved.statistics, "resamples": 100})

    check = evaluate_resolved_checks(starved, baseline, candidate)[0]

    assert check.status == "BLOCK"
    assert check.ci_low is None and check.ci_high is None
    assert "resamples 100" in check.sample_limitation and "at least 800 resamples are required" in check.sample_limitation


def test_missing_pairs_hold_under_full_coverage_and_proceed_under_a_declared_floor():
    baseline = _recall_rows([1.0] * 10)
    candidate = _recall_rows([1.0] * 8) + _failed_rows(["q-8", "q-9"], timeout=True)

    held = _evaluate(_policy(), baseline, candidate)[1][0]
    assert (held.attempted_n, held.paired_n, held.pair_coverage, held.min_pair_coverage) == (10, 8, 0.8, 1.0)
    assert held.status == "HOLD"
    assert held.sample_limitation == "only 80.0% of attempted queries are paired; 0 failed in baseline, 2 in candidate"

    relaxed = _policy(statistics={"confidence_level": 0.95, "familywise_alpha": 0.05, "resamples": 4000, "seed": 17, "min_pair_coverage": 0.75})
    proceeded = _evaluate(relaxed, baseline, candidate)[1][0]
    assert (proceeded.pair_coverage, proceeded.status, proceeded.sample_limitation) == (0.8, "PASS", None)

    # The expected universe counts an attempt that left no row at all.
    expected = {f"q-{index}" for index in range(10)}
    silent = _evaluate(_policy(), baseline, _recall_rows([1.0] * 8), expected=expected)[1][0]
    assert (silent.attempted_n, silent.paired_n, silent.status) == (10, 8, "HOLD")


def test_per_run_keys_are_evaluated_at_each_runs_final_stage():
    baseline = _recall_rows([1.0] * 6, stages=(0, 1))
    candidate = _recall_rows([1.0] * 6, stages=(0, 1, 2))

    resolved, checks, _, _ = _evaluate(_policy(), baseline, candidate)

    check = checks[0]
    assert resolved.findings == ()
    assert check.metric_key_by_run == {"baseline": "pipeline|stage1|recall@10", "candidate": "pipeline|stage2|recall@10"}
    assert check.metric == "pipeline|stage2|recall@10"
    assert check.resolution_status == "resolved"
    assert (check.paired_n, check.status) == (6, "PASS")


def test_unresolved_check_blocks_the_result_and_the_decision():
    policy = _policy(metrics=[_check(), _check(id="final-ndcg", metric="ndcg")])
    rows = _recall_rows([1.0] * 4)

    resolved, checks, slices, operational = _evaluate(policy, rows, rows)
    decision = decide_release_v3(resolved, _assessment(), checks, slices, operational)

    ndcg = checks[1]
    assert (ndcg.resolution_status, ndcg.status) == ("absent", "BLOCK")
    assert ndcg.metric_key_by_run == {"baseline": None, "candidate": None}
    assert ndcg.ci_low is None and "no ndcg@10 rows" in ndcg.sample_limitation
    assert decision.status == "BLOCK"
    assert any(reason.startswith("check final-ndcg: BLOCK") for reason in decision.reasons)


# --------------------------------------------------------------------------- slices


def _critical_policy(**changes):
    return _policy(slices=[{"id": "critical", "field": "critical", "value": True, "metric_ids": ["final-recall"]}], **changes)


def test_regressing_critical_slice_fails_while_the_aggregate_improves():
    critical = {f"q-{index}": {"critical": True} for index in range(4)}
    plain = {f"q-{index}": {"critical": False} for index in range(4, 30)}
    metadata = {**critical, **plain}
    baseline = _recall_rows([1.0] * 30, metadata=metadata)
    candidate = _recall_rows([0.5] * 4 + [1.5] * 26, metadata=metadata)

    decision = _decide(_critical_policy(), baseline, candidate)

    assert decision.aggregate_guards[0].status == "PASS" and decision.aggregate_guards[0].effect > 0
    assert decision.slices[0].status == "FAIL"
    assert decision.slices[0].guards[0].check_id == "final-recall"
    assert decision.slices[0].guards[0].paired_n == 4
    assert decision.status == "FAIL"
    assert any(reason.startswith("declared slice critical: FAIL") for reason in decision.reasons)


def test_slice_absent_from_the_candidate_blocks_and_names_the_run():
    metadata = {"q-0": {"critical": True}, "q-1": {"critical": True}}
    baseline = _recall_rows([1.0] * 4, metadata=metadata)
    candidate = _recall_rows([1.0] * 2, ids=["q-2", "q-3"])

    _, _, slices, _ = _evaluate(_critical_policy(), baseline, candidate)

    assert slices[0].status == "BLOCK"
    assert slices[0].sample_limitation == "declared slice is absent from run candidate"
    assert slices[0].guards == [] and slices[0].check_ids == ["final-recall"]

    nowhere = _evaluate(_critical_policy(), _recall_rows([1.0] * 2), _recall_rows([1.0] * 2))[2][0]
    assert nowhere.sample_limitation == "declared slice is absent from both runs"


def test_small_slice_holds_and_metadata_disagreement_is_reported():
    policy = _critical_policy(metrics=[_check(min_paired_n=3)])
    baseline_meta = {"q-0": {"critical": True}, "q-1": {"critical": True}, "q-2": {"critical": False}}
    candidate_meta = {"q-0": {"critical": True}, "q-1": {"critical": False}, "q-2": {"critical": False}}
    baseline = _recall_rows([1.0] * 3, metadata=baseline_meta)
    candidate = _recall_rows([1.0] * 3, metadata=candidate_meta)

    result = _evaluate(policy, baseline, candidate)[2][0]

    assert result.status == "HOLD"
    assert result.paired_n == 2  # q-1 stays a member: the candidate's metadata does not redefine it
    assert "paired sample count 2 is below required 3" in result.sample_limitation
    assert "query metadata 'critical' disagrees between runs for 1 queries (q-1)" in result.sample_limitation


# --------------------------------------------------------------------------- execution


def test_candidate_failure_rate_above_the_cap_fails_even_when_every_check_passes():
    relaxed = {"confidence_level": 0.95, "familywise_alpha": 0.05, "resamples": 4000, "seed": 17, "min_pair_coverage": 0.75}
    policy = _policy(statistics=relaxed, execution={"max_failure_rate": 0.0})
    baseline = _recall_rows([1.0] * 10)
    candidate = _recall_rows([1.0] * 8) + _failed_rows(["q-8", "q-9"])

    resolved, checks, slices, operational = _evaluate(policy, baseline, candidate)
    decision = decide_release_v3(resolved, _assessment(), checks, slices, operational)

    assert [check.status for check in checks] == ["PASS"]
    assert (operational.status, operational.code) == ("FAIL", FAILURE_RATE_EXCEEDED)
    assert (operational.candidate.attempted_n, operational.candidate.failed_n, operational.candidate.failure_rate) == (10, 2, 0.2)
    assert (operational.baseline.failed_n, operational.baseline.failure_rate) == (0, 0.0)
    assert decision.status == "FAIL"
    assert decision.operational == operational
    assert any(reason.startswith("execution: FAIL") for reason in decision.reasons)

    tolerant = _policy(statistics=relaxed, execution={"max_failure_rate": 0.2})
    assert _evaluate(tolerant, baseline, candidate)[3].status == "PASS"


def test_unknown_attempt_accounting_blocks():
    rows = _recall_rows([1.0] * 4)
    baseline = _evidence("baseline", rows)
    candidate = RunEvidence(run_id="candidate", manifest={"counts": {"attempted": None}}, metric_rows=[])
    resolved = resolve_policy(_policy(), baseline, candidate)

    operational = evaluate_execution(resolved, baseline, candidate)

    assert (operational.status, operational.code) == ("BLOCK", ATTEMPT_ACCOUNTING_UNKNOWN)
    assert operational.candidate.attempted_source == "unknown"
    assert "unknown for run candidate" in operational.detail
    assert operational.baseline.attempted_source == "metric_rows" and operational.baseline.attempted_n == 4

    manifest_counted = _evaluate(_policy(), rows, rows, candidate_attempted=8)[3]
    assert manifest_counted.candidate.attempted_source == "manifest"
    assert manifest_counted.candidate.attempted_n == 8


# --------------------------------------------------------------------------- precedence and determinism


def test_precedence_is_block_over_fail_over_hold_with_every_reason_listed():
    policy = _critical_policy(metrics=[_check(), _check(id="final-ndcg", metric="ndcg"), _latency_check(estimator="mean")])
    metadata = {f"q-{index}": {"critical": True} for index in range(2)}
    baseline = _recall_rows([1.0] * 8, metadata=metadata) + _latency_rows([100.0] * 8)
    candidate = _recall_rows([0.2] * 8, metadata=metadata) + _latency_rows([140.0, 160.0] * 4)

    resolved, checks, slices, operational = _evaluate(policy, baseline, candidate)
    decision = decide_release_v3(resolved, _assessment(), checks, slices, operational)

    assert [check.status for check in checks] == ["FAIL", "BLOCK", "HOLD"]
    assert slices[0].status == "FAIL"
    assert decision.status == "BLOCK"
    prefixes = ["check final-recall: FAIL", "check final-ndcg: BLOCK", "check query-latency: HOLD", "declared slice critical: FAIL"]
    assert all(any(reason.startswith(prefix) for reason in decision.reasons) for prefix in prefixes), decision.reasons
    latency_reason = next(reason for reason in decision.reasons if reason.startswith("check query-latency"))
    assert "crosses the 50 boundary" in latency_reason
    assert decision.policy.model_dump() == {"configured": True, "id": policy.id, "schema_version": 3, "digest": policy.digest}

    assert decide_release_v3(resolved, _assessment(promotion="BLOCK"), [], slices, operational).status == "BLOCK"
    without_ndcg = [check for check in checks if check.check_id != "final-ndcg"]
    missing = decide_release_v3(resolved, _assessment(), without_ndcg, slices, operational)
    assert missing.status == "BLOCK" and "required result is missing: check final-ndcg" in missing.reasons


def test_hold_reasons_name_the_shortfall_and_holding_readiness_holds():
    # Known pair loss without an operational breach: two attempted queries left no row at all.
    baseline = _recall_rows([1.0] * 10)
    candidate = _recall_rows([1.0] * 8)

    decision = _decide(_policy(), baseline, candidate, expected={f"q-{index}" for index in range(10)})

    assert decision.operational.status == "PASS"
    assert decision.status == "HOLD"
    assert decision.reasons == ["check final-recall: HOLD: only 80.0% of attempted queries are paired; 0 failed in baseline, 2 in candidate"]
    resolved, checks, slices, operational = _evaluate(_policy(), baseline, baseline)
    assert decide_release_v3(resolved, _assessment(), checks, slices, operational).status == "PASS"
    assert decide_release_v3(resolved, _assessment(promotion="HOLD"), checks, slices, operational).status == "HOLD"


def test_same_inputs_and_seed_give_an_identical_decision():
    rng = np.random.default_rng(3)
    baseline = _recall_rows(rng.uniform(0.2, 0.9, size=40))
    candidate = _recall_rows(rng.uniform(0.2, 0.9, size=40))

    first = _decide(_policy(), baseline, candidate).model_dump(mode="json")
    second = _decide(_policy(), baseline, candidate).model_dump(mode="json")

    assert first == second
    restored = ReleaseDecision.model_validate_json(_decide(_policy(), baseline, candidate).model_dump_json())
    assert isinstance(restored.aggregate_guards[0], CheckResult)
    assert restored.model_dump(mode="json") == first


# --------------------------------------------------------------------------- seeded simulation


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_a_true_regression_of_five_points_fails_a_one_point_tolerance(seed):
    rng = np.random.default_rng(seed)
    baseline_values = rng.uniform(0.3, 0.9, size=200)
    candidate_values = baseline_values - 0.05 + rng.normal(0.0, 0.1, size=200)
    policy = _policy(metrics=[_check(max_regression=0.01)], statistics={"confidence_level": 0.95, "familywise_alpha": 0.05, "resamples": 1000, "seed": seed})

    check = _evaluate(policy, _recall_rows(baseline_values), _recall_rows(candidate_values))[1][0]

    assert check.status == "FAIL", (check.ci_low, check.ci_high)


def test_no_true_effect_passes_a_five_point_tolerance_in_most_seeds():
    passed = 0
    for seed in (1, 2, 3, 4, 5):
        rng = np.random.default_rng(seed)
        baseline_values = rng.uniform(0.3, 0.9, size=200)
        candidate_values = baseline_values + rng.normal(0.0, 0.1, size=200)
        policy = _policy(metrics=[_check(max_regression=0.05)], statistics={"confidence_level": 0.95, "familywise_alpha": 0.05, "resamples": 1000, "seed": seed})
        check = _evaluate(policy, _recall_rows(baseline_values), _recall_rows(candidate_values))[1][0]
        passed += check.status == "PASS"

    assert passed >= 4


# --------------------------------------------------------------------------- v2 path unchanged


def test_v2_path_is_unchanged_and_carries_no_operational_result():
    policy = load_release_policy(V2_FIXTURE)
    rows = [
        {**_row(f"q-{index}", 1, "ndcg", 1.0), "pipeline_id": "hybrid__rerank"} for index in range(120)
    ]

    guards = evaluate_metric_guards(policy, rows, rows)
    decision = decide_release(policy, _assessment(), guards, evaluate_declared_slices(policy, rows, rows))

    assert decision.status == "PASS"
    assert decision.operational is None
    assert decision.model_dump(mode="json")["operational"] is None
    assert decision.policy.schema_version == 2
    assert "check_id" not in decision.model_dump()["aggregate_guards"][0]


def test_failed_unjudged_queries_count_against_the_failure_budget():
    """Indicator rows exist only for judged queries; the manifest's attempted-minus-completed covers every query."""
    from retrieval_observatory.release.statistics import evaluate_execution

    policy = _policy(execution={"max_failure_rate": 0.1})
    resolved = resolve_policy(policy, _evidence("baseline", _recall_rows([1.0] * 8)), _evidence("candidate", _recall_rows([1.0] * 8)))
    manifest = {"normalized_config": {"pipelines": [{"id": PIPELINE}]}, "counts": {"attempted": 12, "completed": 9}}
    baseline = RunEvidence(run_id="baseline", manifest=manifest, metric_rows=_recall_rows([1.0] * 8))
    # Two judged failures are visible as indicator rows; a third failed query was unjudged and has no rows.
    candidate = RunEvidence(run_id="candidate", manifest=manifest, metric_rows=_recall_rows([1.0] * 7) + _failed_rows(["q-7", "q-8"]))

    operational = evaluate_execution(resolved, baseline, candidate)

    assert operational.candidate.attempted_n == 12
    assert operational.candidate.failed_n == 3  # max(indicator failures 2, attempted 12 - completed 9)
    assert operational.candidate.attempted_source == "manifest"
    assert operational.status == "FAIL"
