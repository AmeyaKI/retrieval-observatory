from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from retrieval_observatory.types import Document, PipelineResult, StageSnapshot


@dataclass
class RetrievalTrace:
    """A single production retrieval request.

    Deliberately a near-superset of ``PipelineResult`` (it reuses ``StageSnapshot`` and
    ``Document`` verbatim) so the existing offline diagnostics run on traces unchanged.
    Production has no ground truth, so quality is never measured here — only label-free
    proxy ``suspected_failures`` are attached at ingest.
    """

    trace_id: str
    service: str
    query_id: str
    query_text: str
    pipeline_id: str
    snapshots: List[StageSnapshot]
    total_latency_ms: float
    status: Literal["OK", "TIMEOUT", "ERROR"] = "OK"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    final_results: List[Document] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Enrichment (populated server-side at ingest, not by the client):
    predicted_difficulty: Optional[str] = None
    suspected_failures: List[str] = field(default_factory=list)
    error_traceback: Optional[str] = None

    def as_pipeline_result(self) -> PipelineResult:
        """Bridge to the offline schema so metrics/diagnostics functions accept a trace."""
        return PipelineResult(
            query_id=self.query_id,
            pipeline_id=self.pipeline_id,
            snapshots=self.snapshots,
            total_latency_ms=self.total_latency_ms,
            status=self.status,
            error_traceback=self.error_traceback,
        )
