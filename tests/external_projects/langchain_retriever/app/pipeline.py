from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda


def langchain_retriever(query: str) -> list[Document]:
    documents = [
        Document(
            page_content="LangChain retrieval result",
            metadata={
                "id": "d-langchain-current",
                "score": 0.93,
                "rank": 1,
                "corpus_path": Path("data/corpus.jsonl"),
                "retrieved_at": datetime(2026, 7, 16, tzinfo=timezone.utc),
            },
        ),
        Document(
            page_content="LangChain retrieval history",
            metadata={
                "id": "d-langchain-history",
                "score": 0.71,
                "rank": 2,
                "corpus_path": Path("data/corpus.jsonl"),
                "retrieved_at": datetime(2026, 7, 16, tzinfo=timezone.utc),
            },
        ),
    ]
    return documents if "history" not in query else list(reversed(documents))


pipeline = RunnableLambda(langchain_retriever)


def _output(query_id: str, query: str) -> dict[str, object]:
    documents = pipeline.invoke(query)
    return {
        "query_id": query_id,
        "documents": [
            {"id": document.metadata["id"], "score": document.metadata["score"], "rank": document.metadata["rank"]}
            for document in documents
        ],
    }


if __name__ == "__main__":
    print(json.dumps([_output("q-langchain-1", "current"), _output("q-langchain-2", "current history")], sort_keys=True))
