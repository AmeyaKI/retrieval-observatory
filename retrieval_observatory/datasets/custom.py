from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from retrieval_observatory.types import Query


class CustomDataset:
    """Loads a user-provided JSONL dataset.

    Each line: {"query_id": "...", "text": "...", "relevant_doc_ids": [...], "temporal_anchor": "..."}
    Graded relevance: relevant_doc_ids can be {"doc_id": grade_int}
    """

    def __init__(
        self,
        queries_path: str,
        corpus_path: Optional[str] = None,
        k: int = 10,
        temporal_field: Optional[str] = None,
    ):
        self.queries_path = queries_path
        self.corpus_path = corpus_path
        self.k = k
        self.temporal_field = temporal_field
        self._corpus: Optional[Dict[str, str]] = None

    @property
    def corpus(self) -> Dict[str, str]:
        if self._corpus is None and self.corpus_path:
            self._corpus = {}
            with open(self.corpus_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    self._corpus[obj["id"]] = obj.get("text", "")
        return self._corpus or {}

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

                temporal_anchor = None
                if "temporal_anchor" in obj and obj["temporal_anchor"]:
                    temporal_anchor = datetime.fromisoformat(obj["temporal_anchor"])

                queries.append(
                    Query(
                        text=obj["text"],
                        k=self.k,
                        query_id=query_id,
                        temporal_anchor=temporal_anchor,
                        filters=obj.get("filters", {}),
                    )
                )

                rel = obj.get("relevant_doc_ids", [])
                if isinstance(rel, dict):
                    qrels[query_id] = {doc_id: int(grade) for doc_id, grade in rel.items()}
                else:
                    qrels[query_id] = {doc_id: 1 for doc_id in rel}

        return queries, qrels
