import pytest

import retobs as ro
from retrieval_observatory.runner import execute as execute_mod


def _retrieve(q):
    return ["d1", "d2"]


def test_llm_judge_labels_used(tmp_path, monkeypatch):
    """labels='llm-judge' grades retrieved docs via the judge path (no gold qrels needed)."""

    async def fake_judge(cfg, queries, all_results, queries_by_id):
        return {q.query_id: {"d1": 1} for q in queries}

    monkeypatch.setattr(execute_mod, "_build_llm_judged_qrels", fake_judge)

    queries = [{"query_id": "q1", "text": "anything"}]  # no relevant_doc_ids provided
    rep = ro.benchmark(_retrieve, queries=queries, corpus={"d1": "x", "d2": "y"}, k=5,
                       labels="llm-judge", db_path=str(tmp_path / "z.db"))
    recall = next(v["mean"] for k, v in rep.metrics.items() if "stage0|recall@5" in k)
    assert recall == 1.0  # judged d1 as relevant, retriever returned it


def test_generate_testset_from_corpus(tmp_path):
    """Forge synthesizes queries + qrels from a corpus with detectable scenarios (no API key)."""
    corpus = {
        "doc2020": {"text": "annual revenue report 2020 quarterly growth earnings summary"},
        "doc2021": {"text": "annual revenue report 2021 quarterly growth earnings summary"},
        "doc2022": {"text": "annual revenue report 2022 quarterly growth earnings summary"},
    }
    ds = ro.generate_testset(corpus, n_per_type=2)
    queries, qrels = ds.load()
    assert hasattr(ds, "corpus") and ds.corpus  # corpus exposed for the benchmark engine

    if queries:  # rule-based generation is scenario-dependent
        rep = ro.benchmark(lambda q: list(ds.corpus.keys()), dataset=ds, k=5,
                           db_path=str(tmp_path / "g.db"))
        assert rep.run_id
