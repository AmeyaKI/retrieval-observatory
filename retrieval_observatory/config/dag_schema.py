"""Declarative DAG config schema for complex RAG pipelines.

Allows users to define operator DAGs declaratively (YAML/JSON) for simulation
and benchmark execution. This is the mid-term goal from Phase 8 — the near-term
path remains ``@observe`` and remote ingest for production pipelines.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


OperatorTypeLiteral = Literal[
    "SOURCE", "FUSE", "RERANK", "BOOST", "EXPAND",
    "FILTER", "GATE", "TRANSFORM",
]


class GateCondition(BaseModel):
    """Condition under which a gate fires (all conditions are ANDed)."""
    field: str
    operator: Literal["eq", "neq", "in", "not_in", "gt", "lt", "gte", "lte"] = "eq"
    value: Any = None


class OperatorConfig(BaseModel):
    """A single operator node in the DAG."""
    op_id: str
    op_type: OperatorTypeLiteral
    op_name: Optional[str] = None
    parent_ids: List[str] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)

    adapter_type: Optional[str] = None
    adapter_config: Dict[str, Any] = Field(default_factory=dict)

    gate_conditions: List[GateCondition] = Field(default_factory=list)
    deterministic: bool = True
    replay_policy: Literal["EXACT", "OBSERVED_ABLATION", "NOT_REPLAYABLE"] = "EXACT"
    fallback_op_id: Optional[str] = None
    cap: Optional[int] = None

    @model_validator(mode="after")
    def _set_defaults(self) -> "OperatorConfig":
        if self.op_name is None:
            self.op_name = self.op_id
        return self


class DagPipelineConfig(BaseModel):
    """Declarative DAG pipeline definition."""
    pipeline_id: str
    operators: List[OperatorConfig]
    final_op_id: Optional[str] = None

    @model_validator(mode="after")
    def _validate_dag(self) -> "DagPipelineConfig":
        op_ids = {op.op_id for op in self.operators}
        for op in self.operators:
            for pid in op.parent_ids:
                if pid not in op_ids:
                    raise ValueError(
                        f"Operator '{op.op_id}' references unknown parent '{pid}'"
                    )
        if self.final_op_id and self.final_op_id not in op_ids:
            raise ValueError(f"final_op_id '{self.final_op_id}' not in operators")
        if self.final_op_id is None and self.operators:
            all_parent_ids = {pid for op in self.operators for pid in op.parent_ids}
            sinks = [op.op_id for op in self.operators if op.op_id not in all_parent_ids]
            if len(sinks) == 1:
                self.final_op_id = sinks[0]
        return self


class DagExperimentConfig(BaseModel):
    """Top-level config for a DAG-based experiment."""
    experiment_name: str
    dataset_name: str
    pipelines: List[DagPipelineConfig]
    metrics: Dict[str, Any] = Field(default_factory=lambda: {
        "recall_at_k": [10, 100],
        "ndcg_at_k": [10],
    })
