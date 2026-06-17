from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from retrieval_observatory.store.sqlite import SQLiteStore


def _slugify(stem: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", stem).strip("_").lower()
    return slug or "db"


@dataclass
class DbSource:
    db_id: str
    label: str
    path: str
    store: SQLiteStore


class DbRegistry:
    """Maps stable db_id keys to SQLiteStore instances for multi-DB dashboard serving."""

    def __init__(self, db_paths: List[str]):
        if not db_paths:
            raise ValueError("At least one database path is required")
        self._sources: Dict[str, DbSource] = {}
        used_ids: Dict[str, int] = {}

        for raw_path in db_paths:
            path = str(Path(raw_path).expanduser().resolve())
            stem = Path(path).stem
            base_id = _slugify(stem)
            count = used_ids.get(base_id, 0)
            used_ids[base_id] = count + 1
            db_id = base_id if count == 0 else f"{base_id}_{count + 1}"

            self._sources[db_id] = DbSource(
                db_id=db_id,
                label=stem,
                path=path,
                store=SQLiteStore(db_path=path),
            )

    @property
    def is_single(self) -> bool:
        return len(self._sources) == 1

    @property
    def default_db_id(self) -> Optional[str]:
        if not self._sources:
            return None
        return next(iter(self._sources.keys()))

    def get(self, db_id: str) -> DbSource:
        source = self._sources.get(db_id)
        if source is None:
            raise KeyError(db_id)
        return source

    def get_store(self, db_id: str) -> SQLiteStore:
        return self.get(db_id).store

    async def init_all(self) -> None:
        for source in self._sources.values():
            await source.store.init_db()

    async def list_sources(self) -> List[Dict]:
        out = []
        for source in self._sources.values():
            runs = await source.store.list_runs()
            out.append(
                {
                    "db_id": source.db_id,
                    "label": source.label,
                    "path": source.path,
                    "run_count": len(runs),
                }
            )
        return out

    def list_db_ids(self) -> List[str]:
        return list(self._sources.keys())

    @property
    def db_paths(self) -> List[str]:
        return [source.path for source in self._sources.values()]

    async def list_runs(self, db_id: str) -> List[Dict]:
        source = self.get(db_id)
        runs = await source.store.list_runs()
        for run in runs:
            run["db_id"] = db_id
        return runs
