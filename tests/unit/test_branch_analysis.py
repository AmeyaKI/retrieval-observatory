from retrieval_observatory.analysis.branches import analyze_branches
from retrieval_observatory.tracing.model import OperatorSpan
from tests.fixtures.analysis_fixtures import analysis_scope, candidate, make_trace, source_span


def trace(policy="EXACT"):
    a = source_span("a", [candidate("shared"), candidate("a", 2)])
    b = source_span("b", [candidate("shared"), candidate("b", 2)])
    outputs = (candidate("shared"), candidate("a", 2), candidate("b", 3))
    f = OperatorSpan(
        "f",
        "FUSE",
        "f",
        ("a", "b"),
        "FIRED",
        1,
        {"a": tuple(a.outputs), "b": tuple(b.outputs)},
        outputs,
        replay_policy=policy,
    )
    return make_trace(spans=(a, b, f))


def test_branch_ready_replayed():
    assert analyze_branches([trace()], {"q1": {"b": 1}}, analysis_scope()).state == "ready"


def test_branch_partial_inferred():
    assert analyze_branches([trace("NOT_REPLAYABLE")], {}, analysis_scope()).state == "partial"


def test_branch_unavailable():
    assert analyze_branches([make_trace(spans=(source_span(),))], {}, analysis_scope()).state == "unavailable"
