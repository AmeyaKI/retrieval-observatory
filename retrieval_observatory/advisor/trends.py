from __future__ import annotations

from typing import Any, Dict, List, Optional

from retrieval_observatory.advisor.recommend import compute_reliability
from retrieval_observatory.store.base import BaseStore


async def record_reliability_snapshot(run_id: str, store: BaseStore) -> Dict[str, Any]:
    """Compute and persist a reliability score snapshot for trend tracking."""
    score = await compute_reliability(run_id, store)
    if hasattr(store, "save_reliability_snapshot"):
        await store.save_reliability_snapshot(run_id, score.value, score.components)
    return {"run_id": run_id, "value": score.value, "components": score.components}


async def get_reliability_trends(
    store: BaseStore,
    *,
    run_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    if not hasattr(store, "get_reliability_history"):
        return []
    return await store.get_reliability_history(run_id=run_id, limit=limit)
