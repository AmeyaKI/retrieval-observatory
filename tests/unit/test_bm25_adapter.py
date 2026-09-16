from retrieval_observatory.types import Query

TINY_CORPUS = {
    "doc1": "Python is a programming language used for data science and machine learning.",
    "doc2": "Machine learning uses statistical methods to learn from data.",
    "doc3": "Retrieval-augmented generation improves LLM accuracy.",
    "doc4": "Vector databases store embeddings efficiently for similarity search.",
    "doc5": "BM25 is a bag-of-words ranking function used in information retrieval.",
}


def test_bm25_adapter_basic():
    from retrieval_observatory.adapters.bm25_adapter import BM25Adapter

    adapter = BM25Adapter(corpus=TINY_CORPUS, retriever_id="test_bm25")
    # "python", "is", "used", "for", "data" together hit doc1, doc4 and doc5 (whitespace tokens).
    query = Query(text="Python is used for data", k=3, query_id="q1")
    result = adapter.retrieve(query)

    assert result.retriever_id == "test_bm25"
    assert len(result.documents) == 3
    assert result.latency_ms > 0
    # doc1 mentions Python directly — should be near top
    top_ids = [d.id for d in result.documents[:2]]
    assert "doc1" in top_ids


def test_bm25_returns_k_docs():
    from retrieval_observatory.adapters.bm25_adapter import BM25Adapter

    adapter = BM25Adapter(corpus=TINY_CORPUS)
    # "is a" occurs in doc1 and doc5 — enough matches to fill k=2.
    result = adapter.retrieve(Query(text="is a", k=2, query_id="q1"))
    assert len(result.documents) == 2


def test_bm25_never_pads_with_non_matching_docs():
    """Only documents sharing a term with the query are candidates; k is an upper bound."""
    from retrieval_observatory.adapters.bm25_adapter import BM25Adapter

    corpus = {f"filler{i}": f"lorem ipsum {i} filler text" for i in range(18)}
    corpus["hit1"] = "zebra quokka habitat"
    corpus["hit2"] = "the zebra crossing"
    adapter = BM25Adapter(corpus=corpus)

    result = adapter.retrieve(Query(text="zebra", k=10, query_id="q1"))

    assert sorted(d.id for d in result.documents) == ["hit1", "hit2"]
    assert all(d.score > 0 for d in result.documents)
    assert [d.rank for d in result.documents] == [1, 2]
    assert adapter.retrieve(Query(text="unicorn", k=10, query_id="q2")).documents == []


def test_bm25_ranks_are_1indexed():
    from retrieval_observatory.adapters.bm25_adapter import BM25Adapter

    adapter = BM25Adapter(corpus=TINY_CORPUS)
    result = adapter.retrieve(Query(text="retrieval", k=5, query_id="q1"))
    ranks = [d.rank for d in result.documents]
    assert ranks == list(range(1, len(ranks) + 1))


def test_bm25_does_not_require_rank_bm25(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "rank_bm25", None)
    from retrieval_observatory.adapters.bm25_adapter import BM25Adapter

    adapter = BM25Adapter(corpus=TINY_CORPUS)
    result = adapter.retrieve(Query(text="is a used for", k=3, query_id="q1"))
    assert len(result.documents) == 3
