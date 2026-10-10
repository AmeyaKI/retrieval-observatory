"""The printed summary names whole-list MRR and MAP plainly instead of as ``@0`` cutoffs."""
from __future__ import annotations

from retrieval_observatory.sdk.report import build_run_report


def test_whole_list_metrics_are_not_printed_as_cutoff_zero() -> None:
    metrics = {
        "hybrid|stage-1|ndcg@10": {"mean": 0.72, "ci_low": 0.7, "ci_high": 0.74},
        "hybrid|stage-1|mrr@0": {"mean": 0.69, "ci_low": 0.67, "ci_high": 0.71},
        "hybrid|stage-1|map@0": {"mean": 0.68, "ci_low": 0.66, "ci_high": 0.70},
    }
    report = build_run_report(
        run_id="r", experiment_name="e", db_path="db", metrics=metrics, diagnostics=[],
        manifest={"counts": {"attempted": 3, "completed": 3}},
    )

    markdown = report.to_markdown()

    assert "@0" not in markdown
    assert "`hybrid|stage-1|mrr (whole list)`" in markdown
    assert "`hybrid|stage-1|map (whole list)`" in markdown
    assert "`hybrid|stage-1|ndcg@10`" in markdown
    assert set(report.metrics) == set(metrics)  # stored keys are unchanged


def test_latency_rows_drop_the_cutoff_marker() -> None:
    metrics = {
        "hybrid|stage-1|ndcg@10": {"mean": 0.72},
        "hybrid|stage0|latency_p50@0": {"mean": 11.4},
    }
    report = build_run_report(
        run_id="r", experiment_name="e", db_path="db", metrics=metrics, diagnostics=[],
        manifest={"counts": {"attempted": 1, "completed": 1}},
    )

    assert "`hybrid|stage0|latency_p50`" in report.to_markdown()
