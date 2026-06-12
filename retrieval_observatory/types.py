from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, runtime_checkable

from typing import Protocol


@dataclass
class Query:
    text: str
    k: int = 10
    query_id: str = ""
    temporal_anchor: Optional[datetime] = None
    filters: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    id: str
    text: str
    score: float
    rank: int  # 1-indexed
    title: str = ""
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    documents: List[Document]
    latency_ms: float
    retriever_id: str
    stage: int = 0
    raw_scores: Optional[List[float]] = None
    profiling: Dict[str, float] = field(default_factory=dict)


@dataclass
class StageSnapshot:
    stage_index: int
    stage_id: str
    documents: List[Document]
    latency_ms: float
    profiling: Dict[str, float] = field(default_factory=dict)
    candidate_count: int = 0


@dataclass
class PipelineResult:
    query_id: str
    pipeline_id: str
    snapshots: List[StageSnapshot]
    total_latency_ms: float
    status: Literal["OK", "TIMEOUT", "ERROR"]
    error_traceback: Optional[str] = None


@dataclass
class CandidateLineage:
    """Per-stage tracking of candidate document flow through a pipeline."""
    stage_index: int
    stage_id: str
    entered: List[str]    # doc IDs first appearing at this stage
    survived: List[str]   # doc IDs carried forward from the previous stage
    dropped: List[str]    # doc IDs present in previous stage but absent here
    churn_rate: float     # fraction of previous candidates that were dropped


@runtime_checkable
class BaseRetriever(Protocol):
    retriever_id: str

    def retrieve(self, query: Query) -> RetrievalResult:
        ...


@runtime_checkable
class BaseReranker(Protocol):
    retriever_id: str

    def rerank(self, query: Query, documents: List[Document]) -> RetrievalResult:
        ...
