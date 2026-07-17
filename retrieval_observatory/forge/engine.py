from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from retrieval_observatory.forge.datasets.exporter import export_dataset
from retrieval_observatory.forge.generation.generator import ForgeGenerator
from retrieval_observatory.forge.labels.difficulty import assign_difficulty_labels
from retrieval_observatory.forge.labels.ground_truth import (
    build_extractive_qrels,
    validate_qrels_with_llm,
)
from retrieval_observatory.forge.scenarios.registry import detect_all
from retrieval_observatory.forge.types import SyntheticDataset

_RULE_BASED_QUERY_TYPES = frozenset({"comparison", "constraint", "long_tail"})


class ForgeEngine:
    """End-to-end orchestrator for synthetic retrieval evaluation dataset generation.

    Usage:
        engine = ForgeEngine(corpus, generator=ForgeGenerator.from_provider("gemini"))
        dataset = await engine.run(query_types=["paraphrase", "temporal"], n_per_type=3)
        suite = StressTestSuite(dataset)
        queries, qrels = suite.to_benchmark_inputs(difficulty_filter="hard")
    """

    def __init__(
        self,
        corpus: Dict[str, Dict],
        generator: Optional[ForgeGenerator] = None,
        scenario_types: List[str] = ("temporal", "alias"),
        max_scenarios_per_type: int = 30,
        difficulty_model_path: Optional[str] = None,
        dataset_id: Optional[str] = None,
    ):
        self.corpus = corpus
        self.generator = generator
        self.scenario_types = list(scenario_types)
        self.max_scenarios_per_type = max_scenarios_per_type
        self.difficulty_model_path = difficulty_model_path
        self.dataset_id = dataset_id or f"forge_{uuid.uuid4().hex[:8]}"

    def scan(self) -> List:
        """Detect scenarios without generating queries. No LLM calls."""
        return detect_all(
            self.corpus,
            types=self.scenario_types,
            max_per_type=self.max_scenarios_per_type,
        )

    async def run(
        self,
        query_types: List[str] = ("paraphrase",),
        n_per_type: int = 3,
        validate: bool = False,
        judge=None,
        validation_budget: int = 500,
        output_dir: Optional[str] = None,
        output_format: str = "beir",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SyntheticDataset:
        """Run the full Test Sets pipeline.

        Args:
            query_types: Which query types to generate (paraphrase/temporal/adversarial).
            n_per_type: Queries generated per scenario per type.
            validate: Whether to expand qrels using LLM validation.
            judge: LLMJudge instance for validation (required if validate=True).
            validation_budget: Max LLM calls during the validation pass.
            output_dir: If set, export the dataset here after generation.
            output_format: "beir" or "custom".
            metadata: Extra metadata to embed in the dataset.

        Returns:
            SyntheticDataset ready for use with StressTestSuite and BenchmarkRunner.
        """
        if self.generator is None and query_types:
            llm_types = [t for t in query_types if t not in _RULE_BASED_QUERY_TYPES]
            if llm_types:
                raise RuntimeError(
                    "ForgeEngine requires a generator for LLM query types. "
                    "Pass generator=ForgeGenerator.from_provider('gemini') or use scan() instead."
                )

        # Step 1: Scenario discovery
        scenarios = self.scan()

        # Step 2: Query generation
        llm_types = [t for t in query_types if t not in _RULE_BASED_QUERY_TYPES]
        rule_types = [t for t in query_types if t in _RULE_BASED_QUERY_TYPES]
        queries = []
        if llm_types and self.generator:
            queries.extend(
                await self.generator.generate_dataset(
                    scenarios=scenarios,
                    corpus=self.corpus,
                    query_types=llm_types,
                    n_per_type=n_per_type,
                )
            )
        if rule_types:
            from retrieval_observatory.forge.generation.rule_based import generate_rule_based_queries

            for scenario in scenarios:
                queries.extend(
                    generate_rule_based_queries(scenario, self.corpus, rule_types, n_per_type)
                )

        # Step 3: Ground truth
        qrels = build_extractive_qrels(queries)

        # Step 4: Optional LLM validation
        if validate and judge and queries:
            qrels = await validate_qrels_with_llm(
                queries=queries,
                corpus=self.corpus,
                judge=judge,
                budget=validation_budget,
            )

        # Step 5: Difficulty scoring
        assign_difficulty_labels(queries, model_path=self.difficulty_model_path)

        # Step 6: Package
        dataset = SyntheticDataset(
            dataset_id=self.dataset_id,
            corpus=self.corpus,
            queries=queries,
            qrels=qrels,
            scenarios=scenarios,
            metadata={
                "scenario_types": self.scenario_types,
                "query_types": list(query_types),
                "n_per_type": n_per_type,
                "validated": validate,
                **(metadata or {}),
            },
            created_at=datetime.now(timezone.utc),
        )

        # Step 7: Export if requested
        if output_dir:
            export_dataset(dataset, output_dir, fmt=output_format)

        return dataset
