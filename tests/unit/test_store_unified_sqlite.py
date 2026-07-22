from datetime import datetime, timezone
import sqlite3

import pytest

from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import OperatorSpan, RetrievalTrace


def _trace(trace_id: str, *, run_id: str | None = None) -> RetrievalTrace:
    return RetrievalTrace(
        trace_id=trace_id,
        service_id="search",
        run_id=run_id,
        query_id="q1",
        query_text="hello",
        pipeline_id="hybrid",
        spans=(OperatorSpan.source("source", "Source", ()),),
        final_op_ids=("source",),
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_production_and_evaluation_traces_share_one_query_api(tmp_path) -> None:
    store = SQLiteStore(str(tmp_path / "results.db"))
    production = _trace("production")
    evaluation = _trace("evaluation", run_id="run-1")
    await store.save_traces([production, evaluation])

    assert [trace.trace_id for trace in await store.list_traces(TraceQuery(service_id="search"))] == [
        "evaluation", "production"
    ]
    assert [trace.trace_id for trace in await store.list_traces(TraceQuery(run_id="run-1"))] == ["evaluation"]
    assert (await store.get_trace("production")).run_id is None
    assert (await store.list_services())[0].service_id == "search"


@pytest.mark.asyncio
async def test_existing_database_gets_run_query_trace_index(tmp_path) -> None:
    db_path = tmp_path / "results.db"
    store = SQLiteStore(str(db_path))
    await store.init_db()
    with sqlite3.connect(db_path) as db:
        db.execute("DROP INDEX idx_traces_run_query")
        db.commit()

    await SQLiteStore(str(db_path)).init_db()

    with sqlite3.connect(db_path) as db:
        columns = [row[2] for row in db.execute("PRAGMA index_info(idx_traces_run_query)")]
    assert columns == ["run_id", "query_id"]
