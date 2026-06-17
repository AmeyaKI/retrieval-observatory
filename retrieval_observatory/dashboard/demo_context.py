from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def find_demo_manifest_for_db(db_path: str) -> Optional[Dict[str, Any]]:
    """Load demo_manifest.json adjacent to the SQLite DB path."""
    parent = Path(db_path).expanduser().resolve().parent
    manifest_path = parent / "demo_manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def find_demo_context_for_registry(db_paths: List[str]) -> Dict[str, Any]:
    """Return demo manifest for the first registered DB that has one."""
    for raw in db_paths:
        manifest = find_demo_manifest_for_db(raw)
        if manifest:
            manifest = dict(manifest)
            manifest["db_path"] = str(Path(raw).expanduser().resolve())
            return manifest
    return {}
