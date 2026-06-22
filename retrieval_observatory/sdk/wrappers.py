from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional

from retrieval_observatory.types import Document, PipelineResult, Query, RetrievalResult, StageSnapshot

# Adapt plain Python callables / framework objects to the BaseRetriever / BaseReranker protocols
# the engine expects. The point of the SDK: an engineer wraps their existing pipeline with no YAML.


def _normalize_documents(
    raw: Any,
    corpus: Optional[Dict[str, str]] = None,
    source_docs: Optional[List[Document]] = None,
) -> List[Document]:
    """Normalize a retriever return value into ranked Documents.

    Accepts: list[doc_id], list[(doc_id, score)], list[Document], or list[dict].
    `source_docs` (rerank case) lets us recover text for plain-id returns.
    """
    corpus = corpus or {}
    by_id = {d.id: d for d in (source_docs or [])}

    def text_for(doc_id: str) -> str:
        if doc_id in by_id:
            return by_id[doc_id].text
        return corpus.get(doc_id, "")

    docs: List[Document] = []
    items = list(raw)
    n = len(items)
    for rank, item in enumerate(items, start=1):
        if isinstance(item, Document):
            item.rank = rank
            docs.append(item)
        elif isinstance(item, dict):
            doc_id = str(item.get("id") or item.get("doc_id"))
            docs.append(
                Document(
                    id=doc_id,
                    text=item.get("text", text_for(doc_id)),
                    score=float(item.get("score", n - rank + 1)),
                    rank=rank,
                    title=item.get("title", ""),
                    metadata=item.get("metadata", {}) or {},
                )
            )
        elif isinstance(item, (tuple, list)):
            doc_id, score = str(item[0]), float(item[1])
            docs.append(Document(id=doc_id, text=text_for(doc_id), score=score, rank=rank))
        else:  # plain id (str/int)
            doc_id = str(item)
            docs.append(Document(id=doc_id, text=text_for(doc_id), score=float(n - rank + 1), rank=rank))
    return docs


async def _call(fn: Callable, *args: Any) -> Any:
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args)
    return await asyncio.to_thread(fn, *args)


class FunctionRetriever:
    """Wrap a callable `fn(query_text) -> list[...]` as a retriever."""

    def __init__(self, fn: Callable, retriever_id: str, corpus: Optional[Dict[str, str]] = None):
        self.retriever_id = retriever_id
        self._fn = fn
        self._corpus = corpus

    async def retrieve(self, query: Query):
        start = time.perf_counter()
        raw = await _call(self._fn, query.text)
        # A monolithic pipeline can report its own per-stage breakdown; pass it straight through
        # so SingleStagePipeline preserves per-stage snapshots (Phase 2).
        if isinstance(raw, PipelineResult) or (
            isinstance(raw, list) and raw and all(isinstance(s, StageSnapshot) for s in raw)
        ):
            return raw
        latency_ms = (time.perf_counter() - start) * 1000
        documents = _normalize_documents(raw, corpus=self._corpus)
        return RetrievalResult(
            documents=documents,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
            profiling={"compute_ms": latency_ms, "network_ms": 0.0, "retries": 0.0},
        )


class FunctionReranker:
    """Wrap a callable `fn(query_text, documents) -> list[...]` as a reranker."""

    def __init__(self, fn: Callable, retriever_id: str, corpus: Optional[Dict[str, str]] = None):
        self.retriever_id = retriever_id
        self._fn = fn
        self._corpus = corpus

    async def rerank(self, query: Query, documents: List[Document]) -> RetrievalResult:
        start = time.perf_counter()
        raw = await _call(self._fn, query.text, documents)
        latency_ms = (time.perf_counter() - start) * 1000
        reranked = _normalize_documents(raw, corpus=self._corpus, source_docs=documents)
        return RetrievalResult(
            documents=reranked,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
            profiling={"compute_ms": latency_ms, "network_ms": 0.0, "retries": 0.0},
        )


def _is_langchain_retriever(obj: Any) -> bool:
    return hasattr(obj, "invoke") and hasattr(obj, "get_relevant_documents")


def _is_llamaindex_retriever(obj: Any) -> bool:
    return hasattr(obj, "retrieve") and hasattr(obj, "aretrieve") and not hasattr(obj, "retriever_id")


def as_retriever(
    obj: Any,
    corpus: Optional[Dict[str, str]] = None,
    retriever_id: Optional[str] = None,
    role: str = "retriever",
):
    """Coerce a callable / object / framework retriever into a retobs stage.

    - object already implementing `.retrieve`/`.rerank` -> passed through (id filled if missing)
    - LangChain / LlamaIndex retriever -> routed to the existing adapters
    - callable -> FunctionRetriever (role="retriever") or FunctionReranker (role="reranker")
    """
    rid = retriever_id or getattr(obj, "retriever_id", None) or getattr(obj, "__name__", None) or obj.__class__.__name__

    # Already a retobs stage.
    if hasattr(obj, "retrieve") or hasattr(obj, "rerank"):
        if _is_llamaindex_retriever(obj):
            from retrieval_observatory.adapters.llamaindex_adapter import LlamaIndexAdapter

            return LlamaIndexAdapter(obj, retriever_id=rid)
        if not getattr(obj, "retriever_id", None):
            try:
                obj.retriever_id = rid
            except (AttributeError, TypeError):
                pass
        return obj

    if _is_langchain_retriever(obj):
        from retrieval_observatory.adapters.langchain_adapter import LangChainAdapter

        return LangChainAdapter(obj, retriever_id=rid)

    if callable(obj):
        if role == "reranker":
            return FunctionReranker(obj, retriever_id=rid, corpus=corpus)
        return FunctionRetriever(obj, retriever_id=rid, corpus=corpus)

    raise TypeError(
        f"Cannot adapt {obj!r} to a retriever. Pass a callable, an object with "
        ".retrieve()/.rerank(), or a LangChain/LlamaIndex retriever."
    )
