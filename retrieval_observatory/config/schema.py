from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator


class ExperimentMeta(BaseModel):
    name: str


class DatasetConfig(BaseModel):
    name: str  # e.g. "beir/nfcorpus" or "custom"
    split: str = "test"
    max_queries: Optional[int] = None
    temporal_field: Optional[str] = None
    # For custom datasets
    queries_path: Optional[str] = None
    corpus_path: Optional[str] = None


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
    retry_attempts: int = 2
    cache_results: bool = True


class OutputConfig(BaseModel):
    store: Literal["sqlite", "postgres"] = "sqlite"
    db_path: str = ".retobs/results.db"
    postgres_dsn: Optional[str] = None  # or set via RETOBS_POSTGRES_DSN env var
    export: List[Literal["json", "csv"]] = []
    dashboard: bool = False


class ExperimentConfig(BaseModel):
    experiment: ExperimentMeta
    dataset: DatasetConfig
    pipelines: List[PipelineConfig]
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "ExperimentConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
