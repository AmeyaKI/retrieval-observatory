from __future__ import annotations

import time
from typing import Dict, List, Optional

from retrieval_observatory.types import Document, Query, RetrievalResult


class BM25Adapter:
    """In-process BM25 retriever backed by rank_bm25.BM25Okapi.

    Index is built lazily on first retrieve() call.
    CPU-bound — runs synchronously (wrap in to_thread for async contexts).

    tokenizer options:
      "whitespace" (default) — simple text.lower().split(); fastest, weakest recall.
      "nltk"                 — Porter stemming + English stopword removal; ~5% better
                               Recall@10 on BEIR vs whitespace; requires nltk package.
    """

    def __init__(
        self,
        corpus: Dict[str, str],
        retriever_id: str = "bm25",
        tokenizer: str = "whitespace",
    ):
        self.retriever_id = retriever_id
        self._corpus = corpus
        self._tokenizer = tokenizer
        self._doc_ids: Optional[List[str]] = None
        self._bm25 = None
        self._stemmer = None
        self._stopwords: Optional[set] = None

    def _build_index(self) -> None:
        try:
            from rank_bm25 import BM25Okapi
        except ImportError as e:
            raise ImportError(
                "BM25Adapter requires rank-bm25. "
                "Install with: pip install retobs[demo]"
            ) from e

        if self._tokenizer == "nltk":
            self._init_nltk()

        self._doc_ids = list(self._corpus.keys())
        tokenized = [self._tokenize(self._corpus[did]) for did in self._doc_ids]
        self._bm25 = BM25Okapi(tokenized)

    def _init_nltk(self) -> None:
        try:
            from nltk.stem import PorterStemmer
            import nltk
        except ImportError as e:
            raise ImportError(
                "BM25Adapter tokenizer='nltk' requires nltk. "
                "Install with: pip install nltk"
            ) from e
        for resource in ("stopwords", "punkt_tab"):
            try:
                nltk.data.find(f"corpora/{resource}" if resource == "stopwords" else f"tokenizers/{resource}")
            except LookupError:
                nltk.download(resource, quiet=True)
        from nltk.corpus import stopwords
        self._stemmer = PorterStemmer()
        self._stopwords = set(stopwords.words("english"))

    def _tokenize(self, text: str) -> List[str]:
        if self._tokenizer == "nltk" and self._stemmer is not None:
            tokens = text.lower().split()
            return [
                self._stemmer.stem(t)
                for t in tokens
                if t.isalpha() and t not in self._stopwords
            ]
        return text.lower().split()

    def retrieve(self, query: Query) -> RetrievalResult:
        if self._bm25 is None:
            self._build_index()

        start = time.perf_counter()
        scores = self._bm25.get_scores(self._tokenize(query.text))
        latency_ms = (time.perf_counter() - start) * 1000

        # Sort by score descending, take top-k
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[: query.k]

        documents = [
            Document(
                id=self._doc_ids[i],
                text=self._corpus[self._doc_ids[i]],
                score=float(scores[i]),
                rank=rank,
            )
            for rank, i in enumerate(top_indices, start=1)
        ]

        return RetrievalResult(
            documents=documents,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
            profiling={"compute_ms": latency_ms, "network_ms": 0.0, "retries": 0.0},
        )
