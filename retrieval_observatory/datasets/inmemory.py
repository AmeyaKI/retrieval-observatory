from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Sequence, Tuple, Union

from retrieval_observatory.types import Document, Query

# Bring-your-own dataset from in-memory Python objects (lists/dicts), for the SDK path.
# Mirrors the (queries, qrels) + .corpus / .corpus_documents surface that CustomDataset exposes,
# so it drops straight into the shared execute_benchmark core.

QueryInput = Union[Query, dict, str]
CorpusInput = Union[Dict[str, str], Dict[str, Document], Sequence[dict], None]
QrelsInput = Optional[Dict[str, Union[Sequence[str], Dict[str, int]]]]


class InMemoryDataset:
    def __init__(
        self,
        queries: Sequence[QueryInput],
        corpus: CorpusInput = None,
        qrels: QrelsInput = None,
        k: int = 10,
    ):
        self.k = k
        self._queries, self._inline_qrels = _normalize_queries(queries, k)
        self._explicit_qrels = _normalize_qrels(qrels) if qrels else {}
        self._corpus, self._corpus_documents = _normalize_corpus(corpus)

    @property
    def corpus(self) -> Dict[str, str]:
        return self._corpus

    @property
    def corpus_documents(self) -> Dict[str, Document]:
        return self._corpus_documents

    def load(self) -> Tuple[List[Query], Dict[str, Dict[str, int]]]:
        qrels = dict(self._inline_qrels)
        qrels.update(self._explicit_qrels)
        return self._queries, qrels


def _content_stable_id(text: str, seen: Dict[str, int]) -> str:
    """Content-derived query id: same query text -> same id across two separate calls
    (e.g. two benchmark runs against the same in-memory query list), unlike a positional
    fallback (`f"q{i}"`) which silently aliases unrelated queries whenever the list is
    resampled, filtered, or reordered between runs. Ties within one call (duplicate query
    text) get a numeric suffix so ids stay unique within the batch."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    base = f"q_{digest}"
    count = seen.get(base, 0)
    seen[base] = count + 1
    return base if count == 0 else f"{base}_{count}"


def _normalize_queries(
    queries: Sequence[QueryInput], k: int
) -> Tuple[List[Query], Dict[str, Dict[str, int]]]:
    out: List[Query] = []
    qrels: Dict[str, Dict[str, int]] = {}
    seen_ids: Dict[str, int] = {}
    for item in queries:
        if isinstance(item, Query):
            q = item
            if not q.query_id:
                q.query_id = _content_stable_id(q.text, seen_ids)
            q.k = k
            out.append(q)
            continue
        if isinstance(item, str):
            out.append(Query(text=item, k=k, query_id=_content_stable_id(item, seen_ids)))
            continue
        if isinstance(item, dict):
            query_id = str(item.get("query_id") or _content_stable_id(item["text"], seen_ids))
            out.append(
                Query(
                    text=item["text"],
                    k=k,
                    query_id=query_id,
                    filters=item.get("filters", {}),
                    metadata=item.get("metadata", {}) or {},
                )
            )
            rel = item.get("relevant_doc_ids")
            if rel is not None:
                qrels[query_id] = _grade_map(rel)
            continue
        raise TypeError(f"Unsupported query item type: {type(item)!r}")
    return out, qrels


def _normalize_qrels(qrels: Dict[str, Union[Sequence[str], Dict[str, int]]]) -> Dict[str, Dict[str, int]]:
    return {str(qid): _grade_map(rel) for qid, rel in qrels.items()}


def _grade_map(rel: Union[Sequence[str], Dict[str, int]]) -> Dict[str, int]:
    if isinstance(rel, dict):
        return {str(doc_id): int(grade) for doc_id, grade in rel.items()}
    return {str(doc_id): 1 for doc_id in rel}


def _normalize_corpus(corpus: CorpusInput) -> Tuple[Dict[str, str], Dict[str, Document]]:
    text_map: Dict[str, str] = {}
    doc_map: Dict[str, Document] = {}
    if corpus is None:
        return text_map, doc_map

    if isinstance(corpus, dict):
        items = corpus.items()
        for doc_id, value in items:
            doc_id = str(doc_id)
            if isinstance(value, Document):
                text_map[doc_id] = value.text
                doc_map[doc_id] = value
            else:
                text_map[doc_id] = str(value)
                doc_map[doc_id] = Document(id=doc_id, text=str(value), score=0.0, rank=0)
        return text_map, doc_map

    # Sequence of dicts: {"id": ..., "text": ..., optional title/metadata}
    for obj in corpus:
        doc_id = str(obj["id"])
        text = obj.get("text", "")
        text_map[doc_id] = text
        doc_map[doc_id] = Document(
            id=doc_id,
            text=text,
            title=obj.get("title", ""),
            score=0.0,
            rank=0,
            metadata=obj.get("metadata", {}) or {},
        )
    return text_map, doc_map
