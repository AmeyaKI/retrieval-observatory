import pytest
from retrieval_observatory.analysis.contracts import AnalysisResult, unavailable
from tests.fixtures.analysis_fixtures import analysis_scope, evidence_descriptor


def test_ready_requires_data_and_sample():
    with pytest.raises(ValueError, match="ready analysis requires"):
        AnalysisResult("ready", analysis_scope(), evidence_descriptor(sample_size=0, population_size=0), None)


def test_partial_requires_limits():
    with pytest.raises(ValueError, match="partial analysis requires"):
        AnalysisResult("partial", analysis_scope(), evidence_descriptor(), {})


def test_unavailable_is_explicit():
    assert unavailable(analysis_scope(), "x", "missing").unavailable_reason == "missing"
