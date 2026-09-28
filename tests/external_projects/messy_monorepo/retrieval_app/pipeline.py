from __future__ import annotations

import json
import sys
from typing import Any

from retrieval_app import filters
from retrieval_app.fusion import fuse_results
from retrieval_app.lanes.keyword import keyword_search
from retrieval_app.lanes.vector import vector_search

from .rerank import rerank_candidates


def retrieve(query: str) -> list[dict[str, Any]]:
    fused = fuse_results(keyword_search(query), vector_search(query))
    return rerank_candidates(query, filters.anchor_filter(fused))


if __name__ == "__main__":
    print(json.dumps(retrieve(" ".join(sys.argv[1:]) or "widget pricing")))
