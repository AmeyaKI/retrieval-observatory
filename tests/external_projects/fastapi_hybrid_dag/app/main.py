from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


app = FastAPI(title="External hybrid retrieval")


class RetrieveRequest(BaseModel):
    query_id: str
    query: str
    scenario: str | None = None


def _candidate(doc_id: str, score: float, rank: int) -> dict[str, Any]:
    return {
        "id": doc_id,
        "score": score,
        "rank": rank,
        "metadata": {
            "corpus_path": Path("data/corpus.jsonl"),
            "retrieved_at": datetime(2026, 7, 16, tzinfo=timezone.utc),
        },
    }


def intent_gate(query: str, scenario: str | None) -> str:
    if scenario:
        return scenario
    if "error" in query:
        return "retriever_error"
    if "skip" in query:
        return "gate_skip"
    if "lexical" in query:
        return "lexical_only"
    return "hybrid"


def bm25(query: str, route: str) -> list[dict[str, Any]]:
    return [_candidate("d-current", 0.84, 1), _candidate("d-lexical", 0.79, 2)]


def dense(query: str, route: str) -> list[dict[str, Any]]:
    return [_candidate("d-hybrid", 0.88, 1), _candidate("d-current", 0.83, 2)]


def rrf_fusion(*lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {candidate["id"]: candidate for lane in lanes for candidate in lane}
    return [
        {**candidate, "rank": rank}
        for rank, candidate in enumerate((by_id["d-current"], by_id["d-hybrid"], by_id["d-lexical"]), start=1)
    ]


def temporal_filter(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [candidate for candidate in candidates if candidate["id"] != "d-lexical"]


def rerank(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = [_candidate("d-current", 0.97, 1), _candidate("d-hybrid", 0.88, 2)]
    return [candidate for candidate in ranked if candidate["id"] in {item["id"] for item in candidates}]


def retrieve(query_id: str, query: str, scenario: str | None = None) -> dict[str, Any]:
    route = intent_gate(query, scenario)
    if route == "retriever_error":
        raise HTTPException(status_code=503, detail={"code": "retriever_unavailable", "query_id": query_id})
    if route == "gate_skip":
        documents: list[dict[str, Any]] = []
    elif route == "lexical_only":
        documents = [_candidate("d-lexical", 0.79, 1)]
    else:
        documents = rerank(temporal_filter(rrf_fusion(bm25(query, route), dense(query, route))))
    return {
        "query_id": query_id,
        "route": route,
        "documents": [{key: candidate[key] for key in ("id", "score", "rank")} for candidate in documents],
    }


@app.post("/retrieve")
def retrieve_route(request: RetrieveRequest) -> dict[str, Any]:
    return retrieve(request.query_id, request.query, request.scenario)


if __name__ == "__main__":
    output = [
        retrieve("q-hybrid", "hybrid query"),
        retrieve("q-hybrid-repeat", "hybrid query"),
        retrieve("q-lexical", "lexical query"),
        retrieve("q-gate", "skip query"),
    ]
    print(json.dumps(output, sort_keys=True))
