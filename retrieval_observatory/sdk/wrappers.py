from __future__ import annotations

import asyncio
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from retrieval_observatory.sdk.observe import ObserveContext, current_trace, finish_trace, record_return_boundary, start_trace
from retrieval_observatory.tracing.candidates import observed_id
from retrieval_observatory.tracing.model import RetrievalTrace
from retrieval_observatory.types import Document, PipelineResult, Query, RetrievalResult, StageSnapshot

# Adapt plain Python callables / framework objects to the BaseRetriever / BaseReranker protocols
# the engine expects. The point of the SDK: an engineer wraps their existing pipeline with no YAML.


def _normalize_documents(
    raw: Any,
    corpus: Optional[Dict[str, str]] = None,
    source_docs: Optional[List[Document]] = None,
) -> List[Document]:
    """Normalize a retriever return value into ranked Documents.

    Accepts: list[doc_id], list[(doc_id, score)], list[Document], list[dict] with an id, or
    objects with an id attribute (the candidate id rule of ``tracing.candidates``). An item with
    no id raises ``TypeError``: neither its position nor its ``repr`` is ever scored as an id.
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
        elif _is_plain_id(item):
            doc_id = str(item)
            docs.append(Document(id=doc_id, text=text_for(doc_id), score=float(n - rank + 1), rank=rank))
        elif isinstance(item, (tuple, list)) and len(item) == 2 and _is_plain_id(item[0]):
            doc_id, score = str(item[0]), float(item[1])
            docs.append(Document(id=doc_id, text=text_for(doc_id), score=score, rank=rank))
        elif not isinstance(item, (tuple, list)) and (found := _result_id(item)) is not None:
            doc_id = str(found)
            get = item.get if isinstance(item, dict) else lambda key: getattr(item, key, None)
            text, score = get("text"), get("score")
            docs.append(
                Document(
                    id=doc_id,
                    text=text if isinstance(text, str) else text_for(doc_id),
                    score=float(n - rank + 1 if score is None else score),
                    rank=rank,
                    title=get("title") or "",
                    metadata=get("metadata") or {},
                )
            )
        else:
            raise TypeError(
                f"the callable returned {type(raw).__name__} of {n} items; item {rank} is a {type(item).__name__} with no id. "
                "Return ids, (id, score) pairs, dicts with id or doc_id, or objects with an id attribute."
            )
    return docs


def _is_plain_id(item: Any) -> bool:
    return isinstance(item, (str, int)) and not isinstance(item, bool)


def _result_id(item: Any) -> Any:
    """A returned item's id. A dict's ``id`` is read before its ``doc_id``, as evaluate always has:
    under ``--chunk-map`` that is the chunk id, not the document it belongs to."""
    if isinstance(item, dict) and item.get("id") not in (None, ""):
        return item["id"]
    return observed_id(item)


async def _call(fn: Callable, *args: Any) -> Any:
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args)
    return await asyncio.to_thread(fn, *args)


def _record_return_boundary(trace: RetrievalTrace, documents: Optional[List[Document]], error: Optional[str] = None) -> Optional[str]:
    """Append the callable's returned documents as the trace's final boundary (see
    ``sdk.observe.record_return_boundary``); ``Document.id`` is the candidate id. Returns the
    operator that emitted exactly the returned ids, which is then the trace's final step."""
    return record_return_boundary(trace, documents, error=error)


class FunctionRetriever:
    """Wrap a callable `fn(query_text) -> list[...]` as a retriever."""

    def __init__(
        self,
        fn: Callable,
        retriever_id: str,
        corpus: Optional[Dict[str, str]] = None,
        pipeline_id: Optional[str] = None,
    ):
        self.retriever_id = retriever_id
        self._fn = fn
        self._corpus = corpus
        # Set by ``evaluate`` when this wrapper is the whole pipeline: the callable then runs
        # under a trace of its own and its ``@observe`` spans become the run's trace.
        self.pipeline_id = pipeline_id

    async def retrieve(self, query: Query):
        if self.pipeline_id is None or current_trace() is not None:
            return await self._retrieve(query)
        trace = start_trace(ObserveContext(None, query.query_id, query.text, self.pipeline_id, "evaluation"))
        try:
            result = await self._retrieve(query)
        except Exception as exc:
            error = traceback.format_exc()
            _record_return_boundary(trace, None, f"{type(exc).__name__}: {exc}")
            finish_trace("ERROR", error)
            return PipelineResult(query.query_id, self.pipeline_id, [], trace.total_latency_ms, "ERROR", error, trace=trace)
        if not trace.spans or not isinstance(result, RetrievalResult):
            finish_trace()
            return result
        final = _record_return_boundary(trace, result.documents)
        finish_trace(final_op_ids=(final,) if final else ())
        corpus = self._corpus or {}
        snapshots = [
            StageSnapshot(
                stage_index=index,
                stage_id=span.op_id,
                documents=[Document(c.doc_id, corpus.get(c.doc_id, ""), c.score, c.rank) for c in span.outputs],
                latency_ms=span.latency_ms,
                candidate_count=len(span.outputs),
                op_type=span.op_type,
            )
            for index, span in enumerate(trace.spans)
        ]
        return PipelineResult(query.query_id, self.pipeline_id, snapshots, trace.total_latency_ms, "OK", trace=trace)

    async def _retrieve(self, query: Query):
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
    try:
        from langchain_core.retrievers import BaseRetriever
    except ImportError:
        BaseRetriever = None  # type: ignore[assignment]
    if BaseRetriever is not None and isinstance(obj, BaseRetriever):
        return True
    # langchain-core 1.x removed the public ``get_relevant_documents`` alias; the retriever
    # contract that survives every version is ``invoke`` plus ``_get_relevant_documents``.
    return hasattr(obj, "invoke") and (
        hasattr(obj, "_get_relevant_documents") or hasattr(obj, "get_relevant_documents")
    )


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
