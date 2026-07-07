"""setup_project and verify_project."""
from pathlib import Path

import pytest

from retrieval_observatory.integrations.wire import load_manifest, setup_project, verify_project


def test_setup_project_writes_manifest_and_retos(tmp_path: Path):
    (tmp_path / "pipeline.py").write_text("def retrieve(q): return []\n", encoding="utf-8")
    out = setup_project(tmp_path, framework="python")
    assert out["status"] == "setup_complete"
    assert (tmp_path / "retobs" / "config.yaml").exists()
    assert (tmp_path / "retobs" / "queries.jsonl").exists()
    assert (tmp_path / "RETOS.md").exists()
    assert (tmp_path / ".retobs" / "manifest.yaml").exists()
    manifest = load_manifest(tmp_path)
    assert manifest["framework"] == "python"
    assert manifest["status"] == "setup_complete"
    assert out["wiring_brief"]["patches"]


@pytest.mark.asyncio
async def test_verify_project_ready_without_runs(tmp_path: Path):
    setup_project(tmp_path, framework="python")
    out = await verify_project(tmp_path)
    assert out["status"] == "ready"
    manifest = load_manifest(tmp_path)
    assert manifest["status"] == "ready"
