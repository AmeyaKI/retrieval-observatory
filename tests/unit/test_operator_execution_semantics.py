from __future__ import annotations

import pytest

from retrieval_observatory.config.operators import FilterSpec, PipelineGraphSpec, SourceSpec
from retrieval_observatory.pipeline.dag import DAGPipeline
from retrieval_observatory.pipeline.executors import OperatorConfigurationError
from retrieval_observatory.types import Document, Query, RetrievalResult


class _Source:
    def __init__(self, doc_id: str):
        self.doc_id = doc_id

    def retrieve(self, query: Query) -> RetrievalResult:
        return RetrievalResult([Document(self.doc_id, "", 1.0, 1)], 1.0, self.doc_id)


class _Filter:
    def __init__(self):
        self.received: list[str] = []

    def __call__(self, query: Query, documents: list[Document]):
        self.received = [item.id for item in documents]
        return documents[:1]


def _graph() -> PipelineGraphSpec:
    return PipelineGraphSpec(
        "multi",
        (
            SourceSpec("bm25", (), adapter="bm25"),
            SourceSpec("dense", (), adapter="dense"),
            FilterSpec("recent", ("bm25", "dense"), {"branch_id": "fresh"}, predicate="recent"),
        ),
        ("recent",),
    )


@pytest.mark.asyncio
async def test_filter_receives_all_declared_parent_groups() -> None:
    filter_ = _Filter()
    result = await DAGPipeline(
        _graph(), {"bm25": _Source("b1"), "dense": _Source("d1"), "recent": filter_}
    ).run(Query("policy", query_id="q"))
    assert filter_.received == ["b1", "d1"]
    assert tuple(result.trace.span("recent").input_groups) == ("bm25", "dense")
    dropped = result.trace.span("recent").input_groups["dense"][0]
    assert dropped.drop_reason == "filtered"
    assert dropped.decision_reason == "filtered"
    assert dropped.decision_evidence == "recorded"
    assert result.trace.span("recent").branch_id == "fresh"


def test_missing_filter_executor_fails_at_build_time() -> None:
    with pytest.raises(OperatorConfigurationError, match="No FILTER executor registered"):
        DAGPipeline(_graph(), {"bm25": _Source("b1"), "dense": _Source("d1")})
