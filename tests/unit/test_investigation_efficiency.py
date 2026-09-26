"""Projection and read-path efficiency fixes keep every output identical.

Digests are computed once per trace/projection; filtered summaries come from one store read yet
equal the old page-by-page computation (values and key order); pipeline resolution never loads
traces; the ordered filter indexes reach v3 files through ``migrate_database``; an undecodable
stored trace raises ``TraceDecodeError`` naming it, from both backends.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import get_args

import pytest

from retrieval_observatory.datasets.judgments import EvaluationSpec, JudgmentSet
from retrieval_observatory.evidence import journeys, service
from retrieval_observatory.evidence.investigation import CaptureState, JudgmentState, Membership, Outcome
from retrieval_observatory.store.base import InvestigationFilter, InvestigationScope, TraceDecodeError, TraceQuery
from retrieval_observatory.store.migrate import migrate_database, reset_database
from retrieval_observatory.store.postgres import PostgresStore
from retrieval_observatory.store.sqlite import SQLiteStore
from tests.fixtures.investigation_cases import run_fixture

RUN = "golden-run"
PIPELINE = "golden-hybrid"
ORDER_INDEXES = ["idx_investigation_pairs_entity_order", "idx_investigation_pairs_outcome_order"]
SENTINEL = "SENTINEL-TEXT-4c1d"


def _manifest(fixture, *, listed: bool = True) -> dict:
    manifest = {"evaluation": {"k": 3}, "judgment_records": fixture.judgments, "chunk_map": fixture.chunk_map}
    if listed:
        manifest["normalized_config"] = {"metrics": {"recall_at_k": [3]}, "pipelines": [{"id": PIPELINE}]}
    return manifest


async def _seed(path: Path, *, listed: bool = True) -> SQLiteStore:
    fixture = run_fixture()
    store = SQLiteStore(str(path))
    await store.init_db()
    await store.save_run(RUN, "golden", "{}")
    await store.save_run_manifest(RUN, _manifest(fixture, listed=listed))
    await store.save_traces(list(fixture.traces))
    await store.save_run_queries(RUN, fixture.queries, "golden")
    return store


async def _index(store: SQLiteStore) -> service.ResolvedScope:
    resolved = await service.resolve_scope(store, service.InvestigationRequest.from_mapping({"run_id": RUN}))
    await service.build_projection(store, RUN, resolved.pipeline_id, resolved.spec, judgments=resolved.judgments, chunk_map=resolved.chunk_map)
    return resolved


async def test_projection_hashes_each_trace_once_and_the_spec_and_judgments_once(tmp_path: Path, monkeypatch) -> None:
    store = await _seed(tmp_path / "golden.db")
    resolved = await service.resolve_scope(store, service.InvestigationRequest.from_mapping({"run_id": RUN}))
    calls: dict[str, list] = {"trace": [], "spec": [], "judgments": []}
    trace_digest, spec_digest, judgment_digest = journeys.trace_digest, EvaluationSpec.digest, JudgmentSet.digest
    monkeypatch.setattr(journeys, "trace_digest", lambda trace: calls["trace"].append(trace.trace_id) or trace_digest(trace))
    monkeypatch.setattr(EvaluationSpec, "digest", lambda self: calls["spec"].append(1) or spec_digest(self))
    monkeypatch.setattr(JudgmentSet, "digest", lambda self: calls["judgments"].append(1) or judgment_digest(self))

    meta = await service.build_projection(store, RUN, PIPELINE, resolved.spec, judgments=resolved.judgments, chunk_map=resolved.chunk_map)

    traces = await store.list_traces(TraceQuery(run_id=RUN))
    assert meta["row_count"] > len(traces) > 1
    assert sorted(calls["trace"]) == sorted(trace.trace_id for trace in traces)  # once per trace, not per row
    assert calls["spec"] == [1] and calls["judgments"] == [1]


def _filters() -> list[InvestigationFilter]:
    fixture = run_fixture()
    values = [
        *(InvestigationFilter(outcome=value) for value in get_args(Outcome)),
        *(InvestigationFilter(judgment=value) for value in get_args(JudgmentState)),
        *(InvestigationFilter(capture_state=value) for value in get_args(CaptureState)),
        *(InvestigationFilter(final_membership=value) for value in get_args(Membership)),
        *(InvestigationFilter(query_id=query.query_id) for query in fixture.queries),
        *(InvestigationFilter(query_id=query.query_id, outcome="relevant_excluded") for query in fixture.queries),
        InvestigationFilter(loss_boundary="recency_filter"),
        InvestigationFilter(),
    ]
    entities = {(record["namespace"], record["entity_id"]) for record in fixture.judgments}
    values += [InvestigationFilter(namespace=namespace, entity_id=entity_id) for namespace, entity_id in sorted(entities)]
    return values


async def test_filtered_summary_from_one_read_equals_the_paged_summary(tmp_path: Path) -> None:
    store = await _seed(tmp_path / "golden.db")
    scope = (await _index(store)).store_scope()
    nonempty = 0
    for filters in _filters():
        for order in ("priority", "entity"):
            paged = service._summarize(await service._all_rows(store, scope, filters, order))
            single = await service._summarize_matching(store, scope, filters, order)
            assert single == paged and list(single.items()) == list(paged.items()), (filters, order)
            nonempty += bool(paged["pairs"])
    assert nonempty > 20, "fixture filters must match rows"


async def test_pipeline_resolution_never_loads_traces(tmp_path: Path, monkeypatch) -> None:
    store = await _seed(tmp_path / "golden.db", listed=False)  # legacy/production or graph-only manifest

    async def no_traces(*args, **kwargs):
        raise AssertionError("resolve_scope loaded traces")

    monkeypatch.setattr(store, "list_traces", no_traces)
    resolved = await service.resolve_scope(store, service.InvestigationRequest.from_mapping({"run_id": RUN}))
    assert resolved.pipeline_id == PIPELINE
    explicit = await service.resolve_scope(store, service.InvestigationRequest.from_mapping({"run_id": RUN, "pipeline_id": PIPELINE}))
    assert explicit.pipeline_id == PIPELINE
    with pytest.raises(service.InvestigationError) as missing:
        await service.resolve_scope(store, service.InvestigationRequest.from_mapping({"run_id": RUN, "pipeline_id": "other"}))
    assert (missing.value.status, missing.value.code) == (404, "pipeline_not_found")

    await store.save_traces([replace(trace, trace_id=f"{trace.trace_id}-b", pipeline_id="a-bm25") for trace in run_fixture().traces])
    assert await store.list_pipeline_ids(RUN) == ["a-bm25", PIPELINE]
    with pytest.raises(service.InvestigationError) as ambiguous:
        await service.resolve_scope(store, service.InvestigationRequest.from_mapping({"run_id": RUN}))
    assert ambiguous.value.code == "pipeline_required" and "['a-bm25', 'golden-hybrid']" in ambiguous.value.detail


async def test_migrate_adds_the_ordered_filter_indexes_to_a_v3_file(tmp_path: Path) -> None:
    path = tmp_path / "v3.db"
    await _seed(path)
    with sqlite3.connect(path) as db:
        for name in ORDER_INDEXES:
            db.execute(f"DROP INDEX {name}")  # a v3 file written before these indexes existed

    report = migrate_database(path, backup=False)

    assert report["status"] == "already_current" and report["indexes_added"] == ORDER_INDEXES
    with sqlite3.connect(path) as db:
        assert set(ORDER_INDEXES) <= {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert migrate_database(path, backup=False)["indexes_added"] == []

    reset = tmp_path / "reset.db"
    reset_database(reset)  # stamped v3 with no tables: nothing to index, no error
    assert migrate_database(reset, backup=False)["indexes_added"] == []


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda payload: "{not json " + SENTINEL,
        lambda payload: json.dumps({**payload, "spans": [payload["spans"][0], {**payload["spans"][1], "input_capture": "bogus"}, *payload["spans"][2:]]}),
    ],
    ids=["invalid_json", "invalid_input_capture"],
)
async def test_undecodable_trace_raises_an_error_naming_it(tmp_path: Path, corrupt, request) -> None:
    path = tmp_path / "golden.db"
    store = await _seed(path)
    with sqlite3.connect(path) as db:
        trace_id, raw = db.execute("SELECT trace_id, trace_json FROM traces WHERE query_id = 'q-outage'").fetchone()
        db.execute("UPDATE traces SET trace_json = ? WHERE trace_id = ?", (corrupt(json.loads(raw)), trace_id))

    for read in (lambda: store.list_traces(TraceQuery(run_id=RUN)), lambda: store.get_trace(trace_id)):
        with pytest.raises(TraceDecodeError) as error:
            await read()
        assert error.value.trace_id == trace_id and trace_id in str(error.value) and SENTINEL not in str(error.value)
        expected = "JSONDecodeError" if "invalid_json" in request.node.callspec.id else "input_capture"
        assert expected in error.value.reason
    assert len(await store.list_traces(TraceQuery(run_id=RUN, query_id="q-refund"))) == 1  # other traces stay readable


# PostgreSQL mirrors, checked against a recording connection (no live server) -------------------


class _Connection:
    def __init__(self, rows=()):
        self.executed: list[str] = []
        self.fetch_calls: list[tuple] = []
        self.rows = list(rows)

    async def execute(self, sql, *params):
        self.executed.append(sql)

    async def fetch(self, sql, *params):
        self.fetch_calls.append((sql, params))
        return self.rows


class _Pool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        connection = self.connection

        class _Acquire:
            async def __aenter__(self):
                return connection

            async def __aexit__(self, *exc):
                return False

        return _Acquire()


def _postgres(rows=()) -> tuple[PostgresStore, _Connection]:
    connection = _Connection(rows)
    store = PostgresStore("postgresql://unused")
    store._pool = _Pool(connection)
    return store, connection


async def test_postgres_creates_the_ordered_filter_indexes() -> None:
    store, connection = _postgres()
    await store.init_db()
    for name in ORDER_INDEXES:
        assert any(f"CREATE INDEX IF NOT EXISTS {name}" in sql for sql in connection.executed)


async def test_postgres_pipeline_ids_are_distinct_and_sorted_in_python() -> None:
    store, connection = _postgres([{"pipeline_id": "b"}, {"pipeline_id": "a"}])
    assert await store.list_pipeline_ids("run-a") == ["a", "b"]
    sql, params = connection.fetch_calls[-1]
    assert sql == "SELECT DISTINCT pipeline_id FROM traces WHERE run_id = $1" and params == ("run-a",)


async def test_postgres_pair_facts_read_the_counted_columns_in_page_order() -> None:
    store, connection = _postgres([("relevant_excluded", "FN", "relevant", "excluded", 1, "filter", 3)])
    scope = InvestigationScope(run_id="run-a", pipeline_id="bm25", evaluation_digest="eval")
    facts = await store.list_investigation_pair_facts(scope, InvestigationFilter(outcome="relevant_excluded"), order="entity")
    assert facts == [{
        "outcome": "relevant_excluded", "confusion": "FN", "judgment": "relevant", "final_membership": "excluded",
        "observed": True, "loss_boundary": "filter", "events": 3,
    }]
    sql, params = connection.fetch_calls[-1]
    assert "json_array_length(payload_json::json -> 'events')" in sql and "outcome = $4" in sql
    assert sql.endswith("ORDER BY namespace, entity_id, priority, query_id, trace_id, unit")
    assert params == ("run-a", "bm25", "eval", "relevant_excluded")


async def test_postgres_undecodable_trace_names_it() -> None:
    store, connection = _postgres([{"trace_id": "t-9", "trace_json": "{not json " + SENTINEL}])
    with pytest.raises(TraceDecodeError) as error:
        await store.list_traces(TraceQuery(run_id="run-a"))
    assert error.value.trace_id == "t-9" and SENTINEL not in str(error.value)
    assert connection.fetch_calls[-1][0].startswith("SELECT trace_id, trace_json FROM traces WHERE run_id = $1")
