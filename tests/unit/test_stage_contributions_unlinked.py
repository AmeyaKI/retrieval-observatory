"""Cross-pipeline contributions for pipelines whose steps are unlinked (no spine stage)."""

from retrieval_observatory.dashboard.api import _compute_stage_contributions


def _row(pipeline_id, stage_index, branch_id, value, query_id):
    return {
        "query_id": query_id, "pipeline_id": pipeline_id, "stage_index": stage_index,
        "branch_id": branch_id, "metric_name": "recall", "k": 10, "value": value,
    }


def _mean(pipeline_id, stage_index, branch_id, mean):
    branch = f"|branch={branch_id}" if branch_id else ""
    return f"{pipeline_id}|stage{stage_index}|recall@10{branch}", {
        "pipeline_id": pipeline_id, "stage_index": stage_index, "metric_name": "recall",
        "k": 10, "mean": mean, "branch_id": branch_id,
    }


def test_unlinked_pipelines_compare_their_final_answers():
    # Each pipeline's steps are unlinked: per-step rows are branches at stage 0 and the final
    # answer is at stage -1. There is no spine stage >= 0 to take a max over.
    metrics = dict([
        _mean("lexical", 0, "merge_lanes", 0.5),
        _mean("lexical", -1, None, 0.5),
        _mean("lexical__diversify", 0, "merge_lanes", 0.5),
        _mean("lexical__diversify", 0, "diversify", 0.75),
        _mean("lexical__diversify", -1, None, 0.75),
    ])
    rows = [
        _row("lexical", -1, None, 0.5, "q1"), _row("lexical", -1, None, 0.5, "q2"),
        _row("lexical__diversify", -1, None, 1.0, "q1"), _row("lexical__diversify", -1, None, 0.5, "q2"),
    ]
    contributions = _compute_stage_contributions(metrics, rows)
    cross = [c for c in contributions if c["comparison_tier"] == "cross_pipeline_prefix"]
    assert len(cross) == 1
    assert cross[0]["deltas"]["recall@10"]["n_pairs"] == 2
