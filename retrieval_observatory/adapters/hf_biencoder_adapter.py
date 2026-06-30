from __future__ import annotations

import asyncio
import hashlib
import pickle
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional

from retrieval_observatory.types import Document, Query, RetrievalResult

_DEFAULT_CACHE_DIR = Path.home() / ".retobs" / "faiss_cache"


class HFBiEncoderAdapter:
    """Dense retriever using a sentence-transformers bi-encoder + FAISS index.

    The corpus is encoded once on first retrieve() call and cached in memory.
    The FAISS index is persisted to disk (keyed by corpus+model hash) so
    subsequent runs skip re-encoding. Suitable for corpora up to ~500k docs.

    Note: Query.filters are not supported and will be silently ignored.

    Requires: pip install retrieval-observatory[dense]
    """

    supports_filters: bool = True

    def __init__(
        self,
        corpus: Dict[str, str],
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        retriever_id: str = "hf_biencoder",
        batch_size: int = 64,
        cache_dir: Optional[Path] = None,
    ):
        self.retriever_id = retriever_id
        self._corpus = corpus
        self._model_name = model_name
        self._batch_size = batch_size
        self._cache_dir = Path(cache_dir) if cache_dir else _DEFAULT_CACHE_DIR
        self._doc_ids: Optional[List[str]] = None
        self._model = None
        self._index = None  # faiss.IndexFlatIP

    def _corpus_cache_key(self) -> str:
        # Hash corpus content + model name so index is reused only for identical inputs
        h = hashlib.sha256()
        for doc_id in sorted(self._corpus.keys()):
            h.update(doc_id.encode())
            h.update(self._corpus[doc_id].encode())
        h.update(self._model_name.encode())
        return h.hexdigest()[:16]

    def _build_index(self) -> None:
        try:
            import faiss
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "HFBiEncoderAdapter requires sentence-transformers and faiss-cpu. "
                "Install with: pip install retrieval-observatory[dense]"
            ) from e

        cache_key = self._corpus_cache_key()
        index_path = self._cache_dir / f"{cache_key}.index"
        ids_path = self._cache_dir / f"{cache_key}.pkl"

        # Load from disk cache if available
        if index_path.exists() and ids_path.exists():
            self._index = faiss.read_index(str(index_path))
            with open(ids_path, "rb") as f:
                self._doc_ids = pickle.load(f)
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=FutureWarning)
                self._model = SentenceTransformer(self._model_name)
            return

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

        # Persist to disk for future runs
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(index_path))
        with open(ids_path, "wb") as f:
            pickle.dump(self._doc_ids, f)

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
        result = await asyncio.to_thread(self._retrieve_sync, query)
        if query.filters:
            doc_ids = query.filters.get("doc_ids")
            unsupported = set(query.filters) - {"doc_ids"}
            if unsupported:
                warnings.warn(
                    f"HFBiEncoderAdapter supports only Query.filters['doc_ids']; unsupported keys: {sorted(unsupported)}",
                    UserWarning,
                    stacklevel=2,
                )
            if doc_ids is not None:
                allowed = set(doc_ids)
                filtered_docs = [doc for doc in result.documents if doc.id in allowed]
                for rank, doc in enumerate(filtered_docs, start=1):
                    doc.rank = rank
                result.documents = filtered_docs[: query.k]
        return result
