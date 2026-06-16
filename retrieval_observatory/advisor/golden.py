from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from retrieval_observatory.store.base import BaseStore


async def save_golden_set(store: BaseStore, name: str, queries: List[Dict[str, Any]]) -> None:
    await store.save_golden_set(name, json.dumps(queries))


async def get_golden_set(store: BaseStore, name: str) -> Optional[List[Dict[str, Any]]]:
    raw = await store.get_golden_set(name)
    if raw is None:
        return None
    return json.loads(raw)


async def list_golden_sets(store: BaseStore) -> List[Dict[str, Any]]:
    return await store.list_golden_sets()
