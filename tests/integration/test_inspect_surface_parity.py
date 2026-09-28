"""Every inspect surface reports the same judgment and outcome for the same (query, entity) pair.

Chunked results are evaluated against document-level qrels through a chunk map, by
``ro.evaluate`` and by ``retobs evaluate --chunk-map`` on an ``@observe``-instrumented module.
For each run, and again after ``retobs storage index`` and with no stored projection at all,
``inspect_query`` and ``inspect_document`` (by ``namespace:document_id`` and by chunk id) agree
across the service, HTTP, SDK, MCP and CLI; the projection's judgments agree with the run's
scored ground truth and recall.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import textwrap
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import retrieval_observatory as ro
from retrieval_observatory.cli import app as cli_app
from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.evidence import InvestigationError, InvestigationRequest, inspect_document, inspect_query
from retrieval_observatory.mcp import server as mcp_server
from retrieval_observatory.sdk.observe import observe
from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace

QUERIES = [
    {"query_id": "q-price", "text": "What changed in widget pricing?"},
    {"query_id": "q-ship", "text": "How are widgets shipped?"},
]
CORPUS = {
    "doc-pricing": "Widget pricing notes",
    "doc-faq": "Widget questions and answers",
    "doc-notes": "Release notes for widgets",
    "doc-misc": "Assorted widget trivia",
    "doc-shipping": "Widget shipping guide",
}
# ``doc-notes`` is short and never chunked: it is returned under its own id and absent from the map.
QRELS = {"q-price": {"doc-pricing": 2, "doc-faq": 1, "doc-notes": 1}, "q-ship": {"doc-shipping": 1, "doc-pricing": 0, "doc-notes": 0}}
RESULTS = {
    "What changed in widget pricing?": ["doc-pricing#0", "doc-faq#0", "doc-notes", "doc-misc#0", "doc-pricing#1"],
    "How are widgets shipped?": ["doc-shipping#0", "doc-pricing#2", "doc-misc#1", "doc-notes"],
}
REMOVED = {"doc-faq#0", "doc-notes"}
CHUNKS = sorted({chunk for chunks in RESULTS.values() for chunk in chunks if "#" in chunk})
K = 5
FIELDS = ("judgment", "grade", "outcome", "confusion", "final_membership", "final_rank", "loss_boundary", "capture_state", "observed")


@observe("SOURCE", op_id="search")
def search(query: str) -> list[dict]:
    return [{"id": chunk, "score": 1.0 / rank} for rank, chunk in enumerate(RESULTS[query], start=1)]


@observe("FILTER", op_id="acl_filter", parent_ids=("search",))
def acl_filter(query: str, search: list[dict]) -> list[dict]:
    return [hit for hit in search if hit["id"] not in REMOVED]


def widget_search(query: str) -> list[dict]:
    return acl_filter(query, search(query))


MODULE = textwrap.dedent(
    f"""
    from retrieval_observatory.sdk.observe import observe

    RESULTS = {RESULTS!r}
    REMOVED = {REMOVED!r}


    @observe("SOURCE", op_id="search")
    def search(query):
        return [{{"id": chunk, "score": 1.0 / rank}} for rank, chunk in enumerate(RESULTS[query], start=1)]


    @observe("FILTER", op_id="acl_filter", parent_ids=("search",))
    def acl_filter(query, search):
        return [hit for hit in search if hit["id"] not in REMOVED]


    def widget_search(query):
        return acl_filter(query, search(query))
    """
)


def _chunk_map(namespace: str | None) -> list[tuple[str, ...]]:
    return [(chunk, chunk.split("#")[0], *((namespace,) if namespace else ())) for chunk in CHUNKS]


def _evaluate_sdk(tmp_path: Path, namespace: str | None) -> tuple[str, str]:
    db = str(tmp_path / "sdk.db")
    report = ro.evaluate(
        widget_search, queries=QUERIES, qrels=QRELS, corpus=CORPUS, k=K, db_path=db, name="widgets",
        metrics={"recall_at_k": [K]}, chunk_map=_chunk_map(namespace),
    )
    return db, report.run_id


def _evaluate_cli(tmp_path: Path, namespace: str | None) -> tuple[str, str]:
    db = str(tmp_path / "cli.db")
    module = tmp_path / "widget_app.py"
    module.write_text(MODULE, encoding="utf-8")
    (tmp_path / "queries.jsonl").write_text("\n".join(json.dumps(q) for q in QUERIES), encoding="utf-8")
    (tmp_path / "corpus.json").write_text(json.dumps([{"id": d, "text": t} for d, t in CORPUS.items()]), encoding="utf-8")
    (tmp_path / "qrels.jsonl").write_text(
        "\n".join(json.dumps({"query_id": q, "doc_id": d, "relevance": g}) for q, rels in QRELS.items() for d, g in rels.items()),
        encoding="utf-8",
    )
    (tmp_path / "chunks.jsonl").write_text(
        "\n".join(json.dumps({"chunk_id": row[0], "document_id": row[1], **({"namespace": row[2]} if len(row) > 2 else {})}) for row in _chunk_map(namespace)),
        encoding="utf-8",
    )
    result = CliRunner().invoke(cli_app, [
        "evaluate", f"{module}:widget_search", "--queries", str(tmp_path / "queries.jsonl"), "--corpus", str(tmp_path / "corpus.json"),
        "--qrels", str(tmp_path / "qrels.jsonl"), "--chunk-map", str(tmp_path / "chunks.jsonl"), "--k", str(K), "--db", db,
        "--name", "widgets", "--format", "json",
    ])
    assert result.exit_code == 0, result.output
    with sqlite3.connect(db) as con:
        (run_id,) = con.execute("SELECT run_id FROM runs").fetchone()
    return db, run_id


SCENARIOS = {
    "sdk-2tuple": (_evaluate_sdk, None),
    "sdk-3tuple": (_evaluate_sdk, "kb"),
    "cli-3tuple": (_evaluate_cli, "kb"),
    "cli-2tuple": (_evaluate_cli, None),
}


def _facts(rows: list[dict]) -> dict[tuple[str, str, str], dict]:
    facts = {(row["query_id"], row["namespace"], row["entity_id"]): {field: row[field] for field in FIELDS} for row in rows}
    assert len(facts) == len(rows), "one row per (query, entity) in a one-trace-per-query run"
    return facts


def _cli_json(*args: str) -> dict:
    result = CliRunner().invoke(cli_app, [*args, "--format", "json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _query_surfaces(db: str, run_id: str, query_id: str, client: TestClient, base: str) -> dict[str, list[dict]]:
    response = client.get(f"{base}/{run_id}/queries/{quote(query_id, safe='')}")
    assert response.status_code == 200, response.text
    return {
        "service": asyncio.run(inspect_query(SQLiteStore(db), InvestigationRequest(run_id=run_id, query_id=query_id)))["rows"],
        "http": response.json()["rows"],
        "sdk": ro.inspect_query(run_id, query_id, db_path=db)["investigation"]["rows"],
        "mcp": asyncio.run(mcp_server._inspect_query(run_id, query_id, db_path=db))["investigation"]["rows"],
        "cli": _cli_json("inspect-query", run_id, query_id, "--db", db)["investigation"]["rows"],
    }


def _document_surfaces(db: str, run_id: str, entity: str, client: TestClient, base: str) -> dict[str, dict]:
    response = client.get(f"{base}/{run_id}/documents/{quote(entity, safe='')}")
    assert response.status_code == 200, (entity, response.text)
    return {
        "service": asyncio.run(inspect_document(SQLiteStore(db), InvestigationRequest(run_id=run_id, entity=entity))),
        "http": response.json(),
        "sdk": ro.inspect_document(run_id, entity, db_path=db),
        "mcp": asyncio.run(mcp_server._inspect_document(run_id, entity, db_path=db)),
        "cli": _cli_json("inspect-document", run_id, entity, "--db", db),
    }


def _scored(db: str, run_id: str) -> tuple[dict[str, set[str]], dict[str, float]]:
    """The run's scoring path: ground truth ids per query (as inspect-query shows them) and final-stage recall@K."""
    truth = {q["query_id"]: set(ro.inspect_query(run_id, q["query_id"], db_path=db)["ground_truth"]["relevant_doc_ids"]) for q in QUERIES}
    with sqlite3.connect(db) as con:
        rows = con.execute(
            "SELECT query_id, stage_index, value FROM metric_scores WHERE run_id = ? AND metric_name = 'recall' AND k = ? ORDER BY stage_index",
            (run_id, K),
        ).fetchall()
    recall = {query_id: value for query_id, _, value in rows}  # the last (final) stage wins
    return truth, recall


def _assert_surfaces_agree(db: str, run_id: str, projection: str, *, chunk_handles: bool = True) -> dict[tuple[str, str, str], dict]:
    registry = DbRegistry([db], read_only=False)
    client = TestClient(create_app(registry=registry, enable_uploads=False), raise_server_exceptions=False)
    base = f"/dbs/{registry.default_db_id}/investigation/runs"

    expected: dict[tuple[str, str, str], dict] = {}
    chunks_of: dict[str, set[str]] = {}
    for query in QUERIES:
        surfaces = _query_surfaces(db, run_id, query["query_id"], client, base)
        reference = _facts(surfaces["service"])
        for name, rows in surfaces.items():
            assert _facts(rows) == reference, f"inspect_query via {name} disagrees for {query['query_id']}"
        expected.update(reference)
        for row in surfaces["service"]:
            chunks_of.setdefault(f"{row['namespace']}:{row['entity_id']}", set()).update(row["occurrence_entity_ids"])

    for entity, chunks in sorted(chunks_of.items()):
        want = {key: value for key, value in expected.items() if f"{key[1]}:{key[2]}" == entity}
        # By ``namespace:document_id``, by the bare document id (resolved to its one namespace) and,
        # when the run has a chunk map, by every chunk id that occurred as this document.
        for handle in sorted({entity, entity.partition(":")[2], *(chunks if chunk_handles else ())}):
            for name, envelope in _document_surfaces(db, run_id, handle, client, base).items():
                assert _facts(envelope["rows"]) == want, f"inspect_document({handle!r}) via {name} disagrees with inspect_query"
                assert envelope["capabilities"]["projection"] == projection, (handle, name)
                assert (envelope["scope"]["entity"], envelope["scope"]["unit"]) == (entity, "document"), (handle, name)

    truth, recall = _scored(db, run_id)
    for query in QUERIES:
        own = {key: value for key, value in expected.items() if key[0] == query["query_id"]}
        relevant = {f"{ns}:{entity_id}" for (_, ns, entity_id), value in own.items() if value["judgment"] == "relevant"}
        scored = {doc_id if ":" in doc_id else f"default:{doc_id}" for doc_id in truth[query["query_id"]]}  # bare ids without a chunk map
        assert relevant == scored, f"projection and scored ground truth disagree for {query['query_id']}"
        delivered = sum(value["judgment"] == "relevant" and value["final_membership"] == "included" for value in own.values())
        assert recall[query["query_id"]] == pytest.approx(delivered / len(relevant))
    return expected


def _drop_projection(db: str, run_id: str) -> None:
    with sqlite3.connect(db) as con:
        for table in ("investigation_pairs", "investigation_summaries", "investigation_projections"):
            con.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))


def _assert_lifecycle(db: str, run_id: str, *, chunk_handles: bool = True) -> dict[tuple[str, str, str], dict]:
    """Surfaces agree after the evaluation, after ``retobs storage index``, and with no projection."""
    after_evaluate = _assert_surfaces_agree(db, run_id, "ready", chunk_handles=chunk_handles)
    result = CliRunner().invoke(cli_app, ["storage", "index", run_id, "--db", db])
    assert result.exit_code == 0, result.output
    assert _assert_surfaces_agree(db, run_id, "ready", chunk_handles=chunk_handles) == after_evaluate
    _drop_projection(db, run_id)
    assert _assert_surfaces_agree(db, run_id, "unavailable", chunk_handles=chunk_handles) == after_evaluate
    return after_evaluate


@observe("SOURCE", op_id="search")
def named_search(query: str) -> list[dict]:
    """Chunks that name their parent document, as an application's own search results often do."""
    return [{"id": chunk, "document_id": chunk.split("#")[0], "score": 1.0 / rank} for rank, chunk in enumerate(RESULTS[query], start=1)]


@observe("FILTER", op_id="acl_filter", parent_ids=("search",))
def named_filter(query: str, search: list[dict]) -> list[dict]:
    return [hit for hit in search if hit["id"] not in REMOVED]


def named_widget_search(query: str) -> list[dict]:
    return named_filter(query, named_search(query))


# Judgments written on the chunk ids the application returns (no chunk map).
CHUNK_QRELS = {"q-price": {"doc-faq#0": 1, "doc-pricing#1": 1, "doc-notes": 1}, "q-ship": {"doc-shipping#0": 1, "doc-pricing#2": 0}}


@pytest.mark.parametrize("qrels", ["chunk-ids", "document-ids"])
def test_candidates_naming_a_document_are_graded_alike_everywhere(tmp_path: Path, qrels: str) -> None:
    """Without a chunk map, hits carry ``document_id`` and the qrels name either the returned chunk
    ids or the documents. Scoring and every inspect surface judge each hit as the same entity."""
    db = str(tmp_path / "named.db")
    report = ro.evaluate(
        named_widget_search, queries=QUERIES, qrels=CHUNK_QRELS if qrels == "chunk-ids" else QRELS, corpus=CORPUS,
        k=K, db_path=db, name="widgets", metrics={"recall_at_k": [K]},
    )
    facts = _assert_lifecycle(db, report.run_id, chunk_handles=False)

    faq = facts[("q-price", "default", "doc-faq#0" if qrels == "chunk-ids" else "doc-faq")]
    assert (faq["judgment"], faq["outcome"], faq["confusion"], faq["loss_boundary"]) == ("relevant", "relevant_excluded", "FN", "acl_filter")
    notes = facts[("q-price", "default", "doc-notes")]
    assert (notes["judgment"], notes["outcome"], notes["loss_boundary"]) == ("relevant", "relevant_excluded", "acl_filter")
    if qrels == "chunk-ids":  # a judged chunk is its own row; its unjudged sibling stays under the document
        assert facts[("q-price", "default", "doc-pricing#1")]["outcome"] == "relevant_delivered"
        assert facts[("q-price", "default", "doc-pricing")]["judgment"] == "unjudged"


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_every_surface_reports_one_judgment_per_pair(tmp_path: Path, scenario: str) -> None:
    evaluate, namespace = SCENARIOS[scenario]
    db, run_id = evaluate(tmp_path, namespace)
    ns = namespace or "default"

    after_evaluate = _assert_lifecycle(db, run_id)
    # The relevant chunk the filter dropped and the unchunked relevant document are both false negatives.
    for entity in (f"{ns}:doc-faq", "default:doc-notes"):
        namespace_of, entity_id = entity.split(":")
        row = after_evaluate[("q-price", namespace_of, entity_id)]
        assert (row["judgment"], row["outcome"], row["confusion"], row["loss_boundary"]) == ("relevant", "relevant_excluded", "FN", "acl_filter")
    assert after_evaluate[("q-ship", "default", "doc-notes")]["judgment"] == "nonrelevant"


def test_an_unmapped_id_that_is_a_judged_document_is_judged_as_scoring_judges_it(tmp_path: Path) -> None:
    """``doc-notes`` is absent from the chunk map. Scoring counts it as the judged document it names,
    so the projection does too; it is never an ``unmapped`` chunk beside a relevant ground truth."""
    db, run_id = _evaluate_sdk(tmp_path, "kb")
    truth, recall = _scored(db, run_id)
    rows = {(r["query_id"], r["namespace"], r["entity_id"]): r for q in QUERIES for r in ro.inspect_query(run_id, q["query_id"], db_path=db)["investigation"]["rows"]}

    assert "default:doc-notes" in truth["q-price"] and recall["q-price"] == pytest.approx(1 / 3)
    price, ship = rows[("q-price", "default", "doc-notes")], rows[("q-ship", "default", "doc-notes")]
    assert (price["judgment"], price["outcome"], price["loss_boundary"]) == ("relevant", "relevant_excluded", "acl_filter")
    assert (ship["judgment"], ship["outcome"]) == ("nonrelevant", "judged_nonrelevant")
    assert rows[("q-price", "kb", "doc-misc")]["judgment"] == "unjudged"  # mapped, simply not judged


async def test_inspect_document_without_a_projection_projects_read_only(tmp_path: Path) -> None:
    db, run_id = await asyncio.to_thread(_evaluate_sdk, tmp_path, "kb")
    _drop_projection(db, run_id)
    repair = f"retobs storage index {run_id} --db {db}"
    with sqlite3.connect(db) as con:  # as the runner records a projection write that failed
        (raw,) = con.execute("SELECT manifest_json FROM run_manifests WHERE run_id = ?", (run_id,)).fetchone()
        manifest = {**json.loads(raw), "investigation_projection": {"widgets": {"status": "failed", "error": "OperationalError('disk I/O error')", "repair": repair}}}
        con.execute("UPDATE run_manifests SET manifest_json = ? WHERE run_id = ?", (json.dumps(manifest), run_id))
    before = hashlib.sha256(Path(db).read_bytes()).hexdigest()
    store = SQLiteStore(db, read_only=True)

    envelope = await inspect_document(store, InvestigationRequest(run_id=run_id, entity="kb:doc-faq"))
    assert envelope["capabilities"]["projection"] == "unavailable"
    finding = next(f for f in envelope["findings"] if f["code"] == "projection_unavailable")
    assert "retobs storage index" in finding["action"]
    failed = next(f for f in envelope["findings"] if f["code"] == "projection_failed")
    assert "disk I/O error" in failed["detail"] and failed["action"] == repair
    assert [(r["query_id"], r["judgment"], r["outcome"], r["loss_boundary"]) for r in envelope["rows"]] == [
        ("q-price", "relevant", "relevant_excluded", "acl_filter")
    ]
    assert envelope["total"] == 1 and envelope["summary"]["pairs"] == 1
    with pytest.raises(InvestigationError) as missing:
        await inspect_document(store, InvestigationRequest(run_id=run_id, entity="kb:doc-absent"))
    assert (missing.value.status, missing.value.code) == (404, "entity_not_found")

    registry = DbRegistry([db], read_only=True)
    client = TestClient(create_app(registry=registry, enable_uploads=False), raise_server_exceptions=False)
    response = client.get(f"/dbs/{registry.default_db_id}/investigation/runs/{run_id}/documents/{quote('doc-faq#0', safe='')}")
    assert response.status_code == 200 and response.json()["rows"] == envelope["rows"]
    assert hashlib.sha256(Path(db).read_bytes()).hexdigest() == before


def test_traces_pushed_without_an_evaluation_are_inspectable_before_and_after_indexing(tmp_path: Path) -> None:
    """A run holding only pushed traces (scenario runs): no manifest, no judgments, no projection."""
    db, evaluated = _evaluate_sdk(tmp_path, None)
    store = SQLiteStore(db)

    async def push() -> None:
        await store.init_db()
        traces = await store.list_traces(TraceQuery(run_id=evaluated))
        await store.save_run("scenario-run", "scenarios", json.dumps({}))
        await store.save_traces([replace(trace, run_id="scenario-run", trace_id=f"scenario-{trace.trace_id}") for trace in traces])

    asyncio.run(push())
    request = InvestigationRequest(run_id="scenario-run", entity="doc-misc#0")
    before = asyncio.run(inspect_document(store, request))
    assert before["capabilities"]["projection"] == "unavailable"
    assert {"judgments_unavailable", "projection_unavailable"} <= {f["code"] for f in before["findings"]}
    assert [(r["query_id"], r["entity_id"], r["judgment"]) for r in before["rows"]] == [("q-price", "doc-misc#0", "unjudged")]

    result = CliRunner().invoke(cli_app, ["storage", "index", "scenario-run", "--db", db])
    assert result.exit_code == 0, result.output
    after = asyncio.run(inspect_document(store, request))
    assert after["capabilities"]["projection"] == "ready"
    assert _facts(after["rows"]) == _facts(before["rows"])


async def test_chunk_unit_over_document_judgments_says_they_are_not_inherited(tmp_path: Path) -> None:
    db, run_id = await asyncio.to_thread(_evaluate_sdk, tmp_path, None)
    envelope = await inspect_document(SQLiteStore(db), InvestigationRequest(run_id=run_id, entity="doc-faq#0", unit="chunk"))
    assert [(r["query_id"], r["judgment"]) for r in envelope["rows"]] == [("q-price", "unjudged")]
    finding = next(f for f in envelope["findings"] if f["code"] == "judgments_not_inherited")
    assert "unit=document" in finding["action"]


def test_a_bare_id_in_two_namespaces_is_ambiguous_on_every_surface(tmp_path: Path) -> None:
    """``doc-shared`` occurs in namespaces ``kb`` and ``web``: a bare handle names neither, so every
    surface refuses it with ``entity_ambiguous`` and lists both keys; ``namespace:id`` still works."""
    db = str(tmp_path / "ambiguous.db")
    store = SQLiteStore(db)
    hits = tuple(Candidate("doc-shared", 1.0 / rank, rank, candidate_id=f"{ns}-hit", metadata={"namespace": ns}) for rank, ns in enumerate(("kb", "web"), start=1))

    async def push() -> None:
        await store.init_db()
        await store.save_run("shared-run", "scenarios", json.dumps({}))
        await store.save_traces([
            RetrievalTrace(
                trace_id="t-shared", service_id="svc", run_id="shared-run", query_id="q-shared", query_text="shared", pipeline_id="pipe",
                spans=(OperatorSpan.source("search", "Search", hits),), final_op_ids=("search",),
            )
        ])

    asyncio.run(push())
    with pytest.raises(InvestigationError) as service:
        asyncio.run(inspect_document(store, InvestigationRequest(run_id="shared-run", entity="doc-shared")))
    assert (service.value.status, service.value.code) == (422, "entity_ambiguous")
    assert "kb:doc-shared" in service.value.detail and "web:doc-shared" in service.value.detail

    registry = DbRegistry([db], read_only=False)
    client = TestClient(create_app(registry=registry, enable_uploads=False), raise_server_exceptions=False)
    response = client.get(f"/dbs/{registry.default_db_id}/investigation/runs/shared-run/documents/doc-shared")
    assert response.status_code == 422 and response.json()["detail"]["code"] == "entity_ambiguous"
    with pytest.raises(InvestigationError) as sdk:
        ro.inspect_document("shared-run", "doc-shared", db_path=db)
    assert sdk.value.code == "entity_ambiguous"
    with pytest.raises(ValueError, match="entity_ambiguous"):
        asyncio.run(mcp_server._inspect_document("shared-run", "doc-shared", db_path=db))
    result = CliRunner().invoke(cli_app, ["inspect-document", "shared-run", "doc-shared", "--db", db])
    assert result.exit_code == 1 and "entity_ambiguous" in result.output

    explicit = asyncio.run(inspect_document(store, InvestigationRequest(run_id="shared-run", entity="web:doc-shared")))
    assert [(r["namespace"], r["entity_id"], r["final_rank"]) for r in explicit["rows"]] == [("web", "doc-shared", 2)]

    indexed = CliRunner().invoke(cli_app, ["storage", "index", "shared-run", "--db", db])  # the stored-projection path
    assert indexed.exit_code == 0, indexed.output
    with pytest.raises(InvestigationError) as stored:
        asyncio.run(inspect_document(store, InvestigationRequest(run_id="shared-run", entity="doc-shared")))
    assert (stored.value.status, stored.value.code) == (422, "entity_ambiguous")


def test_terminal_output_names_the_unit_and_the_namespaced_entity(tmp_path: Path) -> None:
    db, run_id = _evaluate_sdk(tmp_path, "kb")
    document = CliRunner().invoke(cli_app, ["inspect-document", run_id, "doc-faq", "--db", db])
    assert document.exit_code == 0, document.output
    assert "kb:doc-faq" in document.output and "unit=document" in document.output
    assert "entity_resolved" in document.output

    query = CliRunner().invoke(cli_app, ["inspect-query", run_id, "q-price", "--db", db])
    assert query.exit_code == 0, query.output
    assert "unit=document" in query.output
    assert "kb:doc-faq" in query.output and "default:doc-notes" in query.output
