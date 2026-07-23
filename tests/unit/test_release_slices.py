from retrieval_observatory.release.policy import ReleasePolicy
from retrieval_observatory.release.slices import evaluate_declared_slices


METRIC = "pipeline|stage0|recall@10"


def _policy(*, value="enterprise") -> ReleasePolicy:
    return ReleasePolicy.model_validate(
        {
            "id": "release-v2",
            "schema_version": 2,
            "statistics": {
                "confidence_level": 0.95,
                "familywise_alpha": 0.05,
                "resamples": 200,
                "seed": 7,
            },
            "metrics": [
                {
                    "metric": METRIC,
                    "direction": "higher_is_better",
                    "max_regression": 0.05,
                    "min_paired_n": 2,
                }
            ],
            "slices": [{"id": "enterprise", "field": "tier", "value": value}],
        }
    )


def _rows(tiers: list[object], values: list[float] | None = None) -> list[dict]:
    values = values or [1.0] * len(tiers)
    return [
        {
            "pipeline_id": "pipeline",
            "stage_index": 0,
            "metric_name": "recall",
            "k": 10,
            "branch_id": None,
            "query_id": f"q-{index}",
            "value": values[index],
            "query_metadata": {"tier": tier},
        }
        for index, tier in enumerate(tiers)
    ]


def test_absent_required_slice_blocks():
    result = evaluate_declared_slices(
        _policy(),
        _rows(["support", "support"]),
        _rows(["support", "support"]),
    )[0]

    assert result.status == "BLOCK"
    assert result.paired_n == 0
    assert result.label_coverage is None
    assert result.sample_limitation == "declared slice is absent from one or both runs"


def test_declared_slice_uses_exact_literal_and_query_pairing():
    result = evaluate_declared_slices(
        _policy(value=True),
        _rows([True, 1, True]),
        _rows([True, 1, False]),
    )[0]

    assert result.paired_n == 1
    assert result.guards[0].status == "HOLD"
    assert result.label_coverage == 0.5


def test_familywise_adjustment_counts_aggregate_and_declared_slice_guards():
    result = evaluate_declared_slices(
        _policy(),
        _rows(["enterprise", "enterprise"]),
        _rows(["enterprise", "enterprise"]),
    )[0]

    assert result.adjusted_confidence_level == 0.975
    assert result.guards[0].adjusted_confidence_level == 0.975
