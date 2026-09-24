"""Investigation evidence under failure: every case asserts a coded, observable result.

The golden investigation fixture seeds one run; each test breaks one thing (a stored payload, the
exporter, a capture mapping, the disk, a run id, the judgments, the projection write) and checks
the code, status or label that a caller sees.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import stat
from dataclasses import replace
from pathlib import Path

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.datasets.judgments import ChunkMap, EvaluationSpec, JudgmentSet
from retrieval_observatory.evidence import service
from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, observe, start_trace
from retrieval_observatory.store.base import InvestigationScope
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.capture import CaptureSpec
from retrieval_observatory.tracing.config import TelemetryConfig
from retrieval_observatory.tracing.model import RetrievalTrace
from retrieval_observatory.tracing.sink import BufferedTraceSink
from tests.fixtures.investigation_cases import run_fixture

RUN = "golden-run"
PIPELINE = "golden-hybrid"
QUERIES = ("q-invoice", "q-outage", "q-refund")
SENTINEL = "SENTINEL-DOC-TEXT-7f3a"


def _manifest(judgments: list[dict], chunk_map=None, pipeline_id: str = PIPELINE) -> dict:
    return {
        "normalized_config": {"metrics": {"recall_at_k": [3]}, "pipelines": [{"id": pipeline_id}]},
        "evaluation": {"k": 3},
        "counts": {"attempted": 3},
        "judgment_records": judgments,
        "chunk_map": chunk_map,
    }


async def _seed(path: Path) -> None:
    fixture = run_fixture()
    store = SQLiteStore(str(path))
    await store.init_db()
    await store.save_run(RUN, "golden", json.dumps({}))
    await store.save_run_manifest(RUN, _manifest(fixture.judgments, fixture.chunk_map))
    await store.save_traces([replace(trace, run_id=RUN) for trace in fixture.traces])
    await store.save_run_queries(RUN, fixture.queries, "golden")


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "golden.db"
    asyncio.run(_seed(path))
    return path


def _client(db_path: Path) -> tuple[TestClient, str]:
    registry = DbRegistry([str(db_path)])
    client = TestClient(create_app(registry=registry, enable_uploads=False), raise_server_exceptions=False)
    return client, f"/dbs/{registry.default_db_id}/investigation/runs"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _trace_json(db_path: Path, query_id: str) -> tuple[str, dict]:
    with sqlite3.connect(db_path) as db:
        trace_id, payload = db.execute("SELECT trace_id, trace_json FROM traces WHERE query_id = ?", (query_id,)).fetchone()
    return trace_id, json.loads(payload)


def _write_trace_json(db_path: Path, trace_id: str, payload: str) -> None:
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE traces SET trace_json = ? WHERE trace_id = ?", (payload, trace_id))


def _projection_rows(db_path: Path) -> int:
    with sqlite3.connect(db_path) as db:
        return db.execute("SELECT COUNT(*) FROM investigation_pairs").fetchone()[0]


# 1. Malformed or pre-capture trace ----------------------------------------------------------------

_SPAN_CAPTURE_FIELDS = ("input_capture", "output_capture", "parent_linkage", "invocation_id", "parent_invocation_ids", "source_ref")


def test_pre_capture_trace_without_capture_fields_projects_with_inferred_labels(db_path: Path) -> None:
    trace_id, payload = _trace_json(db_path, "q-invoice")
    for field in ("capture", "capture_failures", "lineage_schema_version"):
        payload.pop(field)
    for span in payload["spans"]:
        for field in _SPAN_CAPTURE_FIELDS:
            span.pop(field)
    _write_trace_json(db_path, trace_id, json.dumps(payload))
    client, base = _client(db_path)

    built = client.post(f"{base}/{RUN}/projection", json={})
    assert built.status_code == 200 and built.json()["status"] == "complete"
    listed = client.get(f"{base}/{RUN}/queries").json()
    assert listed["capabilities"]["projection"] == "ready"
    assert sorted(row["query_id"] for row in listed["rows"]) == list(QUERIES)
    older = client.get(f"{base}/{RUN}/queries/q-invoice").json()
    labels = {stage["op_id"]: stage["input_capture"] for stage in older["stages"]}
    parents = {span["op_id"]: span["parent_ids"] for span in payload["spans"]}
    # Inputs a pre-capture payload never recorded are reconstructed from parents and labelled so.
    assert {op_id: label for op_id, label in labels.items() if parents[op_id]} == {
        op_id: "inferred" for op_id in labels if parents[op_id]
    }
    assert {label for op_id, label in labels.items() if not parents[op_id]} == {"not_applicable"}
    assert older["rows"] and all(row["trace_id"] == trace_id for row in older["rows"])


def test_projection_built_before_a_trace_is_corrupted_is_still_served(db_path: Path) -> None:
    client, base = _client(db_path)
    assert client.post(f"{base}/{RUN}/projection", json={}).status_code == 200
    trace_id, _ = _trace_json(db_path, "q-outage")
    _write_trace_json(db_path, trace_id, "{not json")

    listed = client.get(f"{base}/{RUN}/queries").json()
    assert listed["capabilities"]["projection"] == "ready"
    assert sorted(row["query_id"] for row in listed["rows"]) == list(QUERIES)
    unaffected = client.get(f"{base}/{RUN}/queries/q-refund")
    assert unaffected.status_code == 200 and unaffected.json()["rows"]


def test_unreadable_trace_is_a_coded_422_naming_the_trace(db_path: Path) -> None:
    # Skipping the bad trace and projecting the rest is deferred; until then the failure is coded.
    trace_id, _ = _trace_json(db_path, "q-outage")
    _write_trace_json(db_path, trace_id, "{not json")
    client, base = _client(db_path)

    for response in (client.post(f"{base}/{RUN}/projection", json={}), client.get(f"{base}/{RUN}/queries/q-outage")):
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "trace_unreadable" and trace_id in detail["detail"]
    assert _projection_rows(db_path) == 0


# 2. Sink failure ---------------------------------------------------------------------------------


def test_exporter_failure_leaves_the_application_unaffected_and_nothing_persisted() -> None:
    fixture_trace = run_fixture().traces[0]

    class RaisingExporter:
        calls = 0

        async def export(self, batch) -> None:
            RaisingExporter.calls += 1
            raise ConnectionError("collector unavailable")

        async def close(self) -> None:
            return None

    async def scenario():
        sink = BufferedTraceSink(RaisingExporter(), TelemetryConfig(max_retries=1, retry_base_s=0), service_id="search")
        await sink.start()

        def handle(query: str) -> str:  # the application's request handler
            sink.offer(replace(fixture_trace, trace_id="exported-never", run_id=None))
            return f"answer to {query}"

        answer = handle("refund policy")
        await sink.flush(timeout_s=5)
        await sink.shutdown(timeout_s=1)
        return answer, sink.health()

    answer, health = asyncio.run(scenario())
    assert answer == "answer to refund policy"
    assert RaisingExporter.calls == 2  # the first attempt and one retry
    assert (health.accepted, health.exported, health.retries, health.permanent_failures) == (1, 0, 1, 1)
    assert health.last_export_at is None


# 3. Partial capture ------------------------------------------------------------------------------


def test_throwing_capture_mapping_keeps_the_result_and_marks_rows_partial(tmp_path: Path) -> None:
    @observe("SOURCE", op_id="retrieve")
    def retrieve(query: str) -> list[dict]:
        return [{"id": "d1", "score": 2.0}, {"id": "d2", "score": 1.0}, {"id": "d3", "score": 0.5}]

    @observe("RERANK", op_id="rerank", parent_ids=("retrieve",), capture=CaptureSpec(outputs=lambda result: [item["missing"] for item in result]))
    def rerank(query: str, candidates: list[dict]) -> list[dict]:
        return list(reversed(candidates))[:2]

    start_trace(ObserveContext("partial-run", "q1", "query", "app"))
    result = rerank("query", candidates=retrieve("query"))
    trace = finish_trace()
    assert [item["id"] for item in result] == ["d3", "d2"]
    assert [(f["op_id"], f["phase"], f["code"]) for f in trace.capture_failures] == [("rerank", "outputs", "output_mapping_failed")]

    async def project() -> dict:
        store = SQLiteStore(str(tmp_path / "partial.db"))
        await store.init_db()
        await store.save_run("partial-run", "partial", "{}")
        judgments = JudgmentSet.from_qrels({"q1": {"d1": 1, "d3": 1}})
        await store.save_run_manifest("partial-run", _manifest(judgments.to_records(), pipeline_id="app"))
        await store.save_traces([trace])
        await service.build_projection(store, "partial-run", "app", EvaluationSpec(k=2), judgments=judgments, chunk_map=None)
        return await service.inspect_query(store, service.InvestigationRequest(run_id="partial-run", query_id="q1", k=2))

    envelope = asyncio.run(project())
    stages = {stage["op_id"]: (stage["input_capture"], stage["output_capture"]) for stage in envelope["stages"]}
    assert stages == {"retrieve": ("not_applicable", "recorded"), "rerank": ("recorded", "unavailable")}
    rows = {row["entity_id"]: row for row in envelope["rows"]}
    assert set(rows) == {"d1", "d2", "d3"}
    for row in rows.values():  # the exit at rerank was never recorded: unknown, not a removal
        assert (row["capture_state"], row["final_membership"], row["outcome"], row["loss_boundary"]) == (
            "partial", "unknown", "insufficient_evidence", "unknown"
        )
    assert envelope["capabilities"]["capture"] == {"complete_rows": 0, "partial_rows": 3}


# 4. Disk-write failure ---------------------------------------------------------------------------


def test_failed_projection_write_is_coded_and_leaves_no_rows(db_path: Path, monkeypatch) -> None:
    client, base = _client(db_path)
    original = aiosqlite.Connection.executemany

    async def failing(self, sql, parameters):
        if "INTO investigation_pairs" in sql:
            raise sqlite3.OperationalError("disk I/O error")
        return await original(self, sql, parameters)

    monkeypatch.setattr(aiosqlite.Connection, "executemany", failing)
    response = client.post(f"{base}/{RUN}/projection", json={})

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "projection_write_failed", "detail": "projection not written: disk I/O error"}
    assert client.get(f"{base}/{RUN}/projection").json() == {"status": "unavailable"}
    assert _projection_rows(db_path) == 0


def test_read_only_database_file_is_a_coded_write_failure(db_path: Path) -> None:
    client, base = _client(db_path)
    assert client.get(f"{base}/{RUN}/queries").status_code == 200  # the registry store is initialised
    os.chmod(db_path, stat.S_IRUSR)
    try:
        if os.access(db_path, os.W_OK):
            pytest.skip("file permissions do not restrict this user (e.g. root)")
        response = client.post(f"{base}/{RUN}/projection", json={})
    finally:
        os.chmod(db_path, stat.S_IRUSR | stat.S_IWUSR)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "projection_write_failed"
    assert "readonly database" in response.json()["detail"]["detail"]
    assert _projection_rows(db_path) == 0


# 5. Missing candidate run ------------------------------------------------------------------------


def test_compare_against_a_missing_run_names_it(db_path: Path) -> None:
    client, base = _client(db_path)

    missing_baseline = client.get(f"{base}/{RUN}/compare", params={"against": "no-such-run"})
    assert missing_baseline.status_code == 404
    assert missing_baseline.json()["detail"] == {"code": "run_not_found", "detail": "run 'no-such-run' not found"}
    missing_candidate = client.get(f"{base}/no-such-run/compare", params={"against": RUN})
    assert missing_candidate.status_code == 404 and missing_candidate.json()["detail"]["code"] == "run_not_found"

    async def compare() -> service.InvestigationError:
        store = SQLiteStore(str(db_path))
        request = service.InvestigationRequest(run_id=RUN, comparison_run_id="no-such-run")
        with pytest.raises(service.InvestigationError) as caught:
            await service.compare_investigations(store, request)
        return caught.value

    error = asyncio.run(compare())
    assert (error.status, error.code) == (404, "run_not_found") and "no-such-run" in error.detail


# 6. Stale projection -----------------------------------------------------------------------------


def test_stale_projection_is_reported_with_a_repair_action_and_never_rewritten(db_path: Path) -> None:
    client, base = _client(db_path)
    assert client.post(f"{base}/{RUN}/projection", json={}).status_code == 200
    fixture = run_fixture()
    regraded = [{**record, "grade": 0} if index == 0 else record for index, record in enumerate(fixture.judgments)]
    asyncio.run(SQLiteStore(str(db_path)).save_run_manifest(RUN, _manifest(regraded, fixture.chunk_map)))
    client.get(f"{base}/{RUN}/projection")  # warm-up: first use may initialise the registry's store
    before = _digest(db_path)

    listed = client.get(f"{base}/{RUN}/queries").json()
    detail = client.get(f"{base}/{RUN}/queries/q-refund").json()

    for envelope in (listed, detail):
        assert envelope["capabilities"]["projection"] == "partial"
        stale = next(finding for finding in envelope["findings"] if finding["code"] == "projection_stale")
        assert stale["action"].endswith("`retobs storage index RUN`")
    assert _digest(db_path) == before


# 7. Interrupted backfill -------------------------------------------------------------------------


def test_interrupted_rebuild_rolls_back_and_the_previous_projection_is_served(db_path: Path, monkeypatch) -> None:
    fixture = run_fixture()
    judgments = JudgmentSet.from_records(fixture.judgments)
    chunks = ChunkMap.from_pairs([tuple(row) for row in fixture.chunk_map])
    spec = EvaluationSpec(k=3)
    store = SQLiteStore(str(db_path))
    first = asyncio.run(service.build_projection(store, RUN, PIPELINE, spec, judgments=judgments, chunk_map=chunks))
    assert first["status"] == "complete" and first["row_count"] > 0
    with sqlite3.connect(db_path) as db:
        pairs_before = db.execute("SELECT * FROM investigation_pairs ORDER BY 1, 2, 3, 4, 5, 6").fetchall()

    original = aiosqlite.Connection.executemany

    async def interrupted(self, sql, parameters):
        if "INTO investigation_summaries" in sql:  # the pair rows are already inserted
            raise sqlite3.OperationalError("database or disk is full")
        return await original(self, sql, parameters)

    monkeypatch.setattr(aiosqlite.Connection, "executemany", interrupted)
    # The interrupted rebuild would have written different rows (chunks left unmapped).
    with pytest.raises(service.InvestigationError) as caught:
        asyncio.run(service.build_projection(store, RUN, PIPELINE, spec, judgments=judgments, chunk_map=None))
    monkeypatch.undo()
    assert (caught.value.status, caught.value.code) == (409, "projection_write_failed")

    meta = asyncio.run(store.get_investigation_projection(InvestigationScope(RUN, PIPELINE, spec.digest())))
    assert (meta["status"], meta["row_count"], meta["started_at"]) == ("complete", first["row_count"], first["started_at"])
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT * FROM investigation_pairs ORDER BY 1, 2, 3, 4, 5, 6").fetchall() == pairs_before
    client, base = _client(db_path)
    listed = client.get(f"{base}/{RUN}/queries", params={"k": 3}).json()
    assert listed["capabilities"]["projection"] == "ready"
    assert listed["coverage"]["pairs"] == first["row_count"]


# 8. No content leakage ---------------------------------------------------------------------------


def test_document_text_never_reaches_failures_errors_or_logs(tmp_path: Path, caplog) -> None:
    documents = [{"id": "d1", "text": SENTINEL, "score": 1.0}, {"id": "d2", "text": "other", "score": 0.5}]

    @observe("SOURCE", op_id="retrieve")
    def retrieve(query: str) -> list[dict]:
        return [dict(document) for document in documents]

    @observe("RERANK", op_id="rerank", parent_ids=("retrieve",), capture=CaptureSpec(outputs=lambda result: [item["missing"] for item in result]))
    def rerank(query: str, candidates: list[dict]) -> list[dict]:
        return list(reversed(candidates))

    @observe("FILTER", op_id="filter", parent_ids=("rerank",))
    def keep_fresh(query: str, hits: list[dict]) -> list[dict]:
        raise RuntimeError("freshness backend unavailable")

    caplog.set_level(logging.DEBUG)
    start_trace(ObserveContext("leak-run", "q1", "query", "app"))
    reranked = rerank("query", candidates=retrieve("query"))
    with pytest.raises(RuntimeError):
        keep_fresh("query", hits=reranked)
    trace = finish_trace()

    assert [failure["code"] for failure in trace.capture_failures] == ["output_mapping_failed"]
    assert trace.span("filter").error == "RuntimeError: freshness backend unavailable"
    assert SENTINEL not in json.dumps(trace.capture_failures)
    assert SENTINEL not in json.dumps(trace.to_dict())  # nor in span params, which once copied candidate kwargs

    async def persist_and_inspect() -> dict:
        store = SQLiteStore(str(tmp_path / "leak.db"))
        await store.init_db()
        await store.save_run("leak-run", "leak", "{}")
        await store.save_run_manifest("leak-run", _manifest([], pipeline_id="app"))
        await store.save_traces([RetrievalTrace.from_dict(trace.to_dict())])
        return await service.inspect_query(store, service.InvestigationRequest(run_id="leak-run", query_id="q1"))

    envelope = asyncio.run(persist_and_inspect())
    assert envelope["stages"] and SENTINEL not in json.dumps(envelope)
    assert SENTINEL not in caplog.text
