"""The hand-instrumented multi-module example (docs/guides/manual-instrumentation.md) persists one
trace per entrypoint call with cross-module parent edges, declared op types, and replay tiers."""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "integrations" / "manual_class_pipeline"
MODULES = ("pipeline", "retrievers", "fusion", "rerank")


def _load_pipeline(db_path: Path, monkeypatch):
    monkeypatch.setenv("RETOBS_DB", str(db_path))
    monkeypatch.syspath_prepend(str(EXAMPLE))
    for name in MODULES:
        sys.modules.pop(name, None)
    return importlib.import_module("pipeline")


async def _read_traces(db_path: Path):
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    return await store.list_traces(TraceQuery(service_id="manual_class_pipeline"))


def test_manual_class_pipeline_persists_one_wired_trace(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "traces.db"
    pipeline = _load_pipeline(db_path, monkeypatch)

    results = pipeline.SearchService().search("hybrid retrieval with reranking")
    assert len(results) == 5

    # The entrypoint is synchronous and no event loop is running, so the persist completed before return.
    traces = asyncio.run(_read_traces(db_path))
    assert len(traces) == 1
    trace = traces[0]
    assert trace.status == "OK"
    assert trace.pipeline_id == "keyword_dense_rrf_rerank"
    assert trace.query_text == "hybrid retrieval with reranking"

    spans = {span.op_id: span for span in trace.spans}
    assert [span.op_id for span in trace.spans] == ["keyword", "dense", "rrf", "rerank"]
    assert all(span.status == "FIRED" for span in trace.spans)
    assert all(span.outputs and all(candidate.doc_id for candidate in span.outputs) for span in trace.spans)

    assert spans["rrf"].parent_ids == ("keyword", "dense")
    assert spans["rerank"].parent_ids == ("rrf",)
    assert {op_id: span.op_type for op_id, span in spans.items()} == {
        "keyword": "SOURCE", "dense": "SOURCE", "rrf": "FUSE", "rerank": "RERANK",
    }
    assert {op_id: span.replay_policy for op_id, span in spans.items()} == {
        "keyword": "NOT_REPLAYABLE", "dense": "NOT_REPLAYABLE", "rrf": "EXACT", "rerank": "OBSERVED_ABLATION",
    }
    assert spans["rrf"].params == {"rrf_k": 60}
    assert set(spans["rrf"].input_groups) == {"keyword", "dense"}
    assert trace.final_op_ids == ("rerank",)
    assert [candidate.doc_id for candidate in spans["rerank"].outputs] == [hit["doc_id"] for hit in results]
