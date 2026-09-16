from retrieval_observatory.analysis.scores import analyze_scores
from tests.fixtures.analysis_fixtures import analysis_scope, make_trace, source_span


def test_score_ready_single_operator():
    assert analyze_scores([make_trace(spans=(source_span(),))], {"q1": {"d1": 1}}, analysis_scope()).state == "ready"


def test_score_partial_cross_operator():
    assert (
        analyze_scores(
            [make_trace(spans=(source_span("a"), source_span("b")))], {"q1": {"d1": 1}}, analysis_scope()
        ).state
        == "partial"
    )


def test_score_unavailable_without_labels():
    assert analyze_scores([make_trace(spans=(source_span(),))], {}, analysis_scope()).state == "unavailable"


def test_calibration_bins_partition_scores_on_bin_edges():
    """Closed intervals on both ends double-counted every score that sat on a bin edge."""
    from types import SimpleNamespace as NS

    from retrieval_observatory.analysis.contracts import AnalysisScope

    candidates = [NS(doc_id=f"d{i}", score=i / 10) for i in range(11)]
    trace = NS(query_id="q", spans=[NS(op_id="op", outputs=candidates)])
    op = analyze_scores([trace], {"q": {"d10": 1}}, AnalysisScope(db_id="x"), bins=10).data["operators"]["op"]

    assert op["count"] == 11
    assert sum(b["count"] for b in op["calibration_bins"]) == 11
    assert op["calibration_bins"][-1]["count"] == 2  # 0.9 and the closed maximum 1.0
    assert op["calibration_bins"][-1]["relevance_rate"] == 0.5
