from retrieval_observatory.analysis.corpus_health import analyze_corpus_health
from tests.fixtures.analysis_fixtures import analysis_scope


def test_corpus_ready():
    assert (
        analyze_corpus_health(
            {"document_count": 10, "index_document_count": 10, "duplicate_count": 0, "empty_count": 0},
            None,
            analysis_scope(),
        ).state
        == "ready"
    )


def test_corpus_partial():
    assert analyze_corpus_health({"document_count": 10}, None, analysis_scope()).state == "partial"


def test_corpus_unavailable():
    assert analyze_corpus_health(None, None, analysis_scope()).state == "unavailable"
