from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Dict


def detect_forge_dataset_id(cfg: Any) -> str | None:
    """Read forge_metadata.json adjacent to the dataset paths, if present."""
    ds = getattr(cfg, "dataset", None)
    if ds is None:
        return None
    seen: set[Path] = set()
    for attr in ("queries_path", "corpus_path", "qrels_path"):
        value = getattr(ds, attr, None)
        if not value:
            continue
        parent = Path(value).parent
        if parent in seen:
            continue
        seen.add(parent)
        meta_path = parent / "forge_metadata.json"
        if not meta_path.is_file():
            continue
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            dataset_id = data.get("dataset_id")
            if dataset_id:
                return str(dataset_id)
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return None


def build_run_manifest(
    config: Any,
    dataset_fingerprint: Dict[str, Any],
    latency_budget_ms: int | None = None,
    forge_dataset_id: str | None = None,
    golden_set: str | None = None,
) -> Dict[str, Any]:
    """Capture enough environment detail to make a run auditable."""
    config_json = config.model_dump_json() if hasattr(config, "model_dump_json") else json.dumps(config)
    packages = {}
    for name in ("retobs", "numpy", "pydantic", "httpx", "rank-bm25", "sentence-transformers", "faiss-cpu"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue

    manifest = {
        "config_hash": hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
        "dataset": dataset_fingerprint,
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
        "git_commit": _git_commit(),
        "cache_results": getattr(getattr(config, "execution", None), "cache_results", None),
    }
    if latency_budget_ms is not None:
        manifest["latency_budget_ms"] = latency_budget_ms
    if forge_dataset_id is not None:
        manifest["forge_dataset_id"] = forge_dataset_id
    if golden_set is not None:
        manifest["golden_set"] = golden_set
    return manifest


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip()
    except Exception:
        return None
