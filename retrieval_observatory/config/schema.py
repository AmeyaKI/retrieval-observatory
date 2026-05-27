from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator


class ExperimentMeta(BaseModel):
    name: str


class DatasetConfig(BaseModel):
    type: Optional[Literal["beir", "custom"]] = None
    name: str  # e.g. "beir/nfcorpus" or "custom"
    split: str = "test"
    max_queries: Optional[int] = None
    temporal_field: Optional[str] = None
    timestamp_field: Optional[str] = None
    metadata_fields: List[str] = Field(default_factory=list)
    format: Literal["jsonl", "beir"] = "jsonl"
    # For custom datasets
    queries_path: Optional[str] = None
    corpus_path: Optional[str] = None
    qrels_path: Optional[str] = None


class StageConfig(BaseModel):
    type: str  # e.g. "adapter.http", "adapter.langchain"
    url: Optional[str] = None
    retriever_id: Optional[str] = None
    model: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def set_default_retriever_id(self) -> "StageConfig":
        if self.retriever_id is None:
            self.retriever_id = self.url or self.type
        return self


class PipelineConfig(BaseModel):
    id: str
    stages: List[StageConfig]


class CombinationConfig(BaseModel):
    include: List[List[str]] = Field(default_factory=list)


class LabelsConfig(BaseModel):
    mode: Literal["gold", "llm_judge", "pooled_llm_judge"] = "gold"
    judge: Optional[str] = None
    model: Optional[str] = None
    cache_path: str = ".retobs/llm_judge_cache.db"


class MetricsConfig(BaseModel):
    recall_at_k: List[int] = [1, 5, 10]
    mrr: bool = True
    ndcg_at_k: List[int] = [10]
    map: bool = True
    temporal_recall_at_k: List[int] = []
    latency_percentiles: List[int] = [50, 95, 99]


class ExecutionConfig(BaseModel):
    concurrency: int = 8
    timeout_ms: int = 5000
    timeout_seconds: Optional[int] = None  # human-friendly alias; converts to timeout_ms
    retry_attempts: int = 2
    cache_results: bool = True

    @model_validator(mode="after")
    def _apply_timeout_seconds(self) -> "ExecutionConfig":
        if self.timeout_seconds is not None:
            self.timeout_ms = self.timeout_seconds * 1000
        return self


class OutputConfig(BaseModel):
    store: Literal["sqlite", "postgres"] = "sqlite"
    db_path: str = ".retobs/results.db"
    postgres_dsn: Optional[str] = None  # or set via RETOBS_POSTGRES_DSN env var
    export: List[Literal["json", "csv"]] = []
    dashboard: bool = False


class ExperimentConfig(BaseModel):
    experiment: ExperimentMeta
    dataset: DatasetConfig
    pipelines: List[PipelineConfig] = Field(default_factory=list)
    stages: Dict[str, StageConfig] = Field(default_factory=dict)
    combinations: Optional[CombinationConfig] = None
    labels: LabelsConfig = Field(default_factory=LabelsConfig)
    profiling: bool = True
    costs: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @model_validator(mode="after")
    def expand_combinations(self) -> "ExperimentConfig":
        if self.combinations and self.combinations.include:
            if not self.stages:
                raise ValueError("combinations requires a top-level stages mapping")
            expanded = []
            for combo in self.combinations.include:
                missing = [stage_id for stage_id in combo if stage_id not in self.stages]
                if missing:
                    raise ValueError(f"Unknown stage id(s) in combinations: {missing}")
                expanded.append(
                    PipelineConfig(
                        id="__".join(combo),
                        stages=[self.stages[stage_id].model_copy(deep=True) for stage_id in combo],
                    )
                )
            self.pipelines = [*self.pipelines, *expanded]
        if not self.pipelines:
            raise ValueError("At least one pipeline or combination is required")
        return self

    @classmethod
    def from_yaml(cls, path: str) -> "ExperimentConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
