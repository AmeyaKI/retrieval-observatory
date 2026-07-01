from __future__ import annotations

import math
import time
import warnings
from collections import Counter
from typing import Dict, List, Optional

from retrieval_observatory.types import Document, Query, RetrievalResult


class BM25Adapter:
    """In-process BM25 retriever.

    Index is built lazily on first retrieve() call.
    CPU-bound — runs synchronously (wrap in to_thread for async contexts).

    tokenizer options:
      "whitespace" (default) — simple text.lower().split(); fastest, weakest recall.
      "nltk"                 — Porter stemming + English stopword removal; ~5% better
                               Recall@10 on BEIR vs whitespace; requires nltk package.

    Note: only Query.filters['doc_ids'] is enforced in-process. Other filter keys emit
    a warning and are ignored.
    """

    supports_filters: bool = True

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
        if self._tokenizer == "nltk":
            self._init_nltk()

        self._doc_ids = list(self._corpus.keys())
        tokenized = [self._tokenize(self._corpus[did]) for did in self._doc_ids]
        self._bm25 = _SimpleBM25(tokenized)

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
        assert self._bm25 is not None and self._doc_ids is not None  # set by _build_index

        start = time.perf_counter()
        scores = self._bm25.get_scores(self._tokenize(query.text))
        latency_ms = (time.perf_counter() - start) * 1000

        # Sort by score descending, take top-k
        filtered_ids = None
        if query.filters:
            filtered_ids = query.filters.get("doc_ids")
            unsupported = set(query.filters) - {"doc_ids"}
            if unsupported:
                warnings.warn(
                    f"BM25Adapter supports only Query.filters['doc_ids']; unsupported keys: {sorted(unsupported)}",
                    UserWarning,
                    stacklevel=2,
                )

        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        if filtered_ids is not None:
            allowed = set(filtered_ids)
            ranked_indices = [idx for idx in ranked_indices if self._doc_ids[idx] in allowed]
        top_indices = ranked_indices[: query.k]

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


class _SimpleBM25:
    def __init__(self, tokenized_documents: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self._documents = tokenized_documents
        self._k1 = k1
        self._b = b
        self._doc_lengths = [len(doc) for doc in tokenized_documents]
        self._avg_doc_length = sum(self._doc_lengths) / len(self._doc_lengths) if self._doc_lengths else 0.0
        self._term_frequencies = [Counter(doc) for doc in tokenized_documents]
        document_frequency: Counter[str] = Counter()
        for doc in tokenized_documents:
            document_frequency.update(set(doc))
        n_docs = len(tokenized_documents)
        self._idf = {
            term: math.log(1 + (n_docs - freq + 0.5) / (freq + 0.5))
            for term, freq in document_frequency.items()
        }

    def get_scores(self, query_tokens: List[str]) -> List[float]:
        scores: List[float] = []
        for idx, term_frequency in enumerate(self._term_frequencies):
            doc_length = self._doc_lengths[idx]
            score = 0.0
            for term in query_tokens:
                tf = term_frequency.get(term, 0)
                if tf == 0:
                    continue
                idf = self._idf.get(term, 0.0)
                denominator = tf + self._k1 * (
                    1 - self._b + self._b * doc_length / (self._avg_doc_length or 1.0)
                )
                score += idf * (tf * (self._k1 + 1)) / denominator
            scores.append(score)
        return scores
