from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, List


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
    seed: int | None = None,
) -> Dict[str, Any]:
    """Capture enough environment detail to make a run auditable."""
    normalized_config = config.model_dump(mode="json") if hasattr(config, "model_dump") else config
    config_json = json.dumps(normalized_config, sort_keys=True, separators=(",", ":"), default=str)
    packages = {}
    for name in ("retobs", "numpy", "pydantic", "httpx", "rank-bm25", "sentence-transformers", "faiss-cpu"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue

    display = build_pipeline_display(config)
    manifest = {
        "schema_version": 3,
        "config_hash": hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
        "normalized_config": normalized_config,
        "dataset": dataset_fingerprint,
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
        "git_commit": _git_commit(),
        "git_dirty": _git_dirty(),
        "cache_results": getattr(getattr(config, "execution", None), "cache_results", None),
        "seed": seed if seed is not None else getattr(getattr(config, "execution", None), "seed", None),
        "execution": _execution_manifest(config, seed),
        "labeling": _label_manifest(config),
        "models": _model_inventory(config),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or None,
        },
        "counts": {
            "attempted": None,
            "completed": None,
            "labeled": None,
            "metric_eligible": None,
        },
        **display,
    }
    if latency_budget_ms is not None:
        manifest["latency_budget_ms"] = latency_budget_ms
    if forge_dataset_id is not None:
        manifest["forge_dataset_id"] = forge_dataset_id
    if golden_set is not None:
        manifest["golden_set"] = golden_set
    return manifest


def _stage_label(stage: Any) -> str:
    rid = getattr(stage, "retriever_id", None)
    if rid:
        return str(rid)
    stype = getattr(stage, "type", "") or ""
    return stype.replace("adapter.", "")


def build_pipeline_display(config: Any) -> Dict[str, Any]:
    """Per-pipeline stage labels and explicit ablation duplicate-stage hints from resolved config."""
    stage_labels: Dict[str, List[str]] = {}
    duplicate_ablation_stages: List[Dict[str, Any]] = []
    all_ids: set[str] = set()

    for pipeline in getattr(config, "pipelines", []) or []:
        all_ids.add(pipeline.id)
        stage_labels[pipeline.id] = [_stage_label(s) for s in pipeline.stages]

    for graph in getattr(config, "graphs", []) or []:
        all_ids.add(graph.id)
        stage_labels[graph.id] = [n.id for n in graph.nodes]

    for pid in sorted(stage_labels.keys(), key=len):
        parts = pid.split("__")
        for stage_index in range(len(parts) - 1):
            prefix = "__".join(parts[: stage_index + 1])
            if prefix in all_ids and prefix != pid:
                duplicate_ablation_stages.append(
                    {
                        "pipeline_id": pid,
                        "stage_index": stage_index,
                        "equivalent_pipeline_id": prefix,
                    }
                )

    return {
        "stage_labels": stage_labels,
        "duplicate_ablation_stages": duplicate_ablation_stages,
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


def _git_dirty() -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return bool(result.stdout.strip())
    except Exception:
        return None


def _execution_manifest(config: Any, seed: int | None) -> Dict[str, Any]:
    execution = getattr(config, "execution", None)
    configured_seed = seed if seed is not None else getattr(execution, "seed", None)
    return {
        "concurrency": getattr(execution, "concurrency", None),
        "timeout_ms": getattr(execution, "timeout_ms", None),
        "retry_attempts": getattr(execution, "retry_attempts", None),
        "cache_results": getattr(execution, "cache_results", None),
        "seed": configured_seed,
        "nondeterminism_flags": ["scheduler_seed_missing"] if configured_seed is None else [],
        "observed": {
            "cache_hits": None,
            "cache_misses": None,
            "timeouts": None,
            "retries": None,
        },
    }


def _label_manifest(config: Any) -> Dict[str, Any]:
    labels = getattr(config, "labels", None)
    return {
        "method": getattr(labels, "mode", None),
        "judge": getattr(labels, "judge", None),
        "model": getattr(labels, "model", None),
        "version": None,
    }


def _model_inventory(config: Any) -> List[Dict[str, Any]]:
    inventory: List[Dict[str, Any]] = []
    for pipeline in getattr(config, "pipelines", []) or []:
        for index, stage in enumerate(pipeline.stages):
            inventory.append({
                "pipeline_id": pipeline.id,
                "operator_id": getattr(stage, "retriever_id", None) or f"stage-{index}",
                "type": getattr(stage, "type", None),
                "model": getattr(stage, "model", None),
                "version": (getattr(stage, "config", None) or {}).get("model_version"),
            })
    for graph in getattr(config, "graphs", []) or []:
        for node in graph.nodes:
            inventory.append({
                "pipeline_id": graph.id,
                "operator_id": node.id,
                "type": node.type or node.op,
                "model": node.model,
                "version": node.config.get("model_version"),
            })
    return inventory
