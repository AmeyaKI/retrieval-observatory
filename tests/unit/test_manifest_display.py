from retrieval_observatory.config.schema import ExperimentConfig
from retrieval_observatory.runner.manifest import build_pipeline_display


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
