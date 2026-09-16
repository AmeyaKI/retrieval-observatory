"""HFBiEncoderAdapter applies Query.filters['doc_ids'] without starving the result.

The index is a numpy stand-in for ``faiss.IndexFlatIP`` (same ``search`` contract, including
``-1`` padding when k exceeds the corpus) so the test needs neither faiss nor a model, and does
not load a second OpenMP runtime next to scikit-learn in the test process.
"""
from __future__ import annotations

import pytest

from retrieval_observatory.types import Query

np = pytest.importorskip("numpy")


class _FakeModel:
    def __init__(self, seed: int = 0):
        self._rng = np.random.default_rng(seed)

    def encode(self, texts, **kwargs):
        vectors = self._rng.standard_normal((len(texts), 8)).astype("float32")
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


class _FlatIP:
    """Exact inner-product search with faiss' (scores, indices) return shape."""

    def __init__(self, vectors):
        self._vectors = vectors
        self.searched_k: list[int] = []

    def search(self, query, k):
        self.searched_k.append(k)
        n = len(self._vectors)
        sims = query @ self._vectors.T
        order = np.argsort(-sims, axis=1)[:, : min(k, n)]
        scores = np.take_along_axis(sims, order, axis=1)
        if k > n:
            order = np.pad(order, ((0, 0), (0, k - n)), constant_values=-1)
            scores = np.pad(scores, ((0, 0), (0, k - n)), constant_values=-np.inf)
        return scores, order


def _adapter(n_docs: int = 200):
    from retrieval_observatory.adapters.hf_biencoder_adapter import HFBiEncoderAdapter

    corpus = {f"d{i}": f"text {i}" for i in range(n_docs)}
    adapter = HFBiEncoderAdapter(corpus, model_name="fake")
    adapter._model = _FakeModel()
    adapter._doc_ids = list(corpus)
    adapter._index = _FlatIP(adapter._model.encode(list(corpus.values())))
    return adapter


@pytest.mark.asyncio
async def test_doc_id_filter_returns_k_when_enough_allowed_docs_exist():
    adapter = _adapter()
    allowed = [f"d{i}" for i in range(100, 200)]

    result = await adapter.retrieve(Query("q", k=10, filters={"doc_ids": allowed}))

    assert len(result.documents) == 10
    assert all(doc.id in set(allowed) for doc in result.documents)
    assert [doc.rank for doc in result.documents] == list(range(1, 11))
    assert [doc.score for doc in result.documents] == sorted((doc.score for doc in result.documents), reverse=True)
    assert adapter._index.searched_k == [100]  # over-fetched once, no exhaustive pass needed


@pytest.mark.asyncio
async def test_doc_id_filter_falls_back_to_exhaustive_search_for_a_small_allow_list():
    adapter = _adapter(n_docs=2000)
    allowed = ["d5", "d777", "d1999"]

    result = await adapter.retrieve(Query("q", k=10, filters={"doc_ids": allowed}))

    assert sorted(doc.id for doc in result.documents) == sorted(allowed)
    assert adapter._index.searched_k == [100, 2000]


@pytest.mark.asyncio
async def test_unfiltered_query_is_unchanged():
    adapter = _adapter()
    result = await adapter.retrieve(Query("q", k=10))
    assert len(result.documents) == 10
    assert adapter._index.searched_k == [10]
    assert adapter.supports_filters is True
