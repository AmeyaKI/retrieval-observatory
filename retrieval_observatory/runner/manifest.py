from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from importlib import metadata
from typing import Any, Dict


def build_run_manifest(config: Any, dataset_fingerprint: Dict[str, Any]) -> Dict[str, Any]:
    """Capture enough environment detail to make a run auditable."""
    config_json = config.model_dump_json() if hasattr(config, "model_dump_json") else json.dumps(config)
    packages = {}
    for name in ("retrieval-observatory", "numpy", "pydantic", "httpx", "rank-bm25", "sentence-transformers", "faiss-cpu"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue

    return {
        "config_hash": hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
        "dataset": dataset_fingerprint,
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
        "git_commit": _git_commit(),
        "cache_results": getattr(getattr(config, "execution", None), "cache_results", None),
    }


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
