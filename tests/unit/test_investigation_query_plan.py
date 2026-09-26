"""The investigation read paths stay on indexes and inside page bounds.

A tiny synthetic run from ``scripts/bench_investigation.py`` is persisted and projected. Each
service read is driven through a ``SQLiteStore`` whose connections carry a ``sqlite3`` trace
callback; every captured statement against ``investigation_pairs``/``investigation_summaries`` is
re-run under ``EXPLAIN QUERY PLAN`` and must SEARCH one of the table's indexes (the composite
primary key shows up as ``sqlite_autoindex_<table>_1``), never SCAN the table.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import shutil
import sqlite3
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.evidence.service import (
    InvestigationRequest,
    inspect_document,
    inspect_investigation,
    inspect_query,
    resolve_scope,
)
from retrieval_observatory.store.sqlite import SQLiteStore

TABLES = ("investigation_pairs", "investigation_summaries")
ALLOWED_INDEXES = {
    "investigation_pairs": re.compile(r"USING (COVERING )?INDEX (idx_investigation_pairs_\w+|sqlite_autoindex_investigation_pairs_1)\b"),
    "investigation_summaries": re.compile(r"USING (COVERING )?INDEX sqlite_autoindex_investigation_summaries_1\b"),
}


def _bench():
    path = Path(__file__).parents[2] / "scripts" / "bench_investigation.py"
    spec = importlib.util.spec_from_file_location("bench_investigation", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_investigation"] = module
    spec.loader.exec_module(module)
    return module


bench = _bench()


@pytest.fixture(scope="module")
def db_path(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("plan") / "tiny.db"

    async def seed() -> None:
        await bench.generate_run(path, bench.SIZES["tiny"], seed=7)
        await bench.index_run(path)

    asyncio.run(seed())
    return path


def _request(**values) -> InvestigationRequest:
    return InvestigationRequest.from_mapping({"run_id": bench.RUN_ID, "pipeline_id": bench.PIPELINE_ID, **values})


def _traced_store(db_path: Path) -> tuple[SQLiteStore, list[str]]:
    store = SQLiteStore(str(db_path))
    statements: list[str] = []
    connect = store._connect

    @asynccontextmanager
    async def traced():
        async with connect() as db:
            await db.set_trace_callback(statements.append)
            yield db

    store._connect = traced  # type: ignore[method-assign]
    return store, statements


def _plans(db_path: Path, statements: list[str]) -> dict[str, list[str]]:
    """``{statement: plan detail lines}`` for every captured read of the investigation tables."""
    reads = [
        sql for sql in dict.fromkeys(statements)
        if sql.lstrip().upper().startswith("SELECT") and any(f"FROM {table}" in sql for table in TABLES)
    ]
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        return {sql: [row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}")] for sql in reads}


def _assert_indexed(plans: dict[str, list[str]], expected_table: str) -> None:
    assert any(f"FROM {expected_table}" in sql for sql in plans), f"no statement against {expected_table} captured"
    for sql, lines in plans.items():
        for table, allowed in ALLOWED_INDEXES.items():
            touching = [line for line in lines if re.search(rf"\b{table}\b", line)]
            for line in touching:
                assert not line.startswith("SCAN"), f"full scan of {table}:\n{sql}\n{lines}"
                assert line.startswith("SEARCH") and allowed.search(line), f"{table} not read through its index:\n{sql}\n{lines}"


async def _first_query_id(db_path: Path) -> str:
    envelope = await inspect_investigation(SQLiteStore(str(db_path)), _request())
    return envelope["rows"][0]["query_id"]


async def test_first_queries_page_reads_the_summaries_primary_key(db_path: Path) -> None:
    store, statements = _traced_store(db_path)
    envelope = await inspect_investigation(store, _request(view="queries"))
    assert envelope["scope"]["rows_kind"] == "query_summaries" and envelope["rows"]
    _assert_indexed(_plans(db_path, statements), "investigation_summaries")


async def test_one_querys_candidates_use_a_pairs_index(db_path: Path) -> None:
    query_id = await _first_query_id(db_path)
    store, statements = _traced_store(db_path)
    envelope = await inspect_query(store, _request(query_id=query_id))
    assert envelope["rows"] and all(row["query_id"] == query_id for row in envelope["rows"])
    _assert_indexed(_plans(db_path, statements), "investigation_pairs")


async def test_documents_page_reads_the_summaries_primary_key(db_path: Path) -> None:
    store, statements = _traced_store(db_path)
    envelope = await inspect_investigation(store, _request(view="documents"))
    assert envelope["scope"]["rows_kind"] == "document_summaries" and envelope["rows"]
    _assert_indexed(_plans(db_path, statements), "investigation_summaries")


async def test_one_entitys_queries_use_a_pairs_index(db_path: Path) -> None:
    documents = await inspect_investigation(SQLiteStore(str(db_path)), _request(view="documents"))
    entity = documents["rows"][0]["entity"]
    store, statements = _traced_store(db_path)
    envelope = await inspect_document(store, _request(entity=entity))
    assert envelope["rows"] and all(f"{row['namespace']}:{row['entity_id']}" == entity for row in envelope["rows"])
    _assert_indexed(_plans(db_path, statements), "investigation_pairs")


async def test_outcome_filtered_page_uses_a_pairs_index(db_path: Path) -> None:
    store, statements = _traced_store(db_path)
    envelope = await inspect_investigation(store, _request(outcome="relevant_excluded"))
    assert envelope["scope"]["rows_kind"] == "pairs" and envelope["rows"]
    assert all(row["outcome"] == "relevant_excluded" for row in envelope["rows"])
    _assert_indexed(_plans(db_path, statements), "investigation_pairs")


async def test_cursor_pages_use_indexes(db_path: Path) -> None:
    probe = SQLiteStore(str(db_path))
    pairs_cursor = (await inspect_investigation(probe, _request(judgment="unjudged", limit=2)))["next_cursor"]
    summaries_cursor = (await inspect_investigation(probe, _request(view="documents", limit=2)))["next_cursor"]
    assert pairs_cursor and summaries_cursor

    store, statements = _traced_store(db_path)
    await inspect_investigation(store, _request(judgment="unjudged", limit=2, cursor=pairs_cursor))
    pair_plans = _plans(db_path, statements)
    assert any(" > (" in sql for sql in pair_plans), "keyset predicate not captured"
    _assert_indexed(pair_plans, "investigation_pairs")

    store, statements = _traced_store(db_path)
    await inspect_investigation(store, _request(view="documents", limit=2, cursor=summaries_cursor))
    summary_plans = _plans(db_path, statements)
    assert any("key > " in sql for sql in summary_plans), "keyset predicate not captured"
    _assert_indexed(summary_plans, "investigation_summaries")


@pytest.mark.parametrize(("filter_name", "column"), [("query_id", "query_id"), ("entity", "entity_id"), ("outcome", "outcome")])
async def test_filtered_page_select_searches_on_its_filter_column(db_path: Path, filter_name: str, column: str) -> None:
    probe = SQLiteStore(str(db_path))
    if filter_name == "query_id":
        value, call = await _first_query_id(db_path), inspect_query
    elif filter_name == "entity":
        value, call = (await inspect_investigation(probe, _request(view="documents")))["rows"][0]["entity"], inspect_document
    else:
        value, call = "relevant_excluded", inspect_investigation
    store, statements = _traced_store(db_path)
    await call(store, _request(**{filter_name: value}))
    page_selects = {sql: lines for sql, lines in _plans(db_path, statements).items() if "FROM investigation_pairs" in sql and "ORDER BY" in sql}
    assert page_selects
    for sql, lines in page_selects.items():
        assert any(line.startswith("SEARCH") and f"{column}=?" in line for line in lines), f"{sql}\n{lines}"


@pytest.mark.parametrize(("filter_name", "column"), [("query_id", "query_id"), ("entity", "entity_id"), ("outcome", "outcome")])
async def test_filtered_summary_read_searches_its_filter_index_even_on_an_unmigrated_file(
    db_path: Path, tmp_path: Path, filter_name: str, column: str
) -> None:
    # A file opened read-only (or never re-opened writable) lacks the ordered filter indexes;
    # the summary's single read must still use the filter column's own index.
    unmigrated = tmp_path / "unmigrated.db"
    shutil.copyfile(db_path, unmigrated)
    with sqlite3.connect(unmigrated) as db:
        for name in ("idx_investigation_pairs_entity_order", "idx_investigation_pairs_outcome_order"):
            db.execute(f"DROP INDEX {name}")
    probe = SQLiteStore(str(unmigrated), read_only=True)
    if filter_name == "query_id":
        value, call = await _first_query_id(unmigrated), inspect_query
    elif filter_name == "entity":
        value, call = (await inspect_investigation(probe, _request(view="documents")))["rows"][0]["entity"], inspect_document
    else:
        value, call = "relevant_excluded", inspect_investigation
    store, statements = _traced_store(unmigrated)
    store.read_only = True
    await call(store, _request(**{filter_name: value}))
    summary_reads = {sql: lines for sql, lines in _plans(unmigrated, statements).items() if "json_array_length" in sql}
    assert summary_reads
    for sql, lines in summary_reads.items():
        assert any(line.startswith("SEARCH") and f"{column}=?" in line for line in lines), f"{sql}\n{lines}"


async def test_page_sizes_default_to_50_and_clamp_to_200(db_path: Path) -> None:
    store = SQLiteStore(str(db_path))
    assert _request().limit == 50
    assert _request(limit=500).limit == 200 and _request(limit=0).limit == 1

    documents = await inspect_investigation(store, _request(view="documents"))
    assert documents["total"] > 200, "fixture too small to observe the clamp"
    assert len(documents["rows"]) == 50
    assert len((await inspect_investigation(store, _request(view="documents", limit=500)))["rows"]) == 200

    scope = (await resolve_scope(store, _request())).store_scope()
    assert len((await store.list_investigation_pairs(scope, limit=500)).rows) == 200
    assert len((await store.list_investigation_summaries(scope, "document", limit=500)).rows) == 200

    query_id = await _first_query_id(db_path)
    for limit, envelope in (
        (50, await inspect_investigation(store, _request(judgment="unjudged"))),
        (3, await inspect_investigation(store, _request(judgment="unjudged", limit=3))),
        (5, await inspect_query(store, _request(query_id=query_id, limit=5))),
    ):
        assert envelope["total"] > limit and len(envelope["rows"]) == limit


def test_http_limit_above_maximum_is_clamped(db_path: Path) -> None:
    registry = DbRegistry([str(db_path)], read_only=True)
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    base = f"/dbs/{registry.default_db_id}/investigation/runs/{bench.RUN_ID}"
    response = client.get(f"{base}/documents", params={"pipeline_id": bench.PIPELINE_ID, "limit": 500})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 200 and len(body["rows"]) == 200 and body["next_cursor"]
    default = client.get(f"{base}/documents", params={"pipeline_id": bench.PIPELINE_ID}).json()
    assert len(default["rows"]) == 50

