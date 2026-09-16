"""A candidate that fails on queries the baseline answered must not PASS on the survivors."""
from __future__ import annotations

from pathlib import Path

from retrieval_observatory.metrics.comparison import (
    ComparisonValidity,
    compare_paired_metrics,
    pair_coverage,
)
from retrieval_observatory.release.assessment import assess_evidence
from retrieval_observatory.release.decision import decide_release
from retrieval_observatory.release.policy import ReleasePolicy, load_release_policy
from retrieval_observatory.release.slices import evaluate_declared_slices
from retrieval_observatory.release.statistics import evaluate_metric_guards


METRIC = "p|stage0|recall@10"
FIXTURE = Path(__file__).parents[1] / "fixtures" / "release_policy.yaml"


def _policy(**statistics):
    return ReleasePolicy.model_validate({
        "id": "demo",
        "schema_version": 2,
        "statistics": {"confidence_level": 0.95, "familywise_alpha": 0.05, "resamples": 200, "seed": 17, **statistics},
        "metrics": [{"metric": METRIC, "direction": "higher_is_better", "max_regression": 0.02, "min_paired_n": 30}],
    })


def _rows(values, pipeline="p", branch_id=None):
    return [
        {"pipeline_id": pipeline, "stage_index": 0, "metric_name": "recall", "k": 10, "value": v, "query_id": f"q{i}", "branch_id": branch_id}
        for i, v in enumerate(values)
        if v is not None
    ]


def _failure_rows(statuses, pipeline="p"):
    return [
        {"pipeline_id": pipeline, "stage_index": -1, "metric_name": "failure", "k": 0, "value": 1.0 if failed else 0.0, "query_id": f"q{i}", "branch_id": None}
        for i, failed in enumerate(statuses)
    ]


MANIFEST = {
    "dataset": {"query_hash": "q", "corpus_hash": "c", "qrel_hash": "r"},
    "labeling": {"method": "human", "judge": None, "model": None, "version": "1"},
    "counts": {"attempted": 100, "completed": 100},
}


def test_candidate_that_timed_out_on_thirty_queries_is_hold_not_pass():
    baseline = [1.0] * 100
    candidate = [1.0] * 70 + [None] * 30  # no metric rows for the 30 timed-out queries
    policy = _policy()
    guards = evaluate_metric_guards(policy, _rows(baseline), _rows(candidate))
    assessment = assess_evidence(policy, MANIFEST, {**MANIFEST, "counts": {"attempted": 100, "completed": 70}})
    decision = decide_release(policy, assessment, guards, evaluate_declared_slices(policy, _rows(baseline), _rows(candidate)))

    guard = guards[0]
    assert guard.status == "HOLD"
    assert guard.paired_n == 70
    assert guard.attempted_n == 100
    assert guard.pair_coverage == 0.7
    assert guard.min_pair_coverage == 0.95
    assert guard.sample_limitation == "only 70.0% of attempted queries are paired; 0 failed in baseline, 30 in candidate"
    assert decision.status == "HOLD"
    assert guard.model_dump()["pair_coverage"] == 0.7


def test_failure_indicator_rows_make_failed_queries_count_as_attempted():
    """Failed queries have no recall rows, only `failure@0` = 1.0; they still lower coverage."""
    baseline = _rows([1.0] * 100) + _failure_rows([False] * 100)
    ok = _rows([1.0] * 94) + _failure_rows([False] * 94 + [True] * 6)
    assert evaluate_metric_guards(_policy(), baseline, ok)[0].status == "HOLD"
    borderline = _rows([1.0] * 95) + _failure_rows([False] * 95 + [True] * 5)
    assert evaluate_metric_guards(_policy(), baseline, borderline)[0].status == "PASS"
    assert evaluate_metric_guards(_policy(min_pair_coverage=1.0), baseline, borderline)[0].status == "HOLD"


def test_branch_rows_covering_fewer_queries_are_not_a_coverage_gap():
    """Per-branch rows only cover served queries; routing is not failure."""
    baseline = _rows([1.0] * 100) + _rows([1.0] * 30, branch_id="fast")
    candidate = _rows([1.0] * 100) + _rows([1.0] * 30, branch_id="fast")
    coverage = pair_coverage(
        {f"q{i}": 1.0 for i in range(30)}, {f"q{i}": 1.0 for i in range(30)}, baseline, candidate, "p"
    )
    assert (coverage.paired_n, coverage.attempted_n, coverage.coverage) == (30, 30, 1.0)
    assert coverage.below(0.95) is False


def test_policy_min_pair_coverage_is_optional_with_default():
    assert load_release_policy(FIXTURE).statistics.min_pair_coverage == 0.95
    assert _policy(min_pair_coverage=0.5).statistics.min_pair_coverage == 0.5


def test_compare_paired_metrics_exposes_coverage_and_withholds_decision():
    valid = ComparisonValidity(outcome="valid", decision_allowed=True, differences=[], required_axes=[])
    baseline = _rows([0.2] * 100)
    candidate = _rows([0.9] * 70 + [None] * 30)
    result = compare_paired_metrics(baseline, candidate, [METRIC], valid)[METRIC]

    assert result.paired_n == 70
    assert result.attempted_n == 100
    assert result.pair_coverage == 0.7
    assert result.decision == "no_decision"
    assert result.reason == "only 70.0% of attempted queries are paired; 0 failed in baseline, 30 in candidate"
    assert result.to_dict()["pair_coverage"] == 0.7

    complete = compare_paired_metrics(baseline, _rows([0.9] * 100), [METRIC], valid)[METRIC]
    assert complete.pair_coverage == 1.0
    assert complete.decision == "candidate_better"
