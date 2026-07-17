"""Test Sets: Synthetic Retrieval Evaluation Dataset Generation.

Test Sets addresses benchmark blindness — the gap between what static datasets test
and what production retrieval systems actually encounter. It scans your corpus for
structural failure patterns (temporal confusion, alias mismatches), generates targeted
hard queries using an LLM, builds extractive ground truth, and packages everything as
a BEIR-compatible stress-test evaluation suite.

Quick start:
    from retrieval_observatory.forge import ForgeEngine, StressTestSuite
    from retrieval_observatory.forge.generation import ForgeGenerator

    corpus = {"doc1": {"text": "...", "title": "..."}, ...}
    engine = ForgeEngine(
        corpus,
        generator=ForgeGenerator.from_provider("gemini"),
    )
    dataset = await engine.run(query_types=["paraphrase", "temporal"], n_per_type=3)
    suite = StressTestSuite(dataset)
    queries, qrels = suite.to_benchmark_inputs()
"""

from retrieval_observatory.forge.engine import ForgeEngine
from retrieval_observatory.forge.generation.generator import ForgeGenerator
from retrieval_observatory.forge.scenarios.registry import detect_all
from retrieval_observatory.forge.stress.suite import StressTestSuite
from retrieval_observatory.forge.types import (
    CorpusScenario,
    SyntheticDataset,
    SyntheticQuery,
)

__all__ = [
    "ForgeEngine",
    "ForgeGenerator",
    "StressTestSuite",
    "detect_all",
    "CorpusScenario",
    "SyntheticQuery",
    "SyntheticDataset",
]
