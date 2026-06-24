from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from retrieval_observatory.types import Query


class TimeQADataset:
    """Loads the TimeQA dataset, populating Query.temporal_anchor from date metadata."""

    def __init__(self, split: str = "test", max_queries: Optional[int] = None):
        self.split = split
        self.max_queries = max_queries

    def load(self) -> Tuple[List[Query], Dict[str, Set[str]]]:
        try:
            from datasets import load_dataset
        except ImportError as e:
            raise ImportError(
                "TimeQA support requires the 'datasets' package. "
                "Install with: pip install retobs[beir]"
            ) from e

        ds = load_dataset("cmunlp/timeqa", split=self.split)
        if self.max_queries is not None:
            ds = ds.select(range(self.max_queries))

        queries: List[Query] = []
        qrels: Dict[str, Set[str]] = {}

        for i, item in enumerate(ds):
            query_id = item.get("id", str(i))
            text = item["question"]

            temporal_anchor = None
            date_str = item.get("answer_start_year") or item.get("year")
            if date_str:
                try:
                    temporal_anchor = datetime(int(date_str), 1, 1)
                except (ValueError, TypeError):
                    pass

            queries.append(
                Query(
                    text=text,
                    k=10,
                    query_id=str(query_id),
                    temporal_anchor=temporal_anchor,
                )
            )

            answers = item.get("answers", {}).get("text", [])
            qrels[str(query_id)] = set(answers)

        return queries, qrels
