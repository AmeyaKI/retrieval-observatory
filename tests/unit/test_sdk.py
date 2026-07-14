import pytest

import retrieval_observatory as ro
from retrieval_observatory.sdk.wrappers import FunctionReranker, FunctionRetriever
from retrieval_observatory.types import Document, Query


def test_public_import():
    import retrieval_observatory

    assert retrieval_observatory.benchmark is ro.benchmark
    from retrieval_observatory.tracing.integrations.langchain import RetobsLangChainCallback  # noqa: F401

CORPUS = {"d1": "cats and kittens", "d2": "space rockets", "d3": "feline pets", "d4": "stock market"}
QUERIES = [
    {"query_id": "q1", "text": "cats", "relevant_doc_ids": ["d1", "d3"]},
    {"query_id": "q2", "text": "rockets", "relevant_doc_ids": ["d2"]},
]


def _retrieve(q):
    hits = [d for d, t in CORPUS.items() if any(w in t for w in q.split())]
    return hits or ["d1"]


# ---- wrapper normalization -------------------------------------------------

@pytest.mark.asyncio
async def test_function_retriever_id_shape():
    r = FunctionRetriever(lambda q: ["d2", "d1"], retriever_id="r", corpus=CORPUS)
    res = await r.retrieve(Query(text="x", k=5, query_id="q"))
    assert [d.id for d in res.documents] == ["d2", "d1"]
    assert [d.rank for d in res.documents] == [1, 2]
    assert res.documents[0].text == "space rockets"  # text filled from corpus
    assert res.documents[0].score > res.documents[1].score  # rank-implied scores descend


@pytest.mark.asyncio
async def test_function_retriever_tuple_and_document_shapes():
    r = FunctionRetriever(lambda q: [("d1", 0.9), ("d2", 0.3)], retriever_id="r", corpus=CORPUS)
    res = await r.retrieve(Query(text="x", k=5, query_id="q"))
    assert res.documents[0].score == 0.9 and res.documents[1].score == 0.3

    docs = [Document(id="d3", text="t", score=0.5, rank=99)]
    r2 = FunctionRetriever(lambda q: docs, retriever_id="r", corpus=CORPUS)
    res2 = await r2.retrieve(Query(text="x", k=5, query_id="q"))
    assert res2.documents[0].rank == 1  # rank is reassigned


@pytest.mark.asyncio
async def test_function_reranker_recovers_text_from_source_docs():
    source = [Document(id="d1", text="cats and kittens", score=1.0, rank=1)]
    rr = FunctionReranker(lambda q, docs: ["d1"], retriever_id="rr")
    res = await rr.rerank(Query(text="cats", k=5, query_id="q"), source)
    assert res.documents[0].text == "cats and kittens"


@pytest.mark.asyncio
async def test_async_callable_supported():
    async def aretrieve(q):
        return ["d1", "d2"]

    r = FunctionRetriever(aretrieve, retriever_id="r", corpus=CORPUS)
    res = await r.retrieve(Query(text="x", k=5, query_id="q"))
    assert [d.id for d in res.documents] == ["d1", "d2"]


# ---- end-to-end benchmark --------------------------------------------------

def test_benchmark_inmemory_metrics(tmp_path):
    db = str(tmp_path / "sdk.db")
    rep = ro.benchmark(_retrieve, queries=QUERIES, corpus=CORPUS, k=5, db_path=db)
    assert rep.run_id
    assert rep.pipeline_ids == ["_retrieve"]
    recall = next(v for kk, v in rep.metrics.items() if kk.endswith("recall@5") and "stage0" in kk)
    assert recall["mean"] == pytest.approx(0.75)  # q1 finds 1/2 rel, q2 finds 1/1 -> mean 0.75


def test_evaluate_report_contract_and_artifacts(tmp_path):
    db = str(tmp_path / "sdk.db")
    rep = ro.evaluate(_retrieve, queries=QUERIES, corpus=CORPUS, k=5, db_path=db)
    payload = rep.to_dict()
    assert payload["schema_version"] == 1
    assert payload["run_id"] == rep.run_id
    assert payload["verdict"] in {"needs_attention", "no_diagnosed_failures", "partial"}
    assert payload["dashboard_url"].endswith(f"#/runs/{rep.run_id}/overview")
    assert "Evidence" in rep.to_markdown()
    assert "<!doctype html>" in rep.to_html()
    assert rep.write(tmp_path / "report.json").exists()
    assert rep.write(tmp_path / "report.md").exists()
    assert rep.write(tmp_path / "report.html").exists()
    config_path = rep.export_config(tmp_path / "effective.yaml")
    assert "experiment:" in config_path.read_text(encoding="utf-8")


def test_sdk_compare_uses_validity_gate(tmp_path):
    db = str(tmp_path / "sdk.db")
    baseline = ro.evaluate(_retrieve, queries=QUERIES, corpus=CORPUS, k=5, db_path=db, name="same")
    candidate = ro.evaluate(_retrieve, queries=QUERIES, corpus=CORPUS, k=5, db_path=db, name="same")
    comparison = candidate.compare(baseline)
    assert comparison["baseline_run_id"] == baseline.run_id
    assert comparison["candidate_run_id"] == candidate.run_id
    assert comparison["validity"]["decision_allowed"] is True
    assert all(result["decision"] == "no_decision" for result in comparison["results"].values())


def test_benchmark_multistage_per_stage_snapshots(tmp_path):
    db = str(tmp_path / "sdk.db")

    def rerank(q, docs):
        return list(reversed([d.id for d in docs]))

    rep = ro.benchmark([_retrieve, rerank], queries=QUERIES, corpus=CORPUS, k=5, db_path=db)
    keys = set(rep.metrics)
    # I1: per-stage snapshots exist for both stages plus the end-to-end (stage-1) row.
    assert any("stage0|recall@5" in k for k in keys)
    assert any("stage1|recall@5" in k for k in keys)
    assert any("stage-1|" in k for k in keys)


@pytest.mark.asyncio
async def test_lineage_written(tmp_path):
    from retrieval_observatory.store.sqlite import SQLiteStore

    db = str(tmp_path / "sdk.db")
    rep = ro.benchmark(_retrieve, queries=QUERIES, corpus=CORPUS, k=5, db_path=db)

    store = SQLiteStore(db_path=db)
    run_queries = await store.get_run_queries(rep.run_id)
    assert {r["query_id"] for r in run_queries} == {"q1", "q2"}  # I3: run_queries persisted

    lineage = await store.get_query_lineage("q1")
    run_ids = [e.get("run_id") for e in lineage.get("evaluations", [])]
    assert rep.run_id in run_ids


def test_benchmark_with_query_objects_and_explicit_qrels(tmp_path):
    db = str(tmp_path / "sdk.db")
    queries = [Query(text="cats", query_id="q1"), Query(text="rockets", query_id="q2")]
    qrels = {"q1": ["d1", "d3"], "q2": {"d2": 1}}
    rep = ro.benchmark(_retrieve, queries=queries, corpus=CORPUS, qrels=qrels, k=5, db_path=db)
    recall = next(v for kk, v in rep.metrics.items() if kk.endswith("recall@5") and "stage0" in kk)
    assert recall["mean"] == pytest.approx(0.75)


def test_determinism_same_pipeline(tmp_path):
    """The shared executor yields identical aggregates for identical inputs (parity guard)."""
    db = str(tmp_path / "sdk.db")
    rep1 = ro.benchmark(_retrieve, queries=QUERIES, corpus=CORPUS, k=5, name="p", db_path=db)
    rep2 = ro.benchmark(_retrieve, queries=QUERIES, corpus=CORPUS, k=5, name="p", db_path=db)
    quality1 = {k: v["mean"] for k, v in rep1.metrics.items() if "latency" not in k and "profile" not in k}
    quality2 = {k: v["mean"] for k, v in rep2.metrics.items() if "latency" not in k and "profile" not in k}
    assert quality1 == quality2
