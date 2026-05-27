from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from retrieval_observatory.types import Document, Query


class CustomDataset:
    """Loads a user-provided JSONL dataset.

    Each line: {"query_id": "...", "text": "...", "relevant_doc_ids": [...], "temporal_anchor": "..."}
    Graded relevance: relevant_doc_ids can be {"doc_id": grade_int}
    """

    def __init__(
        self,
        queries_path: str,
        corpus_path: Optional[str] = None,
        qrels_path: Optional[str] = None,
        k: int = 10,
        temporal_field: Optional[str] = None,
        timestamp_field: Optional[str] = None,
        metadata_fields: Optional[List[str]] = None,
    ):
        self.queries_path = queries_path
        self.corpus_path = corpus_path
        self.qrels_path = qrels_path
        self.k = k
        self.temporal_field = temporal_field
        self.timestamp_field = timestamp_field or temporal_field or "timestamp"
        self.metadata_fields = metadata_fields or []
        self._corpus: Optional[Dict[str, str]] = None
        self._corpus_documents: Optional[Dict[str, Document]] = None

    @property
    def corpus(self) -> Dict[str, str]:
        if self._corpus is None:
            self._load_corpus()
        return self._corpus or {}

    @property
    def corpus_documents(self) -> Dict[str, Document]:
        if self._corpus_documents is None:
            self._load_corpus()
        return self._corpus_documents or {}

    def _load_corpus(self) -> None:
        self._corpus = {}
        self._corpus_documents = {}
        if not self.corpus_path:
            return
        with open(self.corpus_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                doc_id = str(obj["id"])
                text = obj.get("text", "")
                timestamp = _parse_datetime(obj.get(self.timestamp_field))
                metadata = obj.get("metadata", {}).copy() if isinstance(obj.get("metadata"), dict) else {}
                for field in self.metadata_fields:
                    if field in obj:
                        metadata[field] = obj[field]
                if "source" in obj:
                    metadata.setdefault("source", obj["source"])
                self._corpus[doc_id] = text
                self._corpus_documents[doc_id] = Document(
                    id=doc_id,
                    text=text,
                    title=obj.get("title", ""),
                    score=0.0,
                    rank=0,
                    timestamp=timestamp,
                    metadata=metadata,
                )

    def load(self) -> Tuple[List[Query], Dict[str, Dict[str, int]]]:
        """Returns (queries, qrels) where qrels = {query_id: {doc_id: grade}}.

        Binary relevance lists are converted to grade=1 for all docs.
        Graded dicts ({"doc_id": grade}) are passed through as-is.
        """
        queries: List[Query] = []
        qrels: Dict[str, Dict[str, int]] = {}

        with open(self.queries_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                query_id = obj["query_id"]

                temporal_anchor = _parse_datetime(obj.get("temporal_anchor"))
                metadata = obj.get("metadata", {}).copy() if isinstance(obj.get("metadata"), dict) else {}
                for key in ("tags", "segment", "source"):
                    if key in obj:
                        metadata[key] = obj[key]

                queries.append(
                    Query(
                        text=obj["text"],
                        k=self.k,
                        query_id=query_id,
                        temporal_anchor=temporal_anchor,
                        filters=obj.get("filters", {}),
                        metadata=metadata,
                    )
                )

                rel = obj.get("relevant_doc_ids", [])
                if isinstance(rel, dict):
                    qrels[query_id] = {doc_id: int(grade) for doc_id, grade in rel.items()}
                else:
                    qrels[query_id] = {doc_id: 1 for doc_id in rel}

        if self.qrels_path:
            qrels.update(_load_qrels(self.qrels_path))

        return queries, qrels


def _parse_datetime(value: object) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _load_qrels(path: str) -> Dict[str, Dict[str, int]]:
    qrels: Dict[str, Dict[str, int]] = {}
    if path.endswith(".jsonl"):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                query_id = str(obj["query_id"])
                doc_id = str(obj["doc_id"])
                grade = int(obj.get("grade", obj.get("score", 1)))
                qrels.setdefault(query_id, {})[doc_id] = grade
        return qrels

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 4:
                query_id, _, doc_id, grade = parts[:4]
            elif len(parts) >= 3:
                query_id, doc_id, grade = parts[:3]
            else:
                continue
            qrels.setdefault(query_id, {})[doc_id] = int(float(grade))
    return qrels
