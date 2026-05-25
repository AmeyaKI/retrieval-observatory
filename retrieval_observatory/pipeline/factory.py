from __future__ import annotations

from typing import List, Union

from retrieval_observatory.pipeline.multi import MultiStagePipeline
from retrieval_observatory.pipeline.single import SingleStagePipeline
from retrieval_observatory.types import BaseReranker, BaseRetriever


def build_pipeline(
    pipeline_id: str,
    stages: List[Union[BaseRetriever, BaseReranker]],
    k_per_stage: List[int],
) -> Union[SingleStagePipeline, MultiStagePipeline]:
    if len(stages) == 1:
        return SingleStagePipeline(pipeline_id=pipeline_id, retriever=stages[0])
    return MultiStagePipeline(pipeline_id=pipeline_id, stages=stages, k_per_stage=k_per_stage)


def build_pipeline_from_config(
    pipeline_config: dict,
    corpus: dict | None = None,
) -> Union[SingleStagePipeline, MultiStagePipeline]:
    """Build a pipeline from a YAML pipeline config dict. Imports adapters lazily.

    corpus: optional {doc_id: text} dict required for adapter.bm25 stages.
    """
    _ADAPTER_MAP = {
        "adapter.http": _build_http_adapter,
        "adapter.bm25": _build_bm25_adapter,
    }

    stages = []
    k_per_stage = []

    for stage_cfg in pipeline_config["stages"]:
        stage_type = stage_cfg["type"]
        builder = _ADAPTER_MAP.get(stage_type)
        if builder is None:
            raise ValueError(
                f"Unknown stage type '{stage_type}'. "
                f"Supported: {list(_ADAPTER_MAP.keys())}"
            )
        if stage_type == "adapter.bm25":
            stage, k = builder(stage_cfg, corpus)
        else:
            stage, k = builder(stage_cfg)
        stages.append(stage)
        k_per_stage.append(k)

    return build_pipeline(
        pipeline_id=pipeline_config["id"],
        stages=stages,
        k_per_stage=k_per_stage,
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
    )
    return adapter, k
