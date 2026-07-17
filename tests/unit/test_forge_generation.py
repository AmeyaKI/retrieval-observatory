"""Unit tests for Test Sets generation layer — mocked LLM, no API key needed."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from retrieval_observatory.forge.generation.generator import ForgeGenerator, _parse_lines
from retrieval_observatory.forge.types import CorpusScenario


def _make_scenario(scenario_type="temporal", anchor_ids=("d1", "d2")):
    return CorpusScenario(
        scenario_id="s_test",
        scenario_type=scenario_type,
        anchor_doc_ids=list(anchor_ids),
        evidence_summary="Test scenario",
        metadata={"year_a": 2010, "year_b": 2023},
    )


CORPUS = {
    "d1": {"text": "Apple launched iPhone in 2010 transforming the mobile market.", "title": "iPhone 2010"},
    "d2": {"text": "Apple introduced iPhone 15 in 2023 with advanced AI features.", "title": "iPhone 2023"},
}


class TestParseLines:
    def test_basic_parsing(self):
        raw = "What is the price?\nHow does it work?\nWho made this device?"
        result = _parse_lines(raw, 3)
        assert len(result) == 3
        assert result[0] == "What is the price?"

    def test_strips_numbering(self):
        raw = "1. First question here\n2. Second question here\n3. Third one"
        result = _parse_lines(raw, 3)
        assert not result[0].startswith("1.")

    def test_strips_bullets(self):
        raw = "- First item question\n* Second item question"
        result = _parse_lines(raw, 2)
        assert not result[0].startswith("-")

    def test_caps_at_n(self):
        raw = "Question one\nQuestion two\nQuestion three\nQuestion four"
        result = _parse_lines(raw, 2)
        assert len(result) == 2

    def test_filters_short_lines(self):
        raw = "ok\nThis is a real question about the topic"
        result = _parse_lines(raw, 2)
        assert len(result) == 1

    def test_empty_input(self):
        assert _parse_lines("", 3) == []


class TestForgeGenerator:
    def _make_mock_generator(self, responses=None):
        mock = MagicMock()
        responses = responses or ["Question one here\nQuestion two here\nQuestion three here"]
        mock.generate = AsyncMock(side_effect=responses * 10)
        return mock

    def test_from_provider_raises_on_unknown(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            ForgeGenerator.from_provider(provider="unknown_llm")

    def test_budget_tracking(self):
        mock_gen = self._make_mock_generator()
        gen = ForgeGenerator(mock_gen, budget=5)
        assert gen.budget_remaining == 5
        assert gen.calls_used == 0

    def test_budget_exhausted_raises(self):
        mock_gen = self._make_mock_generator()
        gen = ForgeGenerator(mock_gen, budget=0)
        with pytest.raises(RuntimeError, match="budget exhausted"):
            asyncio.run(gen._generate_queries("prompt", 3))

    def test_generate_paraphrase_queries(self):
        mock_gen = self._make_mock_generator([
            "What launched in 2010?\nHow did iPhone change mobile?\nWho made the first iPhone?"
        ])
        gen = ForgeGenerator(mock_gen, budget=10)
        scenario = _make_scenario("temporal")
        queries = asyncio.run(gen.generate_from_scenario(scenario, CORPUS, ["paraphrase"], n_per_type=3))
        assert len(queries) >= 1
        assert all(q.query_type == "paraphrase" for q in queries)
        assert all(q.scenario_id == "s_test" for q in queries)

    def test_generate_temporal_queries(self):
        mock_gen = self._make_mock_generator([
            "What features were added to iPhone in 2023?\nHow did iPhone change from 2010 to 2023?"
        ])
        gen = ForgeGenerator(mock_gen, budget=10)
        scenario = _make_scenario("temporal")
        queries = asyncio.run(gen.generate_from_scenario(scenario, CORPUS, ["temporal"], n_per_type=2))
        assert len(queries) >= 1
        assert all(q.query_type == "temporal" for q in queries)

    def test_temporal_skipped_if_not_temporal_scenario(self):
        mock_gen = self._make_mock_generator()
        gen = ForgeGenerator(mock_gen, budget=10)
        scenario = _make_scenario("alias", anchor_ids=["d1"])  # alias scenario, not temporal
        queries = asyncio.run(gen.generate_from_scenario(scenario, CORPUS, ["temporal"], n_per_type=2))
        # temporal query type skipped for alias scenario
        assert queries == []

    def test_query_ids_are_unique(self):
        mock_gen = self._make_mock_generator([
            "Question one thing\nQuestion two thing\nQuestion three thing"
        ] * 5)
        gen = ForgeGenerator(mock_gen, budget=10)
        scenario = _make_scenario("temporal")
        queries = asyncio.run(gen.generate_from_scenario(scenario, CORPUS, ["paraphrase"], n_per_type=3))
        ids = [q.query_id for q in queries]
        assert len(ids) == len(set(ids)), "Query IDs are not unique"

    def test_generate_dataset_multiple_scenarios(self):
        mock_gen = self._make_mock_generator([
            "First question for corpus\nSecond question for corpus"
        ] * 10)
        gen = ForgeGenerator(mock_gen, budget=20)
        scenarios = [_make_scenario("temporal"), _make_scenario("temporal", anchor_ids=("d1",))]
        queries = asyncio.run(gen.generate_dataset(scenarios, CORPUS, ["paraphrase"], n_per_type=2))
        assert len(queries) >= 2

    def test_llm_exception_does_not_abort(self):
        mock_gen = MagicMock()
        mock_gen.generate = AsyncMock(side_effect=Exception("API error"))
        gen = ForgeGenerator(mock_gen, budget=10)
        scenario = _make_scenario("temporal")
        # Should return empty list without raising
        queries = asyncio.run(gen.generate_from_scenario(scenario, CORPUS, ["paraphrase"], n_per_type=3))
        assert isinstance(queries, list)
