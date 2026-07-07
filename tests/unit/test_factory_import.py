from retrieval_observatory.pipeline.factory import _build_import_adapter, build_pipeline_from_config


def test_build_import_adapter_from_example_module():
    corpus = {"d1": "BM25 sparse retrieval", "d2": "dense embeddings"}
    stage_cfg = {
        "type": "adapter.import",
        "retriever_id": "keyword",
        "config": {
            "factory": "examples.advanced.custom_retriever.retriever:build_retriever",
            "k": 3,
        },
    }
    # Import via examples path on sys.path
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    custom_dir = str(root / "examples" / "advanced" / "custom_retriever")
    if custom_dir not in sys.path:
        sys.path.insert(0, custom_dir)

    stage_cfg["config"]["factory"] = "retriever:build_retriever"
    adapter, k = _build_import_adapter(stage_cfg, corpus)
    assert k == 3
    assert adapter.retriever_id == "keyword"


def test_build_pipeline_from_config_import():
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    custom_dir = str(root / "examples" / "advanced" / "custom_retriever")
    if custom_dir not in sys.path:
        sys.path.insert(0, custom_dir)

    corpus = {"d1": "BM25 sparse", "d2": "dense vectors"}
    pipeline_config = {
        "id": "kw",
        "stages": [
            {
                "type": "adapter.import",
                "retriever_id": "keyword",
                "config": {"factory": "retriever:build_retriever", "k": 2},
            }
        ],
    }
    pipeline = build_pipeline_from_config(pipeline_config, corpus=corpus)
    assert pipeline.pipeline_id == "kw"
