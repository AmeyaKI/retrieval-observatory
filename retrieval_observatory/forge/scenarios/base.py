from __future__ import annotations

from typing import Dict, List, runtime_checkable

from typing import Protocol

from retrieval_observatory.forge.types import CorpusScenario


@runtime_checkable
class ScenarioDetector(Protocol):
    scenario_type: str

    def detect(self, corpus: Dict[str, Dict]) -> List[CorpusScenario]:
        """Detect failure scenarios in the given corpus.

        Args:
            corpus: Mapping of doc_id -> {"text": ..., "title": ...}

        Returns:
            List of detected CorpusScenario objects.
        """
        ...
