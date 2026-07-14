from __future__ import annotations

from retrieval_observatory.metrics.comparison import compare_paired_metrics, comparison_validity


METRIC = "pipeline|stage0|recall@10"


def _manifest(dataset: str = "same") -> dict:
    return {
        "dataset": {"query_hash": dataset, "corpus_hash": dataset, "qrel_hash": dataset},
        "labeling": {"method": "gold", "judge": None, "model": None, "version": None},
        "execution": {"seed": 1, "cache_results": False, "timeout_ms": 5000},
        "git_commit": "commit",
        "git_dirty": False,
        "models": [{"model": "bm25"}],
        "packages": {"retobs": "test"},
    }


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
        }
        for index, value in enumerate(values)
    ]


def test_invalid_runs_have_no_statistical_decision() -> None:
    validity = comparison_validity([_manifest("one"), _manifest("two")])
    result = compare_paired_metrics(_rows([0.0] * 25), _rows([1.0] * 25), [METRIC], validity)[METRIC]

    assert validity.decision_allowed is False
    assert result.decision == "no_decision"
    assert result.p_value is None
    assert result.q_value is None
    assert result.reason == "comparison validity failed"


def test_low_power_direction_does_not_become_a_winner() -> None:
    validity = comparison_validity([_manifest(), _manifest()])
    result = compare_paired_metrics(_rows([0.0] * 5), _rows([1.0] * 5), [METRIC], validity)[METRIC]

    assert result.low_power is True
    assert result.decision == "no_decision"
    assert result.reason == "insufficient paired samples"


def test_candidate_orientation_and_bh_decision_are_explicit() -> None:
    validity = comparison_validity([_manifest(), _manifest()])
    result = compare_paired_metrics(_rows([0.0] * 25), _rows([1.0] * 25), [METRIC], validity)[METRIC]

    assert result.effect == 1.0
    assert result.paired_n == 25
    assert result.q_value is not None
    assert result.significant is True
    assert result.decision == "candidate_better"


def test_profile_metrics_use_latency_like_threshold_and_orientation() -> None:
    """Sub-ms profile deltas must not gate CI as quality regressions."""
    profile = "pipeline|stage0|profile_compute_ms@0"

    def _profile_rows(values: list[float]) -> list[dict]:
        return [
            {
                "pipeline_id": "pipeline",
                "stage_index": 0,
                "metric_name": "profile_compute_ms",
                "k": 0,
                "branch_id": None,
                "query_id": f"q-{index}",
                "value": value,
            }
            for index, value in enumerate(values)
        ]

    validity = comparison_validity([_manifest(), _manifest()])
    # ~0.013 ms mean drop would look "significant" under the 0.01 quality threshold,
    # but must stay no_decision under the latency-style floor of 1.0.
    result = compare_paired_metrics(
        _profile_rows([0.07] * 25),
        _profile_rows([0.057] * 25),
        [profile],
        validity,
    )[profile]

    assert result.effect_threshold == 1.0
    assert result.decision == "no_decision"
    assert result.reason == "effect is below the declared practical threshold"
