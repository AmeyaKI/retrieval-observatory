from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal


@dataclass
class RegressionFinding:
    metric: str
    before: float
    after: float
    delta: float
    q_value: float
    severity: Literal["high", "medium", "low"]
    n_pairs: int


@dataclass
class Recommendation:
    action: str
    rationale: str
    evidence: List[str]
    priority: int


@dataclass
class GoldenResult:
    set_name: str
    run_id: str
    prior_run_id: str | None
    regressions: List[RegressionFinding]


@dataclass
class ReliabilityScore:
    value: float
    components: Dict[str, float]
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "components": self.components,
            "notes": self.notes,
        }
