from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional

from retrieval_observatory.config.schema import ExperimentConfig


@dataclass
class ValidationItem:
    level: str
    check: str
    message: str


def validate_experiment_config(config: ExperimentConfig, config_path: Optional[str] = None) -> Dict:
    items: List[ValidationItem] = []
    base_dir = os.path.dirname(os.path.abspath(config_path)) if config_path else None

    _check_dataset(config, items, base_dir=base_dir)
    _check_pipelines(config, items)
    _check_labels(config, items)
    _check_output(config, items)

    blocking = sum(1 for item in items if item.level == "error")
    warnings = sum(1 for item in items if item.level == "warning")
    status = "error" if blocking else "warning" if warnings else "ok"
    return {
        "status": status,
        "config_path": config_path,
        "summary": {"errors": blocking, "warnings": warnings, "ok": sum(1 for item in items if item.level == "ok")},
        "items": [asdict(item) for item in items],
    }


def dataset_fingerprint(name: str, queries: list, qrels: Dict, corpus: Optional[Dict[str, str]] = None) -> Dict:
    qrel_doc_ids = {doc_id for rels in qrels.values() for doc_id in _rel_ids(rels)}
    corpus_ids = set(corpus or {})
    missing = sorted(qrel_doc_ids - corpus_ids) if corpus is not None else []
    return {
        "name": name,
        "queries": len(queries),
        "qrels": len(qrels),
        "corpus_docs": len(corpus or {}),
        "qrel_doc_ids": len(qrel_doc_ids),
        "missing_qrel_doc_ids": len(missing),
        "missing_qrel_doc_id_examples": missing[:10],
        "label_sparsity_pct": round((1 - len(qrels) / max(len(queries), 1)) * 100, 2),
    }


def _check_dataset(config: ExperimentConfig, items: List[ValidationItem], base_dir: Optional[str] = None) -> None:
    ds = config.dataset
    if ds.name == "custom" or ds.type == "custom":
        queries_path = _resolve(ds.queries_path, base_dir)
        corpus_path = _resolve(ds.corpus_path, base_dir)
        qrels_path = _resolve(ds.qrels_path, base_dir)
        _path_check(items, "custom queries file", queries_path, required=True)
        _path_check(items, "custom corpus file", corpus_path, required=any(s.type in {"adapter.bm25", "adapter.hf_biencoder"} for p in config.pipelines for s in p.stages))
        _path_check(items, "custom qrels file", qrels_path, required=False)
        if queries_path and os.path.exists(queries_path):
            _inspect_query_file(queries_path, items)
        if corpus_path and os.path.exists(corpus_path):
            _inspect_corpus_file(corpus_path, items)
        return
    if ds.name.startswith("beir/") or ds.name:
        items.append(ValidationItem("ok", "dataset", f"Dataset '{ds.name}' is configured."))


def _check_pipelines(config: ExperimentConfig, items: List[ValidationItem]) -> None:
    supported = {
        "adapter.http",
        "adapter.bm25",
        "adapter.hf_biencoder",
        "adapter.hf_crossencoder",
        "adapter.cohere_rerank",
        "adapter.pgvector",
        "adapter.langchain",
        "adapter.llamaindex",
        "adapter.rrf",
        "adapter.import",
    }
    for pipeline in config.pipelines:
        if not pipeline.stages:
            items.append(ValidationItem("error", "pipeline stages", f"Pipeline '{pipeline.id}' has no stages."))
        for idx, stage in enumerate(pipeline.stages):
            if stage.type not in supported:
                items.append(ValidationItem("error", "stage type", f"Pipeline '{pipeline.id}' stage {idx} uses unsupported type '{stage.type}'."))
            else:
                items.append(ValidationItem("ok", "stage type", f"Pipeline '{pipeline.id}' stage {idx} uses '{stage.type}'."))
            k = stage.config.get("k")
            if k is None:
                items.append(ValidationItem("warning", "stage k", f"Pipeline '{pipeline.id}' stage {idx} has no config.k; a default will be used."))
            elif int(k) <= 0:
                items.append(ValidationItem("error", "stage k", f"Pipeline '{pipeline.id}' stage {idx} has invalid k={k}."))
            if stage.type == "adapter.rrf" and not stage.config.get("retrievers"):
                items.append(ValidationItem("error", "rrf retrievers",
                    f"Pipeline '{pipeline.id}' stage {idx}: adapter.rrf requires config.retrievers "
                    f"(list of sub-retriever stage configs to fuse)."))
            if stage.type == "adapter.http" and not stage.url:
                items.append(ValidationItem("error", "http url", f"Pipeline '{pipeline.id}' stage {idx} needs url."))
            if stage.type == "adapter.cohere_rerank" and not (stage.config.get("api_key") or os.environ.get("COHERE_API_KEY")):
                items.append(ValidationItem("warning", "cohere api key", "Cohere reranking needs config.api_key or COHERE_API_KEY before running."))
            if stage.type == "adapter.import" and not stage.config.get("factory"):
                items.append(ValidationItem("error", "import factory", f"Pipeline '{pipeline.id}' stage {idx}: adapter.import requires config.factory."))
            if stage.type in {"adapter.pgvector", "adapter.langchain", "adapter.llamaindex"}:
                items.append(ValidationItem("warning", "yaml support", f"{stage.type} cannot be fully constructed from YAML in this version. Use adapter.import with a factory callable instead."))


def _check_output(config: ExperimentConfig, items: List[ValidationItem]) -> None:
    out = config.output
    if out.store == "sqlite":
        parent = os.path.dirname(out.db_path) or "."
        if os.path.exists(parent):
            items.append(ValidationItem("ok", "output", f"SQLite output directory exists: {parent}"))
        else:
            items.append(ValidationItem("warning", "output", f"SQLite output directory will be created: {parent}"))
    if out.store == "postgres" and not (out.postgres_dsn or os.environ.get("RETOBS_POSTGRES_DSN")):
        items.append(ValidationItem("error", "postgres dsn", "Postgres output selected but no DSN is configured."))


def _check_labels(config: ExperimentConfig, items: List[ValidationItem]) -> None:
    if config.labels.mode == "gold":
        items.append(ValidationItem("ok", "labels", "Using gold labels from the dataset/qrels."))
        return
    judge = (config.labels.judge or "gemini").lower()
    env_var = {"gemini": "GOOGLE_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(judge)
    if env_var and os.environ.get(env_var):
        items.append(ValidationItem("ok", "llm judge", f"Using {judge} judge with {env_var} configured."))
    elif env_var:
        items.append(ValidationItem("warning", "llm judge", f"{config.labels.mode} needs {env_var} before running."))
    else:
        items.append(ValidationItem("error", "llm judge", f"Unsupported judge '{judge}'. Use gemini, openai, or anthropic."))


def _path_check(items: List[ValidationItem], check: str, path: Optional[str], required: bool) -> None:
    if not path:
        level = "error" if required else "warning"
        items.append(ValidationItem(level, check, f"{check} is not configured."))
    elif os.path.exists(path):
        items.append(ValidationItem("ok", check, f"{check} exists: {path}"))
    else:
        items.append(ValidationItem("error", check, f"{check} does not exist: {path}"))


def _resolve(path: Optional[str], base_dir: Optional[str]) -> Optional[str]:
    if not path or not base_dir or os.path.isabs(path):
        return path
    return os.path.join(base_dir, path)


def _inspect_query_file(path: str, items: List[ValidationItem]) -> None:
    seen = set()
    duplicates = 0
    missing_labels = 0
    count = 0
    for obj in _read_jsonl(path):
        count += 1
        qid = obj.get("query_id")
        if qid in seen:
            duplicates += 1
        seen.add(qid)
        if "relevant_doc_ids" not in obj:
            missing_labels += 1
    if duplicates:
        items.append(ValidationItem("error", "query ids", f"Found {duplicates} duplicate query IDs."))
    if missing_labels:
        items.append(ValidationItem("warning", "qrels", f"{missing_labels}/{count} queries have no inline relevant_doc_ids."))
    items.append(ValidationItem("ok", "query count", f"Found {count} custom queries."))


def _inspect_corpus_file(path: str, items: List[ValidationItem]) -> None:
    seen = set()
    duplicates = 0
    empty = 0
    count = 0
    for obj in _read_jsonl(path):
        count += 1
        doc_id = obj.get("id")
        if doc_id in seen:
            duplicates += 1
        seen.add(doc_id)
        if not obj.get("text"):
            empty += 1
    if duplicates:
        items.append(ValidationItem("error", "corpus ids", f"Found {duplicates} duplicate document IDs."))
    if empty:
        items.append(ValidationItem("warning", "empty documents", f"{empty}/{count} corpus documents have empty text."))
    items.append(ValidationItem("ok", "corpus count", f"Found {count} corpus documents."))


def _read_jsonl(path: str) -> Iterable[Dict]:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _rel_ids(rels: object) -> Iterable[str]:
    if isinstance(rels, dict):
        return [doc_id for doc_id, grade in rels.items() if int(grade) > 0]
    return list(rels or [])
