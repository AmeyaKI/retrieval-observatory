"""Tests for config runtime helpers (CLI/MCP path parity)."""
from pathlib import Path

from retrieval_observatory.config.runtime import prepare_config_runtime, resolve_config_paths
from retrieval_observatory.config.schema import ExperimentConfig


def test_resolve_config_paths_relative(tmp_path: Path):
    queries = tmp_path / "queries.jsonl"
    queries.write_text('{"query_id":"q1","text":"hello"}\n', encoding="utf-8")
    cfg = ExperimentConfig.model_validate(
        {
            "experiment": {"name": "t"},
            "dataset": {"type": "custom", "name": "custom", "queries_path": "queries.jsonl"},
            "pipelines": [{"id": "p", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]}],
        }
    )
    resolve_config_paths(cfg, tmp_path)
    assert Path(cfg.dataset.queries_path).is_absolute()
    assert cfg.dataset.queries_path == str(queries.resolve())


def test_prepare_config_runtime_adds_sys_path(tmp_path: Path, monkeypatch):
    import sys

    marker = tmp_path / "marker.txt"
    marker.write_text("ok", encoding="utf-8")
    cfg = ExperimentConfig.model_validate(
        {
            "experiment": {"name": "t"},
            "dataset": {"name": "beir/nfcorpus", "max_queries": 1},
            "pipelines": [{"id": "p", "stages": [{"type": "adapter.bm25", "retriever_id": "bm25"}]}],
        }
    )
    config_dir = str(tmp_path.resolve())
    if config_dir in sys.path:
        sys.path.remove(config_dir)
    prepare_config_runtime(cfg, tmp_path)
    assert config_dir in sys.path
