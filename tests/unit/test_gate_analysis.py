from retrieval_observatory.analysis.gates import analyze_gates
from retrieval_observatory.tracing.model import OperatorSpan
from tests.fixtures.analysis_fixtures import analysis_scope, make_trace, source_span


def traces():
    s = source_span()
    g = OperatorSpan(
        "gate",
        "GATE",
        "gate",
        ("source",),
        "FIRED",
        1,
        {"source": tuple(s.outputs)},
        tuple(s.outputs),
        gate_values={"route": "legal"},
    )
    return [make_trace(spans=(s, g))]


def test_gate_ready_with_labels():
    assert analyze_gates(traces(), {}, {"q1": "legal"}, analysis_scope()).state == "ready"


def test_gate_partial_without_labels():
    assert analyze_gates(traces(), {}, {}, analysis_scope()).state == "partial"


def test_gate_unavailable_without_gate():
    assert analyze_gates([make_trace(spans=(source_span(),))], {}, {}, analysis_scope()).state == "unavailable"
