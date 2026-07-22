from datetime import datetime, timezone

import pytest

from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import OperatorSpan, RetrievalTrace


def _trace(trace_id: str, run_id: str, query_id: str) -> RetrievalTrace:
    return RetrievalTrace(
        trace_id=trace_id,
        service_id="search",
        run_id=run_id,
        query_id=query_id,
        query_text="query",
        pipeline_id="hybrid",
        spans=(OperatorSpan.source("source", "Source", ()),),
        final_op_ids=("source",),
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_list_traces_filters_run_and_query_id(tmp_path):
    store = SQLiteStore(str(tmp_path / "results.db"))
    await store.save_traces(
        [
            _trace("a-1", "run-a", "q-1"),
            _trace("a-2", "run-a", "q-2"),
            _trace("b-1", "run-b", "q-1"),
        ]
    )

    rows = await store.list_traces(TraceQuery(run_id="run-a", query_id="q-1"))

    assert [(row.run_id, row.query_id) for row in rows] == [("run-a", "q-1")]


@pytest.mark.asyncio
async def test_list_traces_without_query_id_preserves_run_scope(tmp_path):
    store = SQLiteStore(str(tmp_path / "results.db"))
    await store.save_traces(
        [
            _trace("a-1", "run-a", "q-1"),
            _trace("a-2", "run-a", "q-2"),
            _trace("b-1", "run-b", "q-1"),
        ]
    )

    rows = await store.list_traces(TraceQuery(run_id="run-a"))

    assert {row.query_id for row in rows} == {"q-1", "q-2"}
