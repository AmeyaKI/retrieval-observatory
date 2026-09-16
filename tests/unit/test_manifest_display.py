import sys
import types
from pathlib import Path

from retrieval_observatory.config.schema import ExperimentConfig
from retrieval_observatory.runner.manifest import build_pipeline_display, build_run_manifest

_ROOT = Path(__file__).resolve().parents[2]


def test_manifest_model_inventory_reads_config_model_for_shipped_graph_config():
    cfg = ExperimentConfig.from_yaml(str(_ROOT / "examples/advanced/hybrid_fiqa_demo/config_scifact_graph.yaml"))
    models = {row["operator_id"]: row["model"] for row in build_run_manifest(cfg, {"name": "x"})["models"]}
    assert models["dense"] == "sentence-transformers/all-MiniLM-L6-v2"
    assert models["rerank"] == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    assert models["bm25"] is None


def test_manifest_and_factory_agree_on_top_level_stage_model(monkeypatch):
    from retrieval_observatory.pipeline.factory import _build_cohere_rerank_adapter, _build_hf_crossencoder_adapter

    cfg = ExperimentConfig.model_validate({
        "experiment": {"name": "e"},
        "dataset": {"name": "custom", "queries_path": "q"},
        "pipelines": [{"id": "p", "stages": [
            {"type": "adapter.bm25"},
            {"type": "adapter.hf_crossencoder", "model": "cross-encoder/ms-marco-MiniLM-L-6-v2"},
            {"type": "adapter.cohere_rerank", "model": "rerank-v3.5", "config": {"api_key": "k"}},
        ]}],
    })
    models = [row["model"] for row in build_run_manifest(cfg, {})["models"]]
    assert models == [None, "cross-encoder/ms-marco-MiniLM-L-6-v2", "rerank-v3.5"]

    # The builders only import-check sentence-transformers; the adapter itself loads lazily.
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(CrossEncoder=object))
    adapter, _ = _build_hf_crossencoder_adapter(cfg.pipelines[0].stages[1].model_dump())
    assert adapter.model_name == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    adapter, _ = _build_cohere_rerank_adapter(cfg.pipelines[0].stages[2].model_dump())
    assert adapter.model == "rerank-v3.5"
    # config.model still wins over the top-level fallback.
    adapter, _ = _build_cohere_rerank_adapter({"type": "adapter.cohere_rerank", "model": "top", "config": {"api_key": "k", "model": "inner"}})
    assert adapter.model == "inner"


def test_build_pipeline_display_stage_labels_and_ablation_duplicates():
    cfg = ExperimentConfig.model_validate(
        {
            "experiment": {"name": "t"},
            "dataset": {"name": "beir/fiqa"},
            "stages": {
                "bm25": {"type": "adapter.bm25", "retriever_id": "bm25"},
                "rerank": {"type": "adapter.hf_crossencoder", "retriever_id": "cross_rerank"},
            },
            "combinations": {"include": [["bm25", "rerank"]], "ablations": True},
            "pipelines": [],
        }
    )
    display = build_pipeline_display(cfg)
    assert display["stage_labels"]["bm25"] == ["bm25"]
    assert display["stage_labels"]["bm25__rerank"] == ["bm25", "cross_rerank"]
    dupes = display["duplicate_ablation_stages"]
    assert any(
        d["pipeline_id"] == "bm25__rerank" and d["stage_index"] == 0 and d["equivalent_pipeline_id"] == "bm25"
        for d in dupes
    )
