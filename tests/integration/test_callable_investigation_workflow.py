"""``ro.evaluate(callable)`` runs an instrumented callable once per query, keeps its actual
operator DAG as the run's trace, records the returned result as the final boundary, and
writes the investigation projection so ``inspect_query``/``inspect_document`` answer."""

from __future__ import annotations

import asyncio

import pytest
from typer.testing import CliRunner

import retrieval_observatory as ro
from retrieval_observatory.cli import app as cli_app
from retrieval_observatory.datasets.judgments import EvaluationSpec, JudgmentSet
from retrieval_observatory.evidence import service as investigation_service
from retrieval_observatory.sdk.observe import observe
from retrieval_observatory.store.base import InvestigationScope, TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.capture import CaptureSpec

CORPUS = {"d1": "alpha one", "d2": "alpha two", "d3": "alpha three", "d4": "beta four", "d5": "alpha five"}
QUERIES = [
    {"query_id": "q1", "text": "alpha"},
    {"query_id": "q2", "text": "beta"},
]
QRELS = {"q1": {"d1": 1, "d2": 1, "d3": 1, "d5": 0}, "q2": {"d4": 1, "d2": 1}}
METRICS = {"recall_at_k": [3]}
SPEC = EvaluationSpec(unit="document", k=3)


def _hits(*doc_ids: str) -> list[dict]:
    return [{"doc_id": doc_id, "score": float(len(doc_ids) - rank)} for rank, doc_id in enumerate(doc_ids)]


class HybridSearch:
    """Two sources, a fuse, a reranker that drops ``d2``, and an untraced post-filter that drops ``d3``."""

    def __init__(self) -> None:
        self.calls = 0

    @observe("SOURCE", op_id="keyword")
    def keyword(self, query: str) -> list[dict]:
        return _hits("d1", "d2", "d3")

    @observe("SOURCE", op_id="dense")
    def dense(self, query: str) -> list[dict]:
        return _hits("d3", "d5", "d4")

    @observe("FUSE", op_id="fuse", parent_ids=("keyword", "dense"))
    def fuse(self, keyword: list[dict], dense: list[dict]) -> list[dict]:
        return _hits(*dict.fromkeys(hit["doc_id"] for hit in [*keyword, *dense]))

    @observe("RERANK", op_id="rerank", parent_ids=("fuse",))
    def rerank(self, query: str, fuse: list[dict]) -> list[dict]:
        return _hits(*(hit["doc_id"] for hit in fuse if hit["doc_id"] != "d2"))

    def search(self, query: str) -> list[dict]:
        self.calls += 1
        ranked = self.rerank(query, self.fuse(self.keyword(query), self.dense(query)))
        return [hit for hit in ranked if hit["doc_id"] != "d3"]


async def _read(db_path, run_id: str, pipeline_id: str):
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    traces = await store.list_traces(TraceQuery(run_id=run_id))
    projection = await store.get_investigation_projection(InvestigationScope(run_id, pipeline_id, SPEC.digest()))
    return {trace.query_id: trace for trace in traces}, projection


def _rows(run_id: str, query_id: str, db_path) -> dict[str, dict]:
    rows = ro.inspect_query(run_id, query_id, db_path=str(db_path))["investigation"]["rows"]
    return {row["entity_id"]: row for row in rows}


def test_plain_python_class_pipeline_keeps_internal_dag_and_projection(tmp_path) -> None:
    db_path = tmp_path / "hybrid.db"
    service = HybridSearch()
    report = ro.evaluate(service.search, queries=QUERIES, corpus=CORPUS, qrels=QRELS, k=3, metrics=METRICS, db_path=str(db_path), name="hybrid")

    assert service.calls == 2
    traces, projection = asyncio.run(_read(db_path, report.run_id, "hybrid"))
    trace = traces["q1"]
    assert [span.op_id for span in trace.spans] == ["keyword", "dense", "fuse", "rerank", "return"]
    returned = trace.span("return")
    assert returned.op_type == "TRANSFORM" and returned.parent_ids == ("rerank",)
    assert returned.params == {"boundary": "callable_return"}
    assert [candidate.doc_id for candidate in returned.outputs] == ["d1", "d5", "d4"]
    assert trace.final_op_ids == ("return",)
    assert projection["status"] == "complete"
    assert report.manifest["investigation_projection"]["hybrid"]["status"] == "complete"

    rows = _rows(report.run_id, "q1", db_path)
    assert rows["d1"]["outcome"] == "relevant_delivered"
    assert rows["d2"]["outcome"] == "relevant_excluded" and rows["d2"]["loss_boundary"] == "rerank"
    assert rows["d3"]["outcome"] == "relevant_excluded" and rows["d3"]["loss_boundary"] == "return"
    assert rows["d5"]["outcome"] == "judged_nonrelevant"

    document = ro.inspect_document(report.run_id, "default:d2", db_path=str(db_path))
    assert sorted(row["query_id"] for row in document["rows"]) == ["q1", "q2"]
    assert all(row["outcome"] == "relevant_excluded" for row in document["rows"])


def test_multi_branch_async_callable_uses_actual_inputs(tmp_path) -> None:
    calls = []

    class AsyncHybrid:
        @observe("SOURCE", op_id="a")
        async def a(self, query: str) -> list[dict]:
            await asyncio.sleep(0)
            return _hits("d1", "d2")

        @observe("SOURCE", op_id="b")
        async def b(self, query: str) -> list[dict]:
            await asyncio.sleep(0)
            return _hits("d4", "d2")

        @observe(
            "FUSE",
            op_id="fuse",
            parent_ids=("a", "b"),
            capture=CaptureSpec(inputs=lambda bound: {"a": bound.arguments["a"], "b": bound.arguments["b"]}),
        )
        def fuse(self, a: list[dict], b: list[dict]) -> list[dict]:
            return _hits(*dict.fromkeys(hit["doc_id"] for hit in [*a, *b]))

        async def search(self, query: str) -> list[dict]:
            calls.append(query)
            lanes = await asyncio.gather(self.a(query), self.b(query))
            return self.fuse(*lanes)

    db_path = tmp_path / "async.db"
    report = ro.evaluate(AsyncHybrid().search, queries=QUERIES, corpus=CORPUS, qrels=QRELS, k=3, metrics=METRICS, db_path=str(db_path), name="async")

    assert sorted(calls) == ["alpha", "beta"]  # once per query; the scheduler picks the order
    traces, projection = asyncio.run(_read(db_path, report.run_id, "async"))
    assert projection["status"] == "complete"
    for trace in traces.values():
        assert {span.op_id for span in trace.spans} == {"a", "b", "fuse"}
        fuse = trace.span("fuse")
        assert fuse.input_capture == "recorded" and set(fuse.input_groups) == {"a", "b"}
        assert trace.final_op_ids == ("fuse",)  # the return is exactly the fuse output


def test_uninstrumented_callable_still_evaluates_with_linear_trace(tmp_path) -> None:
    def plain(query: str) -> list[str]:
        return ["d1", "d4"]

    db_path = tmp_path / "plain.db"
    report = ro.evaluate(plain, queries=QUERIES, corpus=CORPUS, qrels=QRELS, k=3, metrics=METRICS, db_path=str(db_path))

    traces, projection = asyncio.run(_read(db_path, report.run_id, "plain"))
    assert projection["status"] == "complete"
    for trace in traces.values():
        assert [(span.op_id, span.op_type) for span in trace.spans] == [("plain", "SOURCE")]
    rows = _rows(report.run_id, "q1", db_path)
    assert rows["d1"]["outcome"] == "relevant_delivered"
    assert rows["d2"]["outcome"] == "not_observed"


def test_failed_query_is_persisted_with_attempt_accounting(tmp_path) -> None:
    def flaky(query: str) -> list[str]:
        if query == "beta":
            raise RuntimeError("index unavailable")
        return ["d1"]

    db_path = tmp_path / "flaky.db"
    report = ro.evaluate(flaky, queries=QUERIES, corpus=CORPUS, qrels=QRELS, k=3, metrics=METRICS, db_path=str(db_path))

    traces, projection = asyncio.run(_read(db_path, report.run_id, "flaky"))
    failed = traces["q2"]
    assert failed.status == "ERROR" and "index unavailable" in failed.error_traceback
    assert traces["q1"].status == "OK"
    counts = report.manifest["counts"]
    assert (counts["attempted"], counts["completed"]) == (2, 1)
    assert projection["status"] == "complete"
    rows = _rows(report.run_id, "q2", db_path)
    assert rows and all(row["final_membership"] == "unknown" for row in rows.values())


def test_provenance_and_judgment_records_are_recorded_not_invented(tmp_path) -> None:
    def plain(query: str) -> list[str]:
        return ["d1"]

    db_path = tmp_path / "provenance.db"
    report = ro.evaluate(
        plain,
        queries=QUERIES,
        corpus=CORPUS,
        qrels=QRELS,
        k=3,
        db_path=str(db_path),
        provenance={"service_id": "support-search", "corpus_revision": "corpus-7"},
    )
    manifest = report.manifest
    identity = manifest["release_identity"]
    assert identity["service_id"] == "support-search" and identity["corpus_revision"] == "corpus-7"
    assert identity["deployment_revision"] is None and identity["index_build_id"] is None

    records = manifest["judgment_records"]
    assert JudgmentSet.from_records(records).to_records() == JudgmentSet.from_qrels(QRELS).to_records()
    assert next(record for record in records if record["entity_id"] == "d5")["grade"] == 0
    assert manifest["judgment_digest"] == JudgmentSet.from_qrels(QRELS).digest()
    assert manifest["evaluation"]["unit"] == "document" and manifest["evaluation"]["k"] == 3

    with pytest.raises(ValueError, match="deployment_sha"):
        ro.evaluate(plain, queries=QUERIES, corpus=CORPUS, qrels=QRELS, db_path=str(db_path), provenance={"deployment_sha": "x"})


def test_projection_failure_is_visible_and_repairable(tmp_path, monkeypatch) -> None:
    async def broken(*args, **kwargs):
        raise RuntimeError("projection tables locked")

    monkeypatch.setattr(investigation_service, "build_projection", broken)

    def plain(query: str) -> list[str]:
        return ["d1"]

    db_path = tmp_path / "repair.db"
    report = ro.evaluate(plain, queries=QUERIES, corpus=CORPUS, qrels=QRELS, k=3, metrics=METRICS, db_path=str(db_path))
    status = report.manifest["investigation_projection"]["plain"]
    assert status["status"] == "failed" and "projection tables locked" in status["error"]
    assert status["repair"] == f"retobs storage index {report.run_id} --db {db_path}"
    _, projection = asyncio.run(_read(db_path, report.run_id, "plain"))
    assert projection is None

    monkeypatch.undo()
    result = CliRunner().invoke(cli_app, ["storage", "index", report.run_id, "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    _, projection = asyncio.run(_read(db_path, report.run_id, "plain"))
    assert projection["status"] == "complete"


def test_supported_framework_fixture_still_evaluates(tmp_path) -> None:
    pytest.importorskip("langchain_core")
    from langchain_core.documents import Document as LCDocument
    from langchain_core.retrievers import BaseRetriever

    class TinyRetriever(BaseRetriever):
        def _get_relevant_documents(self, query: str, *, run_manager=None) -> list[LCDocument]:
            return [LCDocument(page_content=CORPUS[doc_id], metadata={"id": doc_id}) for doc_id in ("d1", "d4")]

    db_path = tmp_path / "langchain.db"
    report = ro.evaluate(TinyRetriever(), queries=QUERIES, corpus=CORPUS, qrels=QRELS, k=3, metrics=METRICS, db_path=str(db_path), name="lc")

    traces, projection = asyncio.run(_read(db_path, report.run_id, "lc"))
    assert set(traces) == {"q1", "q2"} and all(trace.status == "OK" for trace in traces.values())
    assert projection["status"] == "complete"


def test_investigation_cutoff_follows_the_callers_k_not_the_first_recall_cutoff(tmp_path) -> None:
    """``evaluate(k=3)`` with the default metrics (recall@1/5/10) must project at k=3, not k=1."""
    def plain(query: str) -> list[str]:
        return ["d1", "d4", "d2"]

    db_path = tmp_path / "cutoff.db"
    report = ro.evaluate(plain, queries=QUERIES, corpus=CORPUS, qrels=QRELS, k=3, db_path=str(db_path))

    assert report.manifest["evaluation"]["k"] == 3
    _, projection = asyncio.run(_read(db_path, report.run_id, "plain"))
    assert projection is not None and projection["status"] == "complete"
    envelope = ro.inspect_query(report.run_id, "q1", db_path=str(db_path))["investigation"]
    assert envelope["scope"]["k"] == 3
    assert not any(finding["code"] == "k_defaulted" and "1" == finding["detail"].split()[-1] for finding in envelope["findings"])
    rows = {row["entity_id"]: row for row in envelope["rows"]}
    assert rows["d2"]["final_rank"] == 3 and rows["d2"]["final_membership"] == "included"
