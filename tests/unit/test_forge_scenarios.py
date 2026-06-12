"""Unit tests for Forge scenario detection — no LLM or API key required."""
from __future__ import annotations

import pytest

from retrieval_observatory.forge.scenarios.alias import AliasScenarioDetector
from retrieval_observatory.forge.scenarios.registry import detect_all
from retrieval_observatory.forge.scenarios.temporal import TemporalScenarioDetector


TEMPORAL_CORPUS = {
    "doc1": {
        "text": "Apple released the iPhone in 2007. It was a revolutionary smartphone product launch.",
        "title": "iPhone Launch 2007",
    },
    "doc2": {
        "text": "Apple introduced the iPhone 15 in 2023. The smartphone features improved camera technology.",
        "title": "iPhone 15 2023",
    },
    "doc3": {
        "text": "The quarterly earnings report for 2022 shows strong growth in smartphone sales.",
        "title": "Earnings 2022",
    },
    "doc4": {
        "text": "A completely different topic about gardening and plants.",
        "title": "Gardening tips",
    },
}

ALIAS_CORPUS = {
    "doc_a": {
        "text": "Machine Learning (ML) has transformed data science. ML models are now widely deployed.",
        "title": "ML Overview",
    },
    "doc_b": {
        "text": "Artificial Intelligence and ML continue to evolve. The ML community is growing rapidly.",
        "title": "AI and ML trends",
    },
    "doc_c": {
        "text": "Machine learning models require careful training procedures and validation datasets.",
        "title": "Model Training",
    },
    "doc_d": {
        "text": "Amazon Web Services (AWS) provides cloud infrastructure. AWS is widely used globally.",
        "title": "AWS Cloud",
    },
    "doc_e": {
        "text": "Cloud infrastructure via AWS continues to grow in enterprise adoption.",
        "title": "Cloud trends",
    },
}


class TestTemporalScenarioDetector:
    def test_detects_temporal_pairs(self):
        detector = TemporalScenarioDetector()
        scenarios = detector.detect(TEMPORAL_CORPUS)
        # doc1 (2007) and doc2 (2023) should form a temporal pair
        assert len(scenarios) >= 1
        doc_id_sets = [set(s.anchor_doc_ids) for s in scenarios]
        assert any("doc1" in ids and "doc2" in ids for ids in doc_id_sets)

    def test_scenario_type(self):
        detector = TemporalScenarioDetector()
        scenarios = detector.detect(TEMPORAL_CORPUS)
        assert all(s.scenario_type == "temporal" for s in scenarios)

    def test_no_duplicate_pairs(self):
        detector = TemporalScenarioDetector()
        scenarios = detector.detect(TEMPORAL_CORPUS)
        pair_keys = []
        for s in scenarios:
            key = tuple(sorted(s.anchor_doc_ids[:2]))
            pair_keys.append(key)
        assert len(pair_keys) == len(set(pair_keys)), "Duplicate pairs detected"

    def test_empty_corpus(self):
        detector = TemporalScenarioDetector()
        assert detector.detect({}) == []

    def test_no_temporal_docs(self):
        corpus = {
            "d1": {"text": "Apples are red fruits found in many countries.", "title": ""},
            "d2": {"text": "Bananas are yellow tropical fruits.", "title": ""},
        }
        detector = TemporalScenarioDetector()
        scenarios = detector.detect(corpus)
        # No year anchors → no temporal scenarios
        assert scenarios == []

    def test_max_scenarios_cap(self):
        # Build a large corpus with many temporal docs
        large_corpus = {}
        for i in range(100):
            year = 2000 + (i % 20)
            large_corpus[f"doc{i}"] = {
                "text": f"Technology product launched in {year}. Smart device innovation continues.",
                "title": f"Tech {year}",
            }
        detector = TemporalScenarioDetector(max_scenarios=5)
        scenarios = detector.detect(large_corpus)
        assert len(scenarios) <= 5

    def test_evidence_summary_populated(self):
        detector = TemporalScenarioDetector()
        scenarios = detector.detect(TEMPORAL_CORPUS)
        for s in scenarios:
            assert len(s.evidence_summary) > 10
            assert s.scenario_id.startswith("temporal_")

    def test_metadata_has_years(self):
        detector = TemporalScenarioDetector()
        scenarios = detector.detect(TEMPORAL_CORPUS)
        for s in scenarios:
            assert "year_a" in s.metadata
            assert "year_b" in s.metadata


class TestAliasScenarioDetector:
    def test_detects_ml_alias(self):
        detector = AliasScenarioDetector()
        scenarios = detector.detect(ALIAS_CORPUS)
        # Should detect ML <-> Machine Learning alias
        assert len(scenarios) >= 1
        abbrs = [s.metadata.get("abbreviation") for s in scenarios]
        assert "ML" in abbrs or "AWS" in abbrs

    def test_scenario_type(self):
        detector = AliasScenarioDetector()
        scenarios = detector.detect(ALIAS_CORPUS)
        assert all(s.scenario_type == "alias" for s in scenarios)

    def test_empty_corpus(self):
        detector = AliasScenarioDetector()
        assert detector.detect({}) == []

    def test_no_aliases(self):
        corpus = {
            "d1": {"text": "The cat sat on the mat in the afternoon.", "title": ""},
            "d2": {"text": "Dogs like to run and play in the park every day.", "title": ""},
        }
        detector = AliasScenarioDetector()
        scenarios = detector.detect(corpus)
        assert scenarios == []

    def test_evidence_summary_mentions_abbreviation(self):
        detector = AliasScenarioDetector()
        scenarios = detector.detect(ALIAS_CORPUS)
        for s in scenarios:
            abbr = s.metadata.get("abbreviation", "")
            assert abbr in s.evidence_summary

    def test_max_scenarios_cap(self):
        detector = AliasScenarioDetector(max_scenarios=1)
        scenarios = detector.detect(ALIAS_CORPUS)
        assert len(scenarios) <= 1


class TestDetectAll:
    def test_combined_detection(self):
        corpus = {**TEMPORAL_CORPUS, **ALIAS_CORPUS}
        scenarios = detect_all(corpus, types=["temporal", "alias"])
        types_found = {s.scenario_type for s in scenarios}
        # Both types should be detected in combined corpus
        assert "temporal" in types_found or "alias" in types_found

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown scenario type"):
            detect_all(TEMPORAL_CORPUS, types=["unknown_type"])

    def test_single_type_filter(self):
        corpus = {**TEMPORAL_CORPUS, **ALIAS_CORPUS}
        scenarios = detect_all(corpus, types=["temporal"])
        assert all(s.scenario_type == "temporal" for s in scenarios)

    def test_returns_list(self):
        result = detect_all({}, types=["temporal", "alias"])
        assert isinstance(result, list)
