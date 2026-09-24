"""Investigation service and its four transports, checked against the golden fixture.

One SQLite file holds ``golden-run`` (pipelines ``golden-hybrid`` and ``golden-other``) and
``other-run`` (same query ids) so scoping, ambiguity and read-only behaviour are all observable.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
from collections import Counter
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from retrieval_observatory.cli import app as cli_app
from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.evidence import query as query_evidence_module
from retrieval_observatory.evidence.query import build_query_evidence
from retrieval_observatory.mcp import server as mcp_server
from retrieval_observatory.sdk import inspect_document as sdk_inspect_document
from retrieval_observatory.store.sqlite import SQLiteStore
from tests.fixtures.investigation_cases import EXPECTED_DOCUMENT_OUTCOMES, EXPECTED_STAGE_COUNTS, run_fixture

RUN = "golden-run"
PIPELINE = "golden-hybrid"
OTHER_PIPELINE = "golden-other"
OTHER_RUN = "other-run"
OUTCOME_FIELDS = ("judgment", "final_membership", "in_final_output", "final_rank", "confusion", "capture_state", "loss_boundary")


async def _seed(db_path: Path) -> None:
    fixture = run_fixture()
    manifest = {
        "normalized_config": {"metrics": {"recall_at_k": [3]}},
        "counts": {"attempted": 3},
        "judgment_records": fixture.judgments,
        "chunk_map": fixture.chunk_map,
    }
    store = SQLiteStore(str(db_path))
    await store.init_db()
    for run_id, prefix in ((RUN, ""), (OTHER_RUN, "other-")):
        await store.save_run(run_id, "golden", json.dumps({}))
        await store.save_run_manifest(run_id, manifest)
        await store.save_traces([replace(t, run_id=run_id, trace_id=f"{prefix}{t.trace_id}") for t in fixture.traces])
        await store.save_run_queries(run_id, fixture.queries, "golden")
    await store.save_traces([replace(fixture.traces[0], trace_id="trace-other-q-refund", pipeline_id=OTHER_PIPELINE)])


@pytest.fixture
def db_path(tmp_path: Path):
    import asyncio

    path = tmp_path / "golden.db"
    asyncio.run(_seed(path))
    return path


def _client(db_path: Path, *, read_only: bool = False) -> tuple[TestClient, str]:
    registry = DbRegistry([str(db_path)], read_only=read_only)
    client = TestClient(create_app(registry=registry, enable_uploads=False), raise_server_exceptions=False)
    return client, f"/dbs/{registry.default_db_id}/investigation/runs"


def _get(client: TestClient, base: str, path: str, **params):
    response = client.get(f"{base}/{path}", params={"pipeline_id": PIPELINE, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _build(client: TestClient, base: str, run_id: str = RUN, pipeline_id: str | None = PIPELINE) -> dict:
    response = client.post(f"{base}/{run_id}/projection", json={"pipeline_id": pipeline_id})
    assert response.status_code == 200, response.text
    return response.json()


def _codes(envelope: dict) -> set[str]:
    return {finding["code"] for finding in envelope["findings"]}


def _expected(query_id: str) -> dict[tuple[str, str], dict]:
    return {
        (outcome.namespace, outcome.document_id): {field: getattr(outcome, field) for field in OUTCOME_FIELDS}
        for outcome in EXPECTED_DOCUMENT_OUTCOMES
        if outcome.query_id == query_id
    }


def _key(row: dict) -> tuple[str, str]:
    return (row["namespace"], row["entity_id"])


def test_query_detail_without_projection_projects_one_query_and_flags_it(db_path: Path) -> None:
    client, base = _client(db_path)
    envelope = _get(client, base, f"{RUN}/queries/q-refund")
    assert envelope["capabilities"]["projection"] == "unavailable"
    assert "projection_unavailable" in _codes(envelope)
    assert next(f for f in envelope["findings"] if f["code"] == "projection_unavailable")["action"].endswith("`retobs storage index RUN`")
    assert envelope["scope"]["k"] == 3 and "k_defaulted" in _codes(envelope)
    got = {_key(row): {field: row[field] for field in OUTCOME_FIELDS} for row in envelope["rows"]}
    expected = _expected("q-refund")
    assert {key: got[key] for key in expected} == expected
    assert got[("kb", "doc-news")]["loss_boundary"] == "recency_filter"  # observed, removed upstream, unjudged
    assert envelope["total"] in (None, len(envelope["rows"]))
    assert all(row["trace_id"] == "trace-q-refund" for row in envelope["rows"])
    stages = {stage["op_id"]: stage for stage in envelope["stages"]}
    assert stages["expand"]["status"] == "SKIPPED_BY_GATE"
    assert stages["select"]["received"] == 5 and stages["select"]["removed"] == 1
    assert stages["rerank@lexical"]["operator_id"] == "rerank" and stages["rerank@lexical"]["branch"] == "lexical"


def test_list_without_projection_returns_actionable_finding_not_a_scan(db_path: Path) -> None:
    client, base = _client(db_path)
    for view in ("queries", "documents"):
        envelope = _get(client, base, f"{RUN}/{view}")
        assert envelope["rows"] == [] and envelope["total"] is None
        assert "projection_unavailable" in _codes(envelope)
    assert _get(client, base, f"{RUN}/projection") == {"status": "unavailable"}


def test_build_projection_then_list_orders_relevant_misses_first(db_path: Path) -> None:
    client, base = _client(db_path)
    meta = _build(client, base)
    assert meta["status"] == "complete" and meta["row_count"] == 12 and meta["trace_count"] == 3
    assert _get(client, base, f"{RUN}/projection")["status"] == "complete"

    envelope = _get(client, base, f"{RUN}/queries")
    assert envelope["capabilities"]["projection"] == "ready" and "projection_unavailable" not in _codes(envelope)
    assert envelope["coverage"] == {"queries_attempted": 3, "queries_with_traces": 3, "queries_projected": 3, "pairs": 12, "events": envelope["summary"]["events"]}
    assert envelope["summary"]["by_confusion"] == {"TP": 5, "FP": 2, "FN": 1, "TN": 1, "unknown": 3}

    # Pair rows (a pair-level filter) come relevant misses first, then deliveries.
    envelope = _get(client, base, f"{RUN}/queries", judgment="relevant")
    assert envelope["total"] == 6 and envelope["next_cursor"] is None
    rows = envelope["rows"]
    assert (rows[0]["query_id"], rows[0]["entity_id"], rows[0]["outcome"]) == ("q-invoice", "doc-archive", "not_observed")
    priorities = [row["priority"] for row in rows]
    assert priorities == sorted(priorities)
    assert [row["outcome"] for row in rows[1:6]] == ["relevant_delivered"] * 5

    walked, cursor = [], None
    while True:
        page = _get(client, base, f"{RUN}/queries", judgment="relevant", limit=2, **({"cursor": cursor} if cursor else {}))
        assert page["total"] == 6 and len(page["rows"]) <= 2
        walked.extend(page["rows"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert [(r["query_id"], r["namespace"], r["entity_id"]) for r in walked] == [(r["query_id"], r["namespace"], r["entity_id"]) for r in rows]


def test_document_view_lists_entity_across_queries(db_path: Path) -> None:
    client, base = _client(db_path)
    _build(client, base)
    documents = _get(client, base, f"{RUN}/documents")
    assert documents["total"] == 8
    faq = next(row for row in documents["rows"] if row["entity"] == "kb:doc-faq")
    assert faq == {"entity": "kb:doc-faq", "queries": 2, "delivered": 1, "excluded": 0, "not_observed": 0, "unknown": 0, "judged_relevant_queries": ["q-refund"]}
    typeahead = _get(client, base, f"{RUN}/documents", entity="kb:doc-f*")
    assert [row["entity"] for row in typeahead["rows"]] == ["kb:doc-faq"]

    detail = _get(client, base, f"{RUN}/documents/{quote('kb:doc-faq', safe='')}")
    assert detail["scope"]["entity"] == "kb:doc-faq" and detail["total"] == 2
    assert {(row["query_id"], row["outcome"], row["final_rank"]) for row in detail["rows"]} == {
        ("q-refund", "relevant_delivered", 1),
        ("q-outage", "judged_nonrelevant", 1),
    }
    assert detail["summary"]["by_confusion"] == {"TP": 1, "FP": 1}


def test_filters_apply_to_rows_totals_and_summary(db_path: Path) -> None:
    client, base = _client(db_path)
    _build(client, base)
    missed = _get(client, base, f"{RUN}/queries", outcome="not_observed")
    assert missed["total"] == 1 and [_key(r) for r in missed["rows"]] == [("kb", "doc-archive")]
    assert missed["summary"]["pairs"] == 1 and missed["summary"]["by_outcome"] == {"not_observed": 1}
    none = _get(client, base, f"{RUN}/queries", outcome="relevant_excluded")
    assert none["rows"] == [] and none["total"] == 0 and none["summary"]["pairs"] == 0
    at_select = _get(client, base, f"{RUN}/queries", stage_id="select")
    assert at_select["total"] == 1 and [(r["query_id"], r["entity_id"]) for r in at_select["rows"]] == [("q-refund", "doc-legal")]
    assert at_select["summary"]["by_loss_boundary"] == {"select": 1}
    partial = _get(client, base, f"{RUN}/queries", capture_state="partial", judgment="relevant")
    assert [(r["query_id"], r["entity_id"]) for r in partial["rows"]] == [("q-outage", "doc-guide")]


def test_queries_view_lists_exact_per_query_summaries(db_path: Path) -> None:
    client, base = _client(db_path)
    _build(client, base)
    envelope = _get(client, base, f"{RUN}/queries")
    assert envelope["scope"]["rows_kind"] == "query_summaries" and "filtered_pairs" not in _codes(envelope)
    assert envelope["total"] == 3 and envelope["next_cursor"] is None
    rows = {row["query_id"]: row for row in envelope["rows"]}
    assert list(rows) == ["q-invoice", "q-outage", "q-refund"]
    refund = rows["q-refund"]
    assert refund["query_text"] and refund["trace_ids"] == ["trace-q-refund"]
    assert (refund["relevant_delivered"], refund["relevant_missed"], refund["unjudged_included"], refund["unknown_capture"]) == (2, 0, 1, 0)
    expected_boundaries = {query_id: Counter(o.loss_boundary for o in EXPECTED_DOCUMENT_OUTCOMES if o.query_id == query_id and o.loss_boundary) for query_id in rows}
    for query_id, boundaries in expected_boundaries.items():
        assert {key: rows[query_id]["loss_boundaries"][key] for key in boundaries} == dict(boundaries), query_id
    assert "select" in expected_boundaries["q-refund"]
    assert rows["q-invoice"]["loss_boundaries"] == {"not_observed": 1}
    assert rows["q-outage"]["unknown_capture"] == 2  # partial capture on both judged pairs

    walked, cursor = [], None
    while True:
        page = _get(client, base, f"{RUN}/queries", limit=2, **({"cursor": cursor} if cursor else {}))
        assert page["total"] == 3 and len(page["rows"]) <= 2 and page["scope"]["rows_kind"] == "query_summaries"
        walked.extend(row["query_id"] for row in page["rows"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert walked == ["q-invoice", "q-outage", "q-refund"]
    assert [row["query_id"] for row in _get(client, base, f"{RUN}/queries", query_id="q-o*")["rows"]] == ["q-outage"]


def test_queries_view_with_a_filter_returns_pairs(db_path: Path) -> None:
    client, base = _client(db_path)
    _build(client, base)
    envelope = _get(client, base, f"{RUN}/queries", outcome="relevant_excluded")
    assert envelope["scope"]["rows_kind"] == "pairs" and envelope["rows"] == [] and envelope["total"] == 0
    assert "filtered_pairs" in _codes(envelope)
    assert _get(client, base, f"{RUN}/documents")["scope"]["rows_kind"] == "document_summaries"
    assert _get(client, base, f"{RUN}/queries/q-refund")["scope"]["rows_kind"] == "pairs"


def test_invalid_scope_and_selectors_return_400_422(db_path: Path) -> None:
    client, base = _client(db_path)
    for params, status, code in (
        ({"unit": "paragraph"}, 422, "unsupported_value"),
        ({"outcome": "harmful"}, 422, "unsupported_value"),
        ({"k": 0}, 422, "unsupported_value"),
        ({"k": "three"}, 422, "invalid_value"),
        ({"limit": "lots"}, 422, "invalid_value"),
        ({"bogus": 1}, 400, "unknown_parameter"),
        ({"cursor": "not-a-cursor"}, 400, "invalid_cursor"),
    ):
        if "cursor" in params:
            _build(client, base)
        response = client.get(f"{base}/{RUN}/queries", params={"pipeline_id": PIPELINE, **params})
        assert response.status_code == status, (params, response.text)
        assert response.json()["detail"]["code"] == code
    assert "supported" in client.get(f"{base}/{RUN}/queries", params={"pipeline_id": PIPELINE, "bogus": 1}).json()["detail"]["detail"]
    clamped = _get(client, base, f"{RUN}/queries", limit=9999, judgment="relevant")
    assert clamped["total"] == 6 and len(clamped["rows"]) == 6


def test_missing_resources_return_404(db_path: Path) -> None:
    client, base = _client(db_path)
    _build(client, base)
    assert client.get(f"/dbs/nope/investigation/runs/{RUN}/queries").status_code == 404
    for path, params, code in (
        ("no-run/queries", {}, "run_not_found"),
        (f"{RUN}/queries", {"pipeline_id": "no-pipeline"}, "pipeline_not_found"),
        (f"{RUN}/queries/q-missing", {"pipeline_id": PIPELINE}, "query_not_found"),
        (f"{RUN}/queries/q-refund", {"pipeline_id": PIPELINE, "trace_id": "trace-q-outage"}, "trace_not_found"),
        (f"{RUN}/documents/kb:doc-missing", {"pipeline_id": PIPELINE}, "entity_not_found"),
    ):
        response = client.get(f"{base}/{path}", params=params)
        assert response.status_code == 404, (path, response.text)
        assert response.json()["detail"]["code"] == code


def test_pipeline_required_when_ambiguous(db_path: Path) -> None:
    client, base = _client(db_path)
    response = client.get(f"{base}/{RUN}/queries")
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "pipeline_required" and PIPELINE in detail["detail"] and OTHER_PIPELINE in detail["detail"]
    assert client.post(f"{base}/{RUN}/projection", json={}).status_code == 422
    assert client.get(f"{base}/{OTHER_RUN}/queries").status_code == 200


def test_incomplete_capture_is_evidence_limited_not_empty(db_path: Path) -> None:
    client, base = _client(db_path)
    for _ in range(2):  # first on the fly, then from the projection
        envelope = _get(client, base, f"{RUN}/queries/q-outage")
        row = next(r for r in envelope["rows"] if _key(r) == ("kb", "doc-faq"))
        assert row["capture_state"] == "partial" and row["outcome"] == "judged_nonrelevant" and row["final_rank"] == 1
        unknown = [e for e in row["events"] if e["kind"] == "unknown"]
        assert unknown and unknown[0]["op_id"] == "rerank@lexical" and unknown[0]["boundary_complete"] is False
        assert envelope["capabilities"]["capture"]["partial_rows"] == 2
        _build(client, base)


def test_gets_are_read_only(db_path: Path) -> None:
    writable, base = _client(db_path)
    _build(writable, base)
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    client, base = _client(db_path, read_only=True)
    paths = (
        f"{RUN}/queries", f"{RUN}/queries/q-refund", f"{RUN}/documents", f"{RUN}/documents/kb:doc-faq", f"{RUN}/projection",
        f"{OTHER_RUN}/queries", f"{OTHER_RUN}/queries/q-invoice", f"{OTHER_RUN}/documents",
    )
    for path in paths:
        assert client.get(f"{base}/{path}", params={"pipeline_id": PIPELINE}).status_code == 200, path
        assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before, path
    response = client.post(f"{base}/{OTHER_RUN}/projection", json={})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "read_only"
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before
    with sqlite3.connect(db_path) as db:
        scopes = db.execute("SELECT DISTINCT run_id, pipeline_id FROM investigation_pairs").fetchall()
    assert scopes == [(RUN, PIPELINE)]


def test_no_cross_run_or_pipeline_leakage(db_path: Path) -> None:
    client, base = _client(db_path)
    _build(client, base)
    _build(client, base, pipeline_id=OTHER_PIPELINE)
    _build(client, base, run_id=OTHER_RUN, pipeline_id=None)

    hybrid = _get(client, base, f"{RUN}/queries", judgment="relevant")
    assert hybrid["total"] == 6 and {(r["run_id"], r["pipeline_id"]) for r in hybrid["rows"]} == {(RUN, PIPELINE)}
    assert _get(client, base, f"{RUN}/queries")["coverage"]["pairs"] == 12
    other_pipeline = _get(client, base, f"{RUN}/queries", pipeline_id=OTHER_PIPELINE)
    assert other_pipeline["total"] == 1 and [r["trace_ids"] for r in other_pipeline["rows"]] == [["trace-other-q-refund"]]
    other_run = client.get(f"{base}/{OTHER_RUN}/queries").json()
    assert other_run["total"] == 3 and {t[:6] for r in other_run["rows"] for t in r["trace_ids"]} == {"other-"}
    refund = _get(client, base, f"{RUN}/queries/q-refund")
    assert {r["trace_id"] for r in refund["rows"]} == {"trace-q-refund"} and "multiple_traces" not in _codes(refund)
    assert refund["scope"]["run_id"] == RUN and refund["scope"]["pipeline_id"] == PIPELINE
    faq = _get(client, base, f"{RUN}/documents/kb:doc-faq")
    assert {(r["run_id"], r["pipeline_id"]) for r in faq["rows"]} == {(RUN, PIPELINE)} and faq["total"] == 2


def test_transports_return_the_same_payload(db_path: Path) -> None:
    client, base = _client(db_path)
    _build(client, base)
    http = _get(client, base, f"{RUN}/documents/kb:doc-faq")
    sdk = sdk_inspect_document(RUN, "kb:doc-faq", db_path=str(db_path), pipeline_id=PIPELINE)
    import asyncio

    mcp = asyncio.run(mcp_server._inspect_document(RUN, "kb:doc-faq", db_path=str(db_path), pipeline_id=PIPELINE))
    result = CliRunner().invoke(cli_app, ["inspect-document", RUN, "kb:doc-faq", "--db", str(db_path), "--pipeline", PIPELINE, "--format", "json"])
    assert result.exit_code == 0, result.output
    cli = json.loads(result.output)
    for other in (sdk, mcp, cli):
        assert other["rows"] == http["rows"]
        assert other["scope"] == http["scope"]
        assert other["findings"] == http["findings"]
        assert other["summary"] == http["summary"]
    terminal = CliRunner().invoke(cli_app, ["inspect-document", RUN, "kb:doc-faq", "--db", str(db_path), "--pipeline", PIPELINE])
    assert terminal.exit_code == 0 and "q-refund" in terminal.output and "relevant_delivered" in terminal.output


def test_storage_commands_migrate_and_index(db_path: Path) -> None:
    runner = CliRunner()
    migrated = runner.invoke(cli_app, ["storage", "migrate", "--db", str(db_path), "--no-backup"])
    assert migrated.exit_code == 0 and json.loads(migrated.output)["status"] == "already_current"
    ambiguous = runner.invoke(cli_app, ["storage", "index", RUN, "--db", str(db_path)])
    assert ambiguous.exit_code == 1 and "pipeline_required" in ambiguous.output
    indexed = runner.invoke(cli_app, ["storage", "index", RUN, "--db", str(db_path), "--pipeline", PIPELINE])
    assert indexed.exit_code == 0 and "Indexed 12 row(s) from 3 trace(s)" in indexed.output
    client, base = _client(db_path)
    assert _get(client, base, f"{RUN}/queries")["coverage"]["pairs"] == 12


def test_query_evidence_has_no_advisor_dependency_and_embeds_investigation(db_path: Path) -> None:
    assert "experimental." + "advisor" not in inspect.getsource(query_evidence_module)
    import asyncio

    async def _evidence(run_id: str) -> dict:
        store = SQLiteStore(str(db_path))
        return await build_query_evidence(store, db_id="golden", run_id=run_id, query_id="q-refund")

    evidence = asyncio.run(_evidence(OTHER_RUN))
    assert evidence["findings"] == [] and evidence["availability"]["findings"] == "unavailable"
    investigation = evidence["investigation"]
    assert investigation["scope"]["run_id"] == OTHER_RUN and investigation["scope"]["query_id"] == "q-refund"
    assert {_key(row) for row in investigation["rows"]} >= set(_expected("q-refund"))
    ambiguous = asyncio.run(_evidence(RUN))
    assert ambiguous["investigation"]["error"] == "pipeline_required"


def test_list_envelopes_carry_stored_stage_counts_once_projected(db_path: Path) -> None:
    client, base = _client(db_path)
    assert _get(client, base, f"{RUN}/queries")["stages"] is None
    _build(client, base)
    fields_ = tuple(EXPECTED_STAGE_COUNTS["dense"])
    for view in ("queries", "documents"):
        stages = {stage["op_id"]: stage for stage in _get(client, base, f"{RUN}/{view}")["stages"]}
        assert {op_id: {field: stage[field] for field in fields_} for op_id, stage in stages.items()} == EXPECTED_STAGE_COUNTS
        assert stages["rerank@lexical"]["operator_id"] == "rerank" and stages["expand"]["queries_skipped"] == 2
    assert _get(client, base, f"{RUN}/documents/{quote('kb:doc-faq', safe='')}")["stages"] is None


def test_query_detail_stages_carry_source_boundary_and_recorded_configuration(db_path: Path) -> None:
    """The stage panel opens the source boundary and recorded parameters (plan 2.1)."""
    client, base = _client(db_path)
    payload = _get(client, base, f"{RUN}/queries/q-refund")
    stages = {stage["op_id"]: stage for stage in payload["stages"]}
    assert "source_ref" in stages["rerank@dense"] and stages["rerank@dense"]["params"]["operator"] == "rerank"
    assert stages["expand"]["gate_values"] == {"expand": False}
