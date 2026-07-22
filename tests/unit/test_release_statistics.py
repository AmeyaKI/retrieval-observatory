import pytest

from retrieval_observatory.release.policy import ReleasePolicy
from retrieval_observatory.release.statistics import (
    evaluate_metric_guards,
    paired_bootstrap_effect_ci,
)


METRIC = "pipeline|stage0|recall@10"


def _policy(*, direction: str = "higher_is_better", max_regression: float = 0.05) -> ReleasePolicy:
    return ReleasePolicy.model_validate(
        {
            "id": "release-v2",
            "schema_version": 2,
            "statistics": {
                "confidence_level": 0.95,
                "familywise_alpha": 0.05,
                "resamples": 500,
                "seed": 7,
            },
            "metrics": [
                {
                    "metric": METRIC,
                    "direction": direction,
                    "max_regression": max_regression,
                    "min_paired_n": 2,
                }
            ],
        }
    )


def _rows(values: list[float]) -> list[dict]:
    return [
        {
            "pipeline_id": "pipeline",
            "stage_index": 0,
            "metric_name": "recall",
            "k": 10,
            "branch_id": None,
            "query_id": f"q-{index}",
            "value": value,
            "query_metadata": {},
        }
        for index, value in enumerate(values)
    ]


def test_p95_resampling_recomputes_quantile_not_mean():
    low, high = paired_bootstrap_effect_ci(
        [1.0] * 95 + [100.0] * 5,
        [1.0] * 95 + [200.0] * 5,
        estimator="p95",
        n_resamples=500,
        confidence_level=0.95,
        seed=7,
    )

    assert low is not None
    assert high is not None
    assert high > 50.0


def test_paired_interval_is_deterministic_and_requires_equal_nonempty_pairs():
    arguments = {
        "estimator": "mean",
        "n_resamples": 200,
        "confidence_level": 0.95,
        "seed": 11,
    }

    assert paired_bootstrap_effect_ci([1, 2, 3], [2, 3, 4], **arguments) == paired_bootstrap_effect_ci(
        [1, 2, 3], [2, 3, 4], **arguments
    )
    assert paired_bootstrap_effect_ci([], [], **arguments) == (None, None)
    with pytest.raises(ValueError, match="equal length"):
        paired_bootstrap_effect_ci([1], [1, 2], **arguments)


def test_guard_interval_status_uses_noninferiority_boundary():
    passing = evaluate_metric_guards(_policy(), _rows([1.0, 1.0]), _rows([1.0, 1.0]))[0]
    failing = evaluate_metric_guards(_policy(), _rows([1.0, 1.0]), _rows([0.0, 0.0]))[0]
    crossing = evaluate_metric_guards(
        _policy(),
        _rows([1.0, 1.0, 1.0, 1.0]),
        _rows([0.8, 1.2, 1.0, 1.0]),
    )[0]
    underpowered = evaluate_metric_guards(_policy(), _rows([1.0]), _rows([1.0]))[0]

    assert passing.status == "PASS"
    assert failing.status == "FAIL"
    assert crossing.status == "HOLD"
    assert underpowered.status == "HOLD"
    assert passing.interval_method == "paired_percentile_bootstrap"
    assert passing.adjusted_confidence_level == 0.95


def test_lower_is_better_guard_inverts_the_regression_boundary():
    passing = evaluate_metric_guards(
        _policy(direction="lower_is_better"),
        _rows([1.0, 1.0]),
        _rows([1.04, 1.04]),
    )[0]
    failing = evaluate_metric_guards(
        _policy(direction="lower_is_better"),
        _rows([1.0, 1.0]),
        _rows([1.1, 1.1]),
    )[0]

    assert passing.status == "PASS"
    assert failing.status == "FAIL"
