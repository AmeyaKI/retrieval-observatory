from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from retrieval_observatory.forge.types import CorpusScenario, SyntheticDataset, SyntheticQuery
from retrieval_observatory.types import Query


class StressTestSuite:
    """Organizes a SyntheticDataset into queryable subsets for targeted evaluation.

    Use this to run your retrieval pipeline against only hard queries, or only
    temporal scenarios, and measure per-tier performance.
    """

    def __init__(self, dataset: SyntheticDataset):
        self.dataset = dataset
        self._scenario_map: Dict[str, CorpusScenario] = {
            s.scenario_id: s for s in dataset.scenarios
        }

    def get_by_difficulty(self, label: str) -> List[SyntheticQuery]:
        """Return queries matching a difficulty label (easy/medium/hard/extreme)."""
        return [q for q in self.dataset.queries if q.difficulty_label == label]

    def get_by_query_type(self, query_type: str) -> List[SyntheticQuery]:
        """Return queries of a given type (paraphrase/temporal/adversarial)."""
        return [q for q in self.dataset.queries if q.query_type == query_type]

    def get_by_scenario_type(self, scenario_type: str) -> List[SyntheticQuery]:
        """Return queries whose parent scenario is of the given type."""
        matching_ids: Set[str] = {
            s.scenario_id
            for s in self.dataset.scenarios
            if s.scenario_type == scenario_type
        }
        return [q for q in self.dataset.queries if q.scenario_id in matching_ids]

    def to_benchmark_inputs(
        self,
        difficulty_filter: Optional[str] = None,
        scenario_type_filter: Optional[str] = None,
        query_type_filter: Optional[str] = None,
    ) -> Tuple[List[Query], Dict[str, Dict[str, int]]]:
        """Convert to (queries, qrels) compatible with BenchmarkRunner.

        Args:
            difficulty_filter: If set, include only queries with this difficulty label.
            scenario_type_filter: If set, include only queries from this scenario type.
            query_type_filter: If set, include only queries of this query type.

        Returns:
            Tuple of (List[Query], qrels_dict) ready for BenchmarkRunner.run().
        """
        synthetic = list(self.dataset.queries)

        if difficulty_filter:
            synthetic = [q for q in synthetic if q.difficulty_label == difficulty_filter]
        if scenario_type_filter:
            matching = {
                s.scenario_id for s in self.dataset.scenarios
                if s.scenario_type == scenario_type_filter
            }
            synthetic = [q for q in synthetic if q.scenario_id in matching]
        if query_type_filter:
            synthetic = [q for q in synthetic if q.query_type == query_type_filter]

        retobs_queries = [Query(text=q.text, query_id=q.query_id) for q in synthetic]
        query_ids = {q.query_id for q in synthetic}
        qrels = {
            qid: grades
            for qid, grades in self.dataset.qrels.items()
            if qid in query_ids
        }
        return retobs_queries, qrels

    def summary(self) -> Dict[str, Any]:
        """Return a structured summary suitable for CLI display."""
        by_difficulty: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        by_scenario: Dict[str, int] = {}

        for q in self.dataset.queries:
            by_difficulty[q.difficulty_label] = by_difficulty.get(q.difficulty_label, 0) + 1
            by_type[q.query_type] = by_type.get(q.query_type, 0) + 1

        for s in self.dataset.scenarios:
            by_scenario[s.scenario_type] = by_scenario.get(s.scenario_type, 0) + 1

        return {
            "total_queries": len(self.dataset.queries),
            "total_scenarios": len(self.dataset.scenarios),
            "corpus_size": len(self.dataset.corpus),
            "by_difficulty": by_difficulty,
            "by_query_type": by_type,
            "by_scenario_type": by_scenario,
            "validated": sum(1 for q in self.dataset.queries if q.validated),
        }
