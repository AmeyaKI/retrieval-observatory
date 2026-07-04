from __future__ import annotations

from typing import Any, Dict

# Self-describing config helpers so an agent can discover the ExperimentConfig shape and
# dry-run-validate a config WITHOUT running a benchmark or reading external docs. Both the REST
# layer and the MCP server wrap these, so the guidance stays in one place.

# Minimal, copy-paste-ready stage snippets keyed by adapter type. Each is a valid `stages[]`
# entry; an agent picks one per stage and fills the blanks.
ADAPTER_EXAMPLES: Dict[str, Dict[str, Any]] = {
    "adapter.http": {
        "type": "adapter.http",
        "url": "http://your-search-service/retrieve",
        "retriever_id": "my_service",
        "config": {"id_field": "id", "text_field": "text", "score_field": "score", "k": 10},
    },
    "adapter.bm25": {"type": "adapter.bm25", "retriever_id": "bm25"},
    "adapter.hf_biencoder": {
        "type": "adapter.hf_biencoder",
        "retriever_id": "dense",
        "config": {"model": "sentence-transformers/all-MiniLM-L6-v2", "k": 10},
    },
    "adapter.hf_crossencoder": {
        "type": "adapter.hf_crossencoder",
        "retriever_id": "rerank",
        "config": {"model": "cross-encoder/ms-marco-MiniLM-L-6-v2"},
    },
    "adapter.cohere_rerank": {
        "type": "adapter.cohere_rerank",
        "retriever_id": "cohere_rerank",
        "config": {"model": "rerank-english-v3.0"},
    },
    "adapter.rrf": {
        "type": "adapter.rrf",
        "retriever_id": "hybrid",
        "config": {"retrievers": ["<stage>", "<stage>"], "rrf_k": 60},
    },
}

# A complete, runnable config that validates out of the box: benchmark an existing HTTP retrieval
# service against a BM25 baseline. Uses a BEIR dataset so no local files are needed; swap in a
# custom dataset (see DATASET_EXAMPLES / notes) to grade against your own queries + qrels.
EXAMPLE_CONFIG: Dict[str, Any] = {
    "experiment": {"name": "my-retrieval-eval"},
    "dataset": {"name": "beir/nfcorpus", "max_queries": 50},
    "pipelines": [
        {
            "id": "baseline_bm25",
            "stages": [{"type": "adapter.bm25", "retriever_id": "bm25", "config": {"k": 10}}],
        },
        {
            "id": "my_service",
            "stages": [
                {
                    "type": "adapter.http",
                    "url": "http://your-search-service/retrieve",
                    "retriever_id": "my_service",
                    "config": {"id_field": "id", "text_field": "text", "score_field": "score", "k": 10},
                }
            ],
        },
    ],
    "output": {"store": "sqlite", "db_path": ".retobs/agent-eval.db"},
}

# Dataset stanza options an agent can drop into `dataset`.
DATASET_EXAMPLES: Dict[str, Any] = {
    "beir": {"name": "beir/nfcorpus", "max_queries": 50},
    "custom": {
        "type": "custom",
        "name": "custom",
        "queries_path": "queries.jsonl",
        "corpus_path": "corpus.jsonl",
        "qrels_path": "qrels.jsonl",
    },
}

# Short, agent-facing notes that prevent the common footguns.
CONFIG_NOTES = [
    "Pipelines are CONFIG, not code: retobs runs its own retrieval out-of-band and never imports "
    "or modifies your live pipeline.",
    "To benchmark an existing service without touching it, use an 'adapter.http' stage pointing at "
    "its retrieval endpoint (read-only calls).",
    "Datasets: use {'type':'custom', 'queries_path','corpus_path','qrels_path'} (JSONL) or a "
    "{'name':'beir/<dataset>'} id — no local files needed for BEIR.",
    "Stage 0 is the retriever/candidate generator; later stages are rerankers.",
    "Set output.db_path to an isolated file (e.g. .retobs/agent-eval.db) to avoid touching other results.",
    "Cap cost with max_queries on the tool/endpoint call while iterating.",
]


def config_schema() -> Dict[str, Any]:
    """Return the ExperimentConfig JSON schema plus copy-paste examples and adapter snippets."""
    from retrieval_observatory.config.schema import ExperimentConfig

    return {
        "json_schema": ExperimentConfig.model_json_schema(),
        "example_config": EXAMPLE_CONFIG,
        "adapter_examples": ADAPTER_EXAMPLES,
        "dataset_examples": DATASET_EXAMPLES,
        "notes": CONFIG_NOTES,
    }


def validate_config_dict(config: Dict[str, Any]) -> Dict[str, Any]:
    """Dry-run validate a config dict WITHOUT running a benchmark.

    Returns {"valid": bool, "status", "summary", "items"}. Parse errors (malformed structure)
    surface as valid=False with a single parse item; semantic checks reuse the same
    validate_experiment_config the dashboard upload path uses.
    """
    from retrieval_observatory.config.schema import ExperimentConfig
    from retrieval_observatory.datasets.validation import validate_experiment_config

    try:
        cfg = ExperimentConfig.model_validate(config)
    except Exception as e:  # noqa: BLE001 — report parse failure to the caller
        return {
            "valid": False,
            "status": "error",
            "summary": {"errors": 1, "warnings": 0, "ok": 0},
            "items": [{"level": "error", "message": f"Config does not parse: {e}", "field": None}],
        }
    report = validate_experiment_config(cfg)
    report["valid"] = report["status"] != "error"
    return report
