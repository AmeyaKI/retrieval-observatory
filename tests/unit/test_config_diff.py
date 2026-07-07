from __future__ import annotations

from retrieval_observatory.config.diff import diff_configs
from retrieval_observatory.config.schema import ExperimentConfig


def _config(pipelines: list) -> ExperimentConfig:
    return ExperimentConfig(
        experiment={"name": "diff-test"},
        dataset={"name": "beir/nfcorpus"},
        pipelines=pipelines,
    )


def test_diff_detects_added_pipeline():
    before = _config([{"id": "bm25", "stages": [{"type": "adapter.bm25", "config": {"k": 10}}]}])
    after = _config(
        [
            {"id": "bm25", "stages": [{"type": "adapter.bm25", "config": {"k": 10}}]},
            {"id": "dense", "stages": [{"type": "adapter.hf_biencoder", "config": {"k": 10}}]},
        ]
    )
    result = diff_configs(before, after)
    by_id = {p.pipeline_id: p for p in result.pipeline_diffs}
    assert by_id["bm25"].change == "unchanged"
    assert by_id["dense"].change == "added"
    assert result.has_changes is True


def test_diff_detects_removed_pipeline():
    before = _config(
        [
            {"id": "bm25", "stages": [{"type": "adapter.bm25", "config": {"k": 10}}]},
            {"id": "dense", "stages": [{"type": "adapter.hf_biencoder", "config": {"k": 10}}]},
        ]
    )
    after = _config([{"id": "bm25", "stages": [{"type": "adapter.bm25", "config": {"k": 10}}]}])
    result = diff_configs(before, after)
    by_id = {p.pipeline_id: p for p in result.pipeline_diffs}
    assert by_id["dense"].change == "removed"


def test_diff_detects_changed_stage_param():
    before = _config([{"id": "bm25", "stages": [{"type": "adapter.bm25", "config": {"k": 10}}]}])
    after = _config([{"id": "bm25", "stages": [{"type": "adapter.bm25", "config": {"k": 20}}]}])
    result = diff_configs(before, after)
    pipeline_diff = result.pipeline_diffs[0]
    assert pipeline_diff.change == "changed"
    assert pipeline_diff.stage_diffs[0].change == "changed"
    assert pipeline_diff.stage_diffs[0].before["config"]["k"] == 10
    assert pipeline_diff.stage_diffs[0].after["config"]["k"] == 20


def test_diff_reports_no_changes_when_identical():
    config = _config([{"id": "bm25", "stages": [{"type": "adapter.bm25", "config": {"k": 10}}]}])
    result = diff_configs(config, config)
    assert result.has_changes is False


def test_diff_configs_cli_runs(tmp_path):
    from typer.testing import CliRunner

    from retrieval_observatory.cli import app

    config_a = tmp_path / "a.yaml"
    config_b = tmp_path / "b.yaml"
    config_a.write_text(
        "experiment:\n  name: t\ndataset:\n  name: beir/nfcorpus\n"
        "pipelines:\n  - id: bm25\n    stages:\n      - type: adapter.bm25\n        config:\n          k: 10\n"
    )
    config_b.write_text(
        "experiment:\n  name: t\ndataset:\n  name: beir/nfcorpus\n"
        "pipelines:\n  - id: bm25\n    stages:\n      - type: adapter.bm25\n        config:\n          k: 20\n"
    )
    runner = CliRunner()
    result = runner.invoke(app, ["diff-configs", str(config_a), str(config_b)])
    assert result.exit_code == 0
    assert "bm25" in result.output
    assert "changed" in result.output
