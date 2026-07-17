import pytest
from retrieval_observatory.analysis.cohorts import CohortClause, CohortDefinition, matches_cohort, validate_cohort


def test_rejects_unknown_field():
    with pytest.raises(ValueError, match="field is not allowed"):
        validate_cohort(CohortDefinition("c", "c", 1, (CohortClause("__class__", "eq", "x"),)))


def test_nested_metadata_and_conjunction():
    c = CohortDefinition(
        "c",
        "c",
        1,
        (
            CohortClause("trace.status", "eq", "ERROR"),
            CohortClause("query.metadata.tenant", "in", ("legal", "finance")),
        ),
    )
    assert matches_cohort({"trace": {"status": "ERROR"}, "query": {"metadata": {"tenant": "legal"}}}, c)
