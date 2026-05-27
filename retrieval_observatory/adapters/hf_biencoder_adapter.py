from __future__ import annotations

import asyncio
import time
import warnings
from typing import Dict, List, Optional

from retrieval_observatory.types import Document, Query, RetrievalResult


class HFBiEncoderAdapter:
    """Dense retriever using a sentence-transformers bi-encoder + FAISS index.

    The corpus is encoded once on first retrieve() call and cached in memory.
    Suitable for corpora up to ~500k documents on a single machine.

    Requires: pip install retrieval-observatory[dense]
    """

    def __init__(
        self,
        corpus: Dict[str, str],
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        retriever_id: str = "hf_biencoder",
        batch_size: int = 64,
    ):
        self.retriever_id = retriever_id
        self._corpus = corpus
        self._model_name = model_name
        self._batch_size = batch_size
        self._doc_ids: Optional[List[str]] = None
        self._model = None
        self._index = None  # faiss.IndexFlatIP

    def _build_index(self) -> None:
        try:
            import faiss
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "HFBiEncoderAdapter requires sentence-transformers and faiss-cpu. "
                "Install with: pip install retrieval-observatory[dense]"
            ) from e

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"`resume_download` is deprecated and will be removed in version 1\.0\.0\.",
                category=FutureWarning,
                module=r"huggingface_hub\.file_download",
            )
            self._model = SentenceTransformer(self._model_name)
        self._doc_ids = list(self._corpus.keys())
        texts = [self._corpus[did] for did in self._doc_ids]

        embeddings = self._model.encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=len(texts) > 1000,
            convert_to_numpy=True,
        )

        dim = embeddings.shape[1]
        self._index = faiss.IndexFlatIP(dim)
        self._index.add(embeddings)

    def _retrieve_sync(self, query: Query) -> RetrievalResult:
        if self._index is None:
            self._build_index()

        start = time.perf_counter()
        query_vec = self._model.encode(
            [query.text],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        scores, indices = self._index.search(query_vec, query.k)
        latency_ms = (time.perf_counter() - start) * 1000

        documents = []
        for rank, (idx, score) in enumerate(zip(indices[0], scores[0]), start=1):
            if idx == -1:
                break
            doc_id = self._doc_ids[idx]
            documents.append(
                Document(
                    id=doc_id,
                    text=self._corpus[doc_id],
                    score=float(score),
                    rank=rank,
                )
            )

        return RetrievalResult(
            documents=documents,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
            profiling={"compute_ms": latency_ms, "network_ms": 0.0, "retries": 0.0},
        )

    async def retrieve(self, query: Query) -> RetrievalResult:
        return await asyncio.to_thread(self._retrieve_sync, query)
