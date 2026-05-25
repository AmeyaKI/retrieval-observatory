import tempfile
from pathlib import Path

import pytest
import yaml

from retrieval_observatory.config.schema import (
    DatasetConfig,
    ExecutionConfig,
    ExperimentConfig,
    MetricsConfig,
    OutputConfig,
    PipelineConfig,
    StageConfig,
)


SAMPLE_CONFIG = {
    "experiment": {"name": "test-run"},
    "dataset": {"name": "beir/nfcorpus", "split": "test", "max_queries": 10},
    "pipelines": [
        {
            "id": "http_pipeline",
            "stages": [
                {
                    "type": "adapter.http",
                    "url": "http://localhost:8000/retrieve",
                    "config": {"k": 10},
                }
            ],
        }
    ],
    "metrics": {"recall_at_k": [1, 5, 10], "mrr": True},
    "execution": {"concurrency": 4, "timeout_ms": 3000},
    "output": {"store": "sqlite", "db_path": "/tmp/test.db"},
}


def test_parse_config_from_dict():
    cfg = ExperimentConfig.model_validate(SAMPLE_CONFIG)
    assert cfg.experiment.name == "test-run"
    assert cfg.dataset.name == "beir/nfcorpus"
    assert cfg.dataset.max_queries == 10
    assert len(cfg.pipelines) == 1
    assert cfg.pipelines[0].id == "http_pipeline"
    assert cfg.execution.concurrency == 4
    assert cfg.metrics.recall_at_k == [1, 5, 10]


def test_parse_config_from_yaml(tmp_path):
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml.dump(SAMPLE_CONFIG))

    cfg = ExperimentConfig.from_yaml(str(config_file))
    assert cfg.experiment.name == "test-run"
    assert cfg.output.db_path == "/tmp/test.db"


def test_metrics_defaults():
    m = MetricsConfig()
    assert m.recall_at_k == [1, 5, 10]
    assert m.mrr is True
    assert m.ndcg_at_k == [10]
    assert m.temporal_recall_at_k == []


def test_execution_defaults():
    e = ExecutionConfig()
    assert e.concurrency == 8
    assert e.timeout_ms == 5000
    assert e.cache_results is True


def test_stage_config_default_retriever_id():
    stage = StageConfig(type="adapter.http", url="http://localhost:9000/search")
    assert stage.retriever_id == "http://localhost:9000/search"
