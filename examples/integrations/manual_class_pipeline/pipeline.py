"""The entrypoint. One call to ``SearchService.search`` opens, finishes, and persists one trace.

Run::

    python examples/integrations/manual_class_pipeline/pipeline.py "hybrid retrieval with reranking"
    retobs serve --db .retobs/manual_class_pipeline.db

Environment:
    RETOBS_DB — SQLite path the trace is written to (default: .retobs/manual_class_pipeline.db)
"""
from __future__ import annotations

import os
from pathlib import Path

from retrieval_observatory.sdk.observe import trace_scope

from fusion import rrf_merge
from rerank import OverlapReranker
from retrievers import DenseRetriever, KeywordRetriever

DB_PATH = os.environ.get("RETOBS_DB", ".retobs/manual_class_pipeline.db")
# The store does not create directories; a failed persist is logged as a warning, not raised.
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


class SearchService:
    def __init__(self) -> None:
        self.keyword = KeywordRetriever()
        self.dense = DenseRetriever()
        self.reranker = OverlapReranker()

    @trace_scope(service_id="manual_class_pipeline", pipeline_id="keyword_dense_rrf_rerank", db_path=DB_PATH)
    def search(self, query: str) -> list[dict]:
        keyword_hits = self.keyword.search(query, k=10)
        dense_hits = self.dense.search(query, k=10)
        fused = rrf_merge([keyword_hits, dense_hits], rrf_k=60)
        return self.reranker.rerank(query, fused, k=5)


if __name__ == "__main__":
    import sys

    query = " ".join(sys.argv[1:]) or "hybrid retrieval with reranking"
    for rank, hit in enumerate(SearchService().search(query), start=1):
        print(f"{rank}. {hit['doc_id']}  score={hit['score']:.2f}  {hit['text']}")
    print(f"trace written to {DB_PATH}")
