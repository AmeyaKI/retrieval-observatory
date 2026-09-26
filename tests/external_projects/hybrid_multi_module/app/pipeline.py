from __future__ import annotations

import asyncio
import json
from typing import Any

from app.fusion import rrf_fusion
from app.gate import IntentRouter
from app.lanes import DenseLane, LexicalLane
from app.rerank import Reranker


class HybridPipeline:
    def __init__(self) -> None:
        self.router = IntentRouter()
        self.lexical = LexicalLane()
        self.dense = DenseLane()
        self.reranker = Reranker()

    async def run(self, query: str) -> list[dict[str, Any]]:
        route = self.router.route(query)
        if route == "hybrid":
            lanes = await asyncio.gather(
                asyncio.to_thread(self.lexical.search, query, route),
                self.dense.search(query, route),
            )
        else:
            lanes = [self.lexical.search(query, route)]
        return self.reranker.rerank(query, rrf_fusion(*lanes))


PIPELINE = HybridPipeline()


def retrieve(query: str) -> list[dict[str, Any]]:
    return asyncio.run(PIPELINE.run(query))


if __name__ == "__main__":
    queries = (("q-hybrid", "hybrid question"), ("q-hybrid-repeat", "hybrid question"), ("q-lexical", "lexical question"))
    print(json.dumps([{"query_id": query_id, "documents": retrieve(query)} for query_id, query in queries], sort_keys=True))
