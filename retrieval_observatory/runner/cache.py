from __future__ import annotations

import hashlib
import json
from typing import Optional

from retrieval_observatory.store.base import BaseStore
from retrieval_observatory.types import Document, PipelineResult, StageSnapshot


def _make_cache_key(pipeline_config_yaml: str, query_id: str) -> str:
    raw = f"{pipeline_config_yaml}::{query_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _make_stage_cache_key(stage_config_yaml: str, query_id: str) -> str:
    raw = f"stage::{stage_config_yaml}::{query_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _snap_to_json(snap: StageSnapshot) -> str:
    def _snap_dict(item: StageSnapshot) -> dict:
        return {
            "stage_index": item.stage_index,
            "stage_id": item.stage_id,
            "latency_ms": item.latency_ms,
            "profiling": item.profiling,
            "candidate_count": item.candidate_count,
            "documents": [
                {
                    "id": d.id,
                    "text": d.text,
                    "score": d.score,
                    "rank": d.rank,
                    "title": d.title,
                    "timestamp": d.timestamp.isoformat() if d.timestamp else None,
                    "metadata": d.metadata,
                }
                for d in item.documents
            ],
            "arms": [_snap_dict(arm) for arm in item.arms],
        }

    return json.dumps(_snap_dict(snap))


def _snap_from_json(data: str) -> StageSnapshot:
    from datetime import datetime

    def _snap_obj(obj: dict) -> StageSnapshot:
        docs = [
            Document(
                id=d["id"],
                text=d["text"],
                score=d["score"],
                rank=d["rank"],
                title=d.get("title", ""),
                timestamp=datetime.fromisoformat(d["timestamp"]) if d["timestamp"] else None,
                metadata=d.get("metadata", {}),
            )
            for d in obj["documents"]
        ]
        return StageSnapshot(
            stage_index=obj["stage_index"],
            stage_id=obj["stage_id"],
            documents=docs,
            latency_ms=obj["latency_ms"],
            profiling=obj.get("profiling", {}),
            candidate_count=obj.get("candidate_count", len(docs)),
            arms=[_snap_obj(arm) for arm in obj.get("arms", [])],
        )

    return _snap_obj(json.loads(data))


def _result_to_json(result: PipelineResult) -> str:
    def snap_to_dict(s: StageSnapshot) -> dict:
        return {
            "stage_index": s.stage_index,
            "stage_id": s.stage_id,
            "latency_ms": s.latency_ms,
            "profiling": s.profiling,
            "candidate_count": s.candidate_count,
            "documents": [
                {
                    "id": d.id,
                    "text": d.text,
                    "score": d.score,
                    "rank": d.rank,
                    "title": d.title,
                    "timestamp": d.timestamp.isoformat() if d.timestamp else None,
                    "metadata": d.metadata,
                }
                for d in s.documents
            ],
            "arms": [snap_to_dict(arm) for arm in s.arms],
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

    def _to_snap(s: dict) -> StageSnapshot:
        docs = [
            Document(
                id=d["id"],
                text=d["text"],
                score=d["score"],
                rank=d["rank"],
                title=d.get("title", ""),
                timestamp=datetime.fromisoformat(d["timestamp"]) if d["timestamp"] else None,
                metadata=d.get("metadata", {}),
            )
            for d in s["documents"]
        ]
        return StageSnapshot(
            stage_index=s["stage_index"],
            stage_id=s["stage_id"],
            documents=docs,
            latency_ms=s["latency_ms"],
            profiling=s.get("profiling", {}),
            candidate_count=s.get("candidate_count", len(docs)),
            arms=[_to_snap(arm) for arm in s.get("arms", [])],
        )

    for s in obj["snapshots"]:
        snapshots.append(_to_snap(s))
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


class StageResultCache:
    """Per-stage cache shared across all pipelines.

    Key = hash(stage_config + upstream_fingerprint + query_id).

    For Stage 0 (first retriever), no upstream candidates exist, so the key is just
    hash(stage_config + query_id) — identical first-stage configs share cache entries
    across ablation combos as intended.

    For Stage 1+ (rerankers), the key also includes a fingerprint of the upstream
    candidate doc IDs. This prevents a reranker from returning a snapshot computed
    on a different pipeline's candidate set, which would silently corrupt results when
    two pipelines share the same reranker but have different first-stage retrievers.
    """

    def __init__(self, store: BaseStore):
        self._store = store

    def key_for(
        self,
        stage_config: dict,
        query_id: str,
        upstream_doc_ids: list[str] | None = None,
    ) -> str:
        import yaml
        upstream_part = (
            hashlib.sha256(",".join(sorted(upstream_doc_ids)).encode()).hexdigest()[:16]
            if upstream_doc_ids
            else "nostage"
        )
        stage_yaml = yaml.dump(stage_config, sort_keys=True)
        raw = f"stage::{stage_yaml}::{upstream_part}::{query_id}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def get(self, key: str) -> Optional[StageSnapshot]:
        raw = await self._store.cache_get(key)
        if raw is None:
            return None
        return _snap_from_json(raw)

    async def set(self, key: str, snap: StageSnapshot) -> None:
        await self._store.cache_set(key, _snap_to_json(snap))
