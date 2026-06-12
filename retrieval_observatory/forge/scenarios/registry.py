from __future__ import annotations

from typing import Dict, List, Literal

from retrieval_observatory.forge.scenarios.alias import AliasScenarioDetector
from retrieval_observatory.forge.scenarios.temporal import TemporalScenarioDetector
from retrieval_observatory.forge.types import CorpusScenario

ScenarioType = Literal["temporal", "alias"]

_DETECTORS = {
    "temporal": TemporalScenarioDetector,
    "alias": AliasScenarioDetector,
}


def detect_all(
    corpus: Dict[str, Dict],
    types: List[ScenarioType] = ("temporal", "alias"),
    max_per_type: int = 30,
) -> List[CorpusScenario]:
    """Run all requested scenario detectors over the corpus.

    Args:
        corpus: Mapping of doc_id -> {"text": ..., "title": ...}
        types: Which scenario types to detect.
        max_per_type: Maximum scenarios returned per detector type.

    Returns:
        Combined list of detected CorpusScenario objects.
    """
    scenarios: List[CorpusScenario] = []
    for scenario_type in types:
        cls = _DETECTORS.get(scenario_type)
        if cls is None:
            raise ValueError(f"Unknown scenario type: {scenario_type!r}. Choose from {list(_DETECTORS)}")
        detector = cls(max_scenarios=max_per_type)
        found = detector.detect(corpus)
        scenarios.extend(found)
    return scenarios
