"""Unit tests for StressTestSuite."""
from __future__ import annotations

from datetime import datetime, timezone

from retrieval_observatory.forge.stress.suite import StressTestSuite
from retrieval_observatory.forge.types import CorpusScenario, SyntheticDataset, SyntheticQuery


def _make_dataset() -> SyntheticDataset:
    scenarios = [
        CorpusScenario("s1", "temporal", ["d1", "d2"], "Temporal scenario"),
        CorpusScenario("s2", "alias", ["d3", "d4"], "Alias scenario"),
    ]
    queries = [
        SyntheticQuery("q1", "What happened in 2020?", "s1", "temporal", ["d1"], difficulty_label="hard"),
        SyntheticQuery("q2", "Describe the launch.", "s1", "paraphrase", ["d2"], difficulty_label="easy"),
        SyntheticQuery("q3", "What is ML?", "s2", "paraphrase", ["d3"], difficulty_label="medium"),
        SyntheticQuery("q4", "adversarial trick question", "s2", "adversarial", ["d4"], difficulty_label="extreme"),
    ]
    qrels = {
        "q1": {"d1": 2},
        "q2": {"d2": 2},
        "q3": {"d3": 2},
        "q4": {"d4": 2},
    }
    corpus = {f"d{i}": {"text": f"doc {i}", "title": ""} for i in range(1, 5)}
    return SyntheticDataset(
        dataset_id="test",
        corpus=corpus,
        queries=queries,
        qrels=qrels,
        scenarios=scenarios,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


class TestStressTestSuite:
    def setup_method(self):
        self.suite = StressTestSuite(_make_dataset())

    def test_get_by_difficulty(self):
        hard = self.suite.get_by_difficulty("hard")
        assert len(hard) == 1
        assert hard[0].query_id == "q1"

    def test_get_by_difficulty_extreme(self):
        extreme = self.suite.get_by_difficulty("extreme")
        assert len(extreme) == 1
        assert extreme[0].query_id == "q4"

    def test_get_by_query_type_paraphrase(self):
        para = self.suite.get_by_query_type("paraphrase")
        assert {q.query_id for q in para} == {"q2", "q3"}

    def test_get_by_scenario_type_temporal(self):
        temporal = self.suite.get_by_scenario_type("temporal")
        assert {q.query_id for q in temporal} == {"q1", "q2"}

    def test_get_by_scenario_type_alias(self):
        alias = self.suite.get_by_scenario_type("alias")
        assert {q.query_id for q in alias} == {"q3", "q4"}

    def test_to_benchmark_inputs_all(self):
        retobs_queries, qrels = self.suite.to_benchmark_inputs()
        assert len(retobs_queries) == 4
        assert len(qrels) == 4

    def test_to_benchmark_inputs_difficulty_filter(self):
        retobs_queries, qrels = self.suite.to_benchmark_inputs(difficulty_filter="easy")
        assert len(retobs_queries) == 1
        assert retobs_queries[0].query_id == "q2"
        assert "q2" in qrels

    def test_to_benchmark_inputs_scenario_filter(self):
        retobs_queries, qrels = self.suite.to_benchmark_inputs(scenario_type_filter="alias")
        query_ids = {q.query_id for q in retobs_queries}
        assert "q3" in query_ids
        assert "q4" in query_ids
        assert "q1" not in query_ids

    def test_summary_structure(self):
        summary = self.suite.summary()
        assert summary["total_queries"] == 4
        assert summary["total_scenarios"] == 2
        assert summary["corpus_size"] == 4
        assert "by_difficulty" in summary
        assert "by_query_type" in summary
        assert "by_scenario_type" in summary

    def test_summary_counts(self):
        summary = self.suite.summary()
        assert summary["by_query_type"].get("paraphrase") == 2
        assert summary["by_query_type"].get("temporal") == 1
        assert summary["by_query_type"].get("adversarial") == 1
        assert summary["by_scenario_type"].get("temporal") == 1
        assert summary["by_scenario_type"].get("alias") == 1
