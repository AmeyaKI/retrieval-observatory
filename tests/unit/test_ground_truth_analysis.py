from retrieval_observatory.analysis.ground_truth import analyze_ground_truth
from tests.fixtures.analysis_fixtures import analysis_scope


def test_ground_truth_ready():
    assert analyze_ground_truth({"q1": {"d": 1}}, [{"query_id": "q1"}], [], analysis_scope()).state == "ready"


def test_ground_truth_partial_queue():
    assert (
        analyze_ground_truth({"q1": {"d": 1}}, [{"query_id": "q1"}, {"query_id": "q2"}], [], analysis_scope()).state
        == "partial"
    )


def test_ground_truth_unavailable():
    assert analyze_ground_truth({}, [], [], analysis_scope()).state == "unavailable"
