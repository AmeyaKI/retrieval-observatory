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
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    documents: List[Document]
    latency_ms: float
    retriever_id: str
    stage: int = 0
    raw_scores: Optional[List[float]] = None


@dataclass
class StageSnapshot:
    stage_index: int
    stage_id: str
    documents: List[Document]
    latency_ms: float


@dataclass
class PipelineResult:
    query_id: str
    pipeline_id: str
    snapshots: List[StageSnapshot]
    total_latency_ms: float
    status: Literal["OK", "TIMEOUT", "ERROR"]
    error_traceback: Optional[str] = None


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
