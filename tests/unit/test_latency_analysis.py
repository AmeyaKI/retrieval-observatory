from retrieval_observatory.analysis.latency import analyze_latency
from tests.fixtures.analysis_fixtures import analysis_scope, make_trace, source_span


def test_latency_ready():
    assert analyze_latency([make_trace(spans=(source_span(),))], analysis_scope()).state == "ready"


def test_latency_partial():
    assert (
        analyze_latency(
            [make_trace(spans=(source_span(),)), make_trace("t2", timing=False, spans=())], analysis_scope()
        ).state
        == "partial"
    )


def test_latency_unavailable():
    assert analyze_latency([], analysis_scope()).state == "unavailable"
