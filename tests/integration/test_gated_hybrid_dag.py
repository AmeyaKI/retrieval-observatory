from __future__ import annotations

import pytest

from retrieval_observatory.config.operators import FilterSpec, GateSpec, PipelineGraphSpec, RerankSpec, SourceSpec
from retrieval_observatory.pipeline.dag import DAGPipeline
from retrieval_observatory.types import Document, RetrievalResult


class _Source:
    def retrieve(self, query):
        return RetrievalResult([Document("old", "", 1.0, 1), Document("new", "", .9, 2)], 1.0, "source")


def _route(query, documents):
    return "temporal" if "after" in query.text else "generic"


def _filter(query, documents):
    return [doc for doc in documents if doc.id == "new"]


def _rerank(query, documents):
    return RetrievalResult(list(reversed(documents)), 1.0, "rerank")


def _pipeline():
    graph = PipelineGraphSpec(
        "gated",
        (
            SourceSpec("source", (), adapter="source"),
            GateSpec("intent_gate", ("source",), router="route",
                     branches={"temporal": ("temporal_filter",), "generic": ("generic_reranker",)}),
            FilterSpec("temporal_filter", ("intent_gate",), predicate="filter"),
            RerankSpec("generic_reranker", ("intent_gate",), adapter="rerank"),
        ),
        ("temporal_filter", "generic_reranker"),
    )
    return DAGPipeline(graph, {"source": _Source(), "route": _route, "filter": _filter, "rerank": _rerank})


@pytest.mark.asyncio
async def test_temporal_route_records_selected_and_skipped_branches() -> None:
    trace = (await _pipeline().run("policy changes after 2025", query_id="q-temporal")).trace
    assert trace.span("intent_gate").gate_values["selected_route"] == "temporal"
    assert trace.span("temporal_filter").status == "FIRED"
    assert trace.span("generic_reranker").status == "SKIPPED_BY_GATE"
    assert trace.span("generic_reranker").parent_ids == ("intent_gate",)
    assert trace.span("temporal_filter").input_groups["intent_gate"][0].drop_reason == "filtered"


@pytest.mark.asyncio
async def test_representative_queries_cover_every_branch() -> None:
    temporal = (await _pipeline().run("after 2025", query_id="temporal")).trace
    generic = (await _pipeline().run("ordinary", query_id="generic")).trace
    assert temporal.span("generic_reranker").status == "SKIPPED_BY_GATE"
    assert generic.span("temporal_filter").status == "SKIPPED_BY_GATE"
    assert generic.final_op_ids == ("generic_reranker",)
