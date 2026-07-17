from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from llama_index.core.schema import NodeWithScore, TextNode


def llamaindex_retriever(query: str) -> list[NodeWithScore]:
    nodes = [
        NodeWithScore(
            node=TextNode(
                id_="d-llama-current",
                text="Current LlamaIndex retrieval result",
                metadata={"rank": 1, "corpus_path": Path("data/corpus.jsonl"), "retrieved_at": datetime(2026, 7, 16, tzinfo=timezone.utc)},
            ),
            score=0.94,
        ),
        NodeWithScore(
            node=TextNode(
                id_="d-llama-history",
                text="Historical LlamaIndex retrieval result",
                metadata={"rank": 2, "corpus_path": Path("data/corpus.jsonl"), "retrieved_at": datetime(2026, 7, 16, tzinfo=timezone.utc)},
            ),
            score=0.70,
        ),
    ]
    return nodes if "history" not in query else list(reversed(nodes))


def _output(query_id: str, query: str) -> dict[str, object]:
    nodes = llamaindex_retriever(query)
    return {
        "query_id": query_id,
        "documents": [
            {"id": node.node.node_id, "score": node.score, "rank": node.node.metadata["rank"]}
            for node in nodes
        ],
    }


if __name__ == "__main__":
    print(json.dumps([_output("q-llama-1", "current"), _output("q-llama-2", "current history")], sort_keys=True))
