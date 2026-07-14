from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass
class RegressionFinding:
    metric: str
    before: float
    after: float
    delta: float
    q_value: float
    severity: Literal["high", "medium", "low"]
    n_pairs: int
    p_value: Optional[float] = None
    effect_threshold: Optional[float] = None
    decision: str = "candidate_worse"


EffortLevel = Literal["S", "M", "L"]


@dataclass
class Recommendation:
    action: str
    rationale: str
    evidence: List[str]
    priority: int
    # --- Advisor Evolution (Pillar 5): make each recommendation a planning input. ---
    # All optional: when a value cannot be estimated it stays None and the UI renders
    # "not estimated" rather than a fabricated number (Trust principle).
    estimated_quality_improvement: Optional[float] = None  # delta in `quality_metric` units
    quality_metric: Optional[str] = None  # e.g. "recall@10"
    estimated_quality_ci: Optional[List[float]] = None  # [low, high]
    estimated_latency_increase_ms: Optional[float] = None
    implementation_effort: Optional[EffortLevel] = None
    confidence: Optional[float] = None  # 0..1
    affected_query_categories: List[str] = field(default_factory=list)
    expected_value: Optional[float] = None  # ranking score; higher = act first

    def compute_expected_value(self) -> Optional[float]:
        """Expected engineering value: quality gain weighted by confidence, penalized
        by latency cost and implementation effort. Returns None when unestimable so
        unestimated recommendations sort into an explicit tail rather than pretending
        to rank."""
        if self.estimated_quality_improvement is None:
            return None
        conf = self.confidence if self.confidence is not None else 0.5
        value = self.estimated_quality_improvement * conf
        if self.estimated_latency_increase_ms:
            value -= (self.estimated_latency_increase_ms / 100.0) * 0.01
        effort_factor = {"S": 1.0, "M": 0.8, "L": 0.6}.get(self.implementation_effort or "M", 0.8)
        value *= effort_factor
        return value


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
