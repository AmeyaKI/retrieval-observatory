from retrieval_observatory.forge.generation.rule_based import generate_rule_based_queries
from retrieval_observatory.forge.types import CorpusScenario


def test_rule_based_comparison_queries():
    scenario = CorpusScenario(
        scenario_id="s1",
        scenario_type="temporal",
        anchor_doc_ids=["d1"],
        evidence_summary="test",
    )
    corpus = {"d1": {"title": "API Reference", "text": "api docs"}}
    queries = generate_rule_based_queries(scenario, corpus, ["comparison"], n_per_type=2)
    assert len(queries) == 2
    assert queries[0].query_type == "comparison"
    assert "api reference" in queries[0].text.lower()


def test_rule_based_long_tail_difficulty():
    scenario = CorpusScenario(
        scenario_id="s1",
        scenario_type="alias",
        anchor_doc_ids=["d1"],
        evidence_summary="test",
    )
    corpus = {"d1": {"title": "RAG", "text": "retrieval augmented generation"}}
    queries = generate_rule_based_queries(scenario, corpus, ["long_tail"], n_per_type=1)
    assert queries[0].difficulty_label == "hard"
