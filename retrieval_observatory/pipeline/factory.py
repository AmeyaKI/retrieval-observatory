from __future__ import annotations

import importlib
import os
from typing import Any, Callable, List, Union

from retrieval_observatory.pipeline.multi import MultiStagePipeline
from retrieval_observatory.pipeline.single import SingleStagePipeline
from retrieval_observatory.types import BaseReranker, BaseRetriever


def build_pipeline(
    pipeline_id: str,
    stages: List[Union[BaseRetriever, BaseReranker]],
    k_per_stage: List[int],
    stage_configs: list | None = None,
    stage_cache: object | None = None,
) -> Union[SingleStagePipeline, MultiStagePipeline]:
    if len(stages) == 1:
        return SingleStagePipeline(pipeline_id=pipeline_id, retriever=stages[0], k=k_per_stage[0])
    return MultiStagePipeline(
        pipeline_id=pipeline_id,
        stages=stages,
        k_per_stage=k_per_stage,
        stage_configs=stage_configs,
        stage_cache=stage_cache,
    )


def build_pipeline_from_config(
    pipeline_config: dict,
    corpus: dict | None = None,
    stage_cache: object | None = None,
) -> Union[SingleStagePipeline, MultiStagePipeline]:
    """Build a pipeline from a YAML pipeline config dict. Imports adapters lazily.

    corpus: optional {doc_id: text} dict required for adapter.bm25 and adapter.hf_biencoder stages.
    """
    # Adapters that need corpus are called with (stage_cfg, corpus); others with (stage_cfg,) only.
    _CORPUS_ADAPTERS = {"adapter.bm25", "adapter.hf_biencoder"}

    _ADAPTER_MAP = {
        "adapter.http": _build_http_adapter,
        "adapter.bm25": _build_bm25_adapter,
        "adapter.hf_biencoder": _build_hf_biencoder_adapter,
        "adapter.hf_crossencoder": _build_hf_crossencoder_adapter,
        "adapter.cohere_rerank": _build_cohere_rerank_adapter,
        "adapter.rrf": None,  # handled specially below (needs recursive sub-builder calls)
        # These adapters wrap pre-constructed Python objects and cannot be fully wired from YAML.
        # Use them programmatically: MyAdapter(retriever_obj, ...) then build_pipeline() directly.
        "adapter.pgvector": _build_pgvector_adapter,
        "adapter.import": _build_import_adapter,
    }

    stages = []
    k_per_stage = []
    stage_cfgs_raw = []

    for stage_cfg in pipeline_config["stages"]:
        stage_type = stage_cfg["type"]
        if stage_type not in _ADAPTER_MAP:
            raise ValueError(
                f"Unknown stage type '{stage_type}'. "
                f"Supported: {list(_ADAPTER_MAP.keys())}"
            )
        if stage_type == "adapter.rrf":
            stage, k = _build_rrf_adapter(stage_cfg, corpus)
        else:
            builder = _ADAPTER_MAP[stage_type]
            if stage_type in _CORPUS_ADAPTERS or stage_type == "adapter.import":
                stage, k = builder(stage_cfg, corpus)
            else:
                stage, k = builder(stage_cfg)
        stages.append(stage)
        k_per_stage.append(k)
        stage_cfgs_raw.append(stage_cfg)

    return build_pipeline(
        pipeline_id=pipeline_config["id"],
        stages=stages,
        k_per_stage=k_per_stage,
        stage_configs=stage_cfgs_raw,
        stage_cache=stage_cache,
    )


def _build_bm25_adapter(stage_cfg: dict, corpus: dict | None = None):
    from retrieval_observatory.adapters.bm25_adapter import BM25Adapter

    if corpus is None:
        raise ValueError(
            "adapter.bm25 requires a corpus dict. "
            "The CLI passes this automatically when using a BEIR or custom dataset."
        )
    cfg = stage_cfg.get("config", {})
    k = cfg.get("k", 100)
    adapter = BM25Adapter(
        corpus=corpus,
        retriever_id=stage_cfg.get("retriever_id", "bm25"),
        tokenizer=cfg.get("tokenizer", "whitespace"),
    )
    return adapter, k


def _build_http_adapter(stage_cfg: dict):
    from retrieval_observatory.adapters.http_adapter import HTTPAdapter

    cfg = stage_cfg.get("config", {})
    k = cfg.get("k", 10)
    adapter = HTTPAdapter(
        url=stage_cfg["url"],
        retriever_id=stage_cfg.get("retriever_id", stage_cfg["url"]),
        id_field=cfg.get("id_field", "id"),
        text_field=cfg.get("text_field", "text"),
        score_field=cfg.get("score_field", "score"),
        timeout=cfg.get("timeout", 10.0),
        retry_attempts=cfg.get("retry_attempts", 2),
    )
    return adapter, k


def _build_hf_biencoder_adapter(stage_cfg: dict, corpus: dict | None = None):
    try:
        import faiss  # noqa: F401
        from sentence_transformers import SentenceTransformer  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "adapter.hf_biencoder requires sentence-transformers and faiss-cpu. "
            "Install with: pip install retobs[dense]"
        ) from exc
    from retrieval_observatory.adapters.hf_biencoder_adapter import HFBiEncoderAdapter

    if corpus is None:
        raise ValueError(
            "adapter.hf_biencoder requires a corpus dict. "
            "The CLI passes this automatically when using a BEIR or custom dataset."
        )
    cfg = stage_cfg.get("config", {})
    k = cfg.get("k", 100)
    model_name = cfg.get("model", "sentence-transformers/all-MiniLM-L6-v2")
    adapter = HFBiEncoderAdapter(
        corpus=corpus,
        model_name=model_name,
        retriever_id=stage_cfg.get("retriever_id", model_name),
        batch_size=cfg.get("batch_size", 64),
    )
    return adapter, k


def _build_hf_crossencoder_adapter(stage_cfg: dict):
    try:
        from sentence_transformers import CrossEncoder  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "adapter.hf_crossencoder requires sentence-transformers. "
            "Install with: pip install retobs[dense]"
        ) from exc
    from retrieval_observatory.adapters.hf_adapter import HFCrossEncoderAdapter

    cfg = stage_cfg.get("config", {})
    k = cfg.get("k", 10)
    model_name = cfg.get("model")
    if not model_name:
        raise ValueError("adapter.hf_crossencoder requires config.model (e.g. 'cross-encoder/ms-marco-MiniLM-L-6-v2')")
    adapter = HFCrossEncoderAdapter(
        model_name=model_name,
        retriever_id=stage_cfg.get("retriever_id", model_name),
        batch_size=cfg.get("batch_size", 32),
    )
    return adapter, k


def _build_cohere_rerank_adapter(stage_cfg: dict):
    from retrieval_observatory.adapters.cohere_adapter import CohereRerankAdapter

    cfg = stage_cfg.get("config", {})
    k = cfg.get("k", 10)
    api_key = cfg.get("api_key") or os.environ.get("COHERE_API_KEY")
    if not api_key:
        raise ValueError(
            "adapter.cohere_rerank requires config.api_key or COHERE_API_KEY environment variable."
        )
    adapter = CohereRerankAdapter(
        api_key=api_key,
        model=cfg.get("model", "rerank-english-v3.0"),
        retriever_id=stage_cfg.get("retriever_id", "cohere_rerank"),
    )
    return adapter, k


def _build_rrf_adapter(stage_cfg: dict, corpus: dict | None = None):
    from retrieval_observatory.adapters.rrf_adapter import RRFFusionAdapter

    cfg = stage_cfg.get("config", {})
    top_k = cfg.get("top_k", 100)
    rrf_k = cfg.get("rrf_k", 60)
    fetch_k = cfg.get("fetch_k", 100)

    sub_retriever_cfgs = cfg.get("retrievers", [])
    if not sub_retriever_cfgs:
        raise ValueError(
            "adapter.rrf requires config.retrievers: a list of stage configs (type + config) "
            "for the retrievers to fuse. Example:\n"
            "  - type: adapter.bm25\n"
            "  - type: adapter.hf_biencoder\n"
            "    config: {model: sentence-transformers/all-MiniLM-L6-v2}"
        )

    _CORPUS_ADAPTERS = {"adapter.bm25", "adapter.hf_biencoder"}
    _SUB_BUILDER_MAP = {
        "adapter.http": _build_http_adapter,
        "adapter.bm25": _build_bm25_adapter,
        "adapter.hf_biencoder": _build_hf_biencoder_adapter,
    }

    sub_retrievers = []
    for sub_cfg in sub_retriever_cfgs:
        sub_type = sub_cfg.get("type")
        builder = _SUB_BUILDER_MAP.get(sub_type)
        if builder is None:
            raise ValueError(
                f"adapter.rrf sub-retriever type '{sub_type}' not supported. "
                f"Use one of: {list(_SUB_BUILDER_MAP.keys())}"
            )
        if sub_type in _CORPUS_ADAPTERS:
            retriever, _ = builder(sub_cfg, corpus)
        else:
            retriever, _ = builder(sub_cfg)
        sub_retrievers.append(retriever)

    retriever_id = stage_cfg.get("retriever_id", "rrf")
    adapter = RRFFusionAdapter(
        retrievers=sub_retrievers,
        retriever_id=retriever_id,
        rrf_k=rrf_k,
        fetch_k=fetch_k,
        top_k=top_k,
    )
    return adapter, top_k


def _build_pgvector_adapter(stage_cfg: dict):
    raise ValueError(
        "adapter.pgvector requires a Python embedding function and cannot be fully configured "
        "from YAML alone. Use PgvectorAdapter(...) programmatically and call build_pipeline() directly."
    )


def _load_factory_callable(factory_path: str) -> Callable[..., Any]:
    """Resolve 'module.path:callable' or 'module.path.callable'."""
    if ":" in factory_path:
        module_path, attr = factory_path.rsplit(":", 1)
    else:
        module_path, _, attr = factory_path.rpartition(".")
        if not module_path or not attr:
            raise ValueError(
                f"Invalid factory path '{factory_path}'. "
                "Use 'package.module:callable' or 'package.module.callable'."
            )
    module = importlib.import_module(module_path)
    fn = getattr(module, attr, None)
    if fn is None or not callable(fn):
        raise ValueError(f"Factory '{factory_path}' did not resolve to a callable.")
    return fn


def _build_import_adapter(stage_cfg: dict, corpus: dict | None = None):
    cfg = stage_cfg.get("config", {})
    factory_path = cfg.get("factory")
    if not factory_path:
        raise ValueError(
            "adapter.import requires config.factory "
            "(e.g. 'my_pkg.retrieval:build_retriever' or 'my_pkg.retrieval.build_retriever')."
        )

    factory = _load_factory_callable(factory_path)
    extra_args = cfg.get("args") or {}
    result = factory(corpus, stage_cfg, **extra_args)

    if isinstance(result, tuple) and len(result) == 2:
        adapter, k = result
    else:
        adapter = result
        k = cfg.get("k", 10)

    if not hasattr(adapter, "retrieve") and not hasattr(adapter, "rerank"):
        raise ValueError(
            f"Factory '{factory_path}' must return a retriever/reranker with retrieve() or rerank()."
        )
    return adapter, int(k)
