"""`retobs inspect-query` shows each trace's recorded wall-clock time, not 0.0 ms."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from typer.testing import CliRunner

from retrieval_observatory.cli import _trace_wall_latency_ms
from retrieval_observatory.cli import app as cli_app
from retrieval_observatory.evidence.query import build_query_evidence
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming

RUN_ID = "latency-run"
QUERY_ID = "q-latency"


def _trace(trace_id: str, pipeline_id: str, wall_clock_ms: float) -> RetrievalTrace:
    span = OperatorSpan(
        op_id="lookup", op_type="SOURCE", op_name="lookup", parent_ids=[],
        status="FIRED", deterministic=True, replay_policy="EXACT", latency_ms=0.03,
        outputs=[Candidate(doc_id="doc-a", score=1.0, rank=1, origin_op_ids=["lookup"])],
    )
    return RetrievalTrace(
        service_id="svc", trace_id=trace_id, run_id=RUN_ID, query_id=QUERY_ID, query_text="where is it",
        pipeline_id=pipeline_id, spans=[span], final_op_ids=("lookup",),
        timing=TraceTiming(wall_clock_ms, wall_clock_ms, 0.03),
    )


async def _seed(db_path: Path) -> None:
    store = SQLiteStore(str(db_path))
    await store.init_db()
    await store.save_run(RUN_ID, "latency", json.dumps({}))
    await store.save_traces([_trace("t-slow", "pipe-slow", 45.3), _trace("t-fast", "pipe-fast", 0.04)])


def test_inspect_query_shows_recorded_wall_clock(tmp_path: Path) -> None:
    db_path = tmp_path / "latency.db"
    asyncio.run(_seed(db_path))

    async def _evidence() -> dict:
        return await build_query_evidence(SQLiteStore(str(db_path)), db_id="latency", run_id=RUN_ID, query_id=QUERY_ID)

    walls = {t["pipeline_id"]: t["timing"]["wall_clock_ms"] for t in asyncio.run(_evidence())["traces"]}
    assert walls == {"pipe-slow": 45.3, "pipe-fast": 0.04}

    result = CliRunner().invoke(cli_app, ["inspect-query", RUN_ID, QUERY_ID, "--db", str(db_path)], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "45.3 ms" in result.output
    assert "<0.1 ms" in result.output
    assert "0.0 ms" not in result.output


def test_wall_latency_reads_legacy_total_latency_ms() -> None:
    assert _trace_wall_latency_ms({"total_latency_ms": 12.5}) == 12.5
    assert _trace_wall_latency_ms({"timing": {"wall_clock_ms": 0.0}, "total_latency_ms": 9.0}) == 0.0
