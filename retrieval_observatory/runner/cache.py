from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Optional

from retrieval_observatory.store.base import BaseStore
from retrieval_observatory.types import Document, PipelineResult, StageSnapshot


def _make_cache_key(pipeline_config_yaml: str, query_id: str) -> str:
    raw = f"{pipeline_config_yaml}::{query_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _result_to_json(result: PipelineResult) -> str:
    def snap_to_dict(s: StageSnapshot) -> dict:
        return {
            "stage_index": s.stage_index,
            "stage_id": s.stage_id,
            "latency_ms": s.latency_ms,
            "documents": [
                {
                    "id": d.id,
                    "text": d.text,
                    "score": d.score,
                    "rank": d.rank,
                    "timestamp": d.timestamp.isoformat() if d.timestamp else None,
                    "metadata": d.metadata,
                }
                for d in s.documents
            ],
        }

    return json.dumps({
        "query_id": result.query_id,
        "pipeline_id": result.pipeline_id,
        "total_latency_ms": result.total_latency_ms,
        "status": result.status,
        "error_traceback": result.error_traceback,
        "snapshots": [snap_to_dict(s) for s in result.snapshots],
    })


def _result_from_json(data: str) -> PipelineResult:
    from datetime import datetime

    obj = json.loads(data)
    snapshots = []
    for s in obj["snapshots"]:
        docs = [
            Document(
                id=d["id"],
                text=d["text"],
                score=d["score"],
                rank=d["rank"],
                timestamp=datetime.fromisoformat(d["timestamp"]) if d["timestamp"] else None,
                metadata=d.get("metadata", {}),
            )
            for d in s["documents"]
        ]
        snapshots.append(
            StageSnapshot(
                stage_index=s["stage_index"],
                stage_id=s["stage_id"],
                documents=docs,
                latency_ms=s["latency_ms"],
            )
        )
    return PipelineResult(
        query_id=obj["query_id"],
        pipeline_id=obj["pipeline_id"],
        snapshots=snapshots,
        total_latency_ms=obj["total_latency_ms"],
        status=obj["status"],
        error_traceback=obj.get("error_traceback"),
    )


class ResultCache:
    def __init__(self, store: BaseStore, pipeline_config_yaml: str):
        self._store = store
        self._config_yaml = pipeline_config_yaml

    def _key(self, query_id: str) -> str:
        return _make_cache_key(self._config_yaml, query_id)

    async def get(self, query_id: str) -> Optional[PipelineResult]:
        raw = await self._store.cache_get(self._key(query_id))
        if raw is None:
            return None
        return _result_from_json(raw)

    async def set(self, query_id: str, result: PipelineResult) -> None:
        await self._store.cache_set(self._key(query_id), _result_to_json(result))
