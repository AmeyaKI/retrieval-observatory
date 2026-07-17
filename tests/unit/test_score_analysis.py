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
