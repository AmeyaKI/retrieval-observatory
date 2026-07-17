from retrieval_observatory.analysis.instrumentation import analyze_instrumentation
from tests.fixtures.analysis_fixtures import analysis_scope, make_trace, source_span


def test_instrumentation_ready():
    assert (
        analyze_instrumentation(
            None, [make_trace(spans=(source_span(),))], {"accepted": 1, "exported": 1}, analysis_scope()
        ).state
        == "ready"
    )


def test_instrumentation_partial():
    assert (
        analyze_instrumentation(
            None, [make_trace(spans=(source_span(),))], {"accepted": 1, "dropped": 1}, analysis_scope()
        ).state
        == "partial"
    )


def test_instrumentation_unavailable():
    assert analyze_instrumentation(None, [], None, analysis_scope()).state == "unavailable"
