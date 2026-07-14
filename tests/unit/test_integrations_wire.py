"""setup_project and verify_project."""
from pathlib import Path

import pytest

from retrieval_observatory.integrations.wire import load_manifest, plan_project, setup_project, verify_project


@pytest.mark.parametrize(
    ("framework", "source", "action"),
    [
        ("python", "def retrieve(query):\n    return []\n", "wrap_or_delegate"),
        ("fastapi", "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/search')\ndef search(q: str): return []\n", "instrument_app"),
        ("http", "from fastapi import FastAPI\napp = FastAPI()\n@app.post('/retrieve')\ndef retrieve(): return []\n", "configure_http_adapter"),
        ("langchain", "from langchain_core.runnables import RunnableLambda\ndef retrieve(query): return []\n", "add_callback"),
        ("llamaindex", "from llama_index.core import VectorStoreIndex\ndef retrieve(query): return []\n", "add_callback"),
    ],
)
def test_first_class_integration_plan_has_minimal_patch(tmp_path: Path, framework: str, source: str, action: str):
    (tmp_path / "app.py").write_text(source, encoding="utf-8")
    result = plan_project(tmp_path, framework=framework)
    assert result["status"] == "planned"
    assert result["support"]["level"] == "first_class"
    assert result["files_written"] == []
    assert any(patch["action"] == action for patch in result["proposed_patches"])
    assert result["verification_criteria"]


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
async def test_verify_project_not_verified_without_runs(tmp_path: Path):
    setup_project(tmp_path, framework="python")
    out = await verify_project(tmp_path)
    assert out["status"] == "not_verified"
    manifest = load_manifest(tmp_path)
    assert manifest["status"] == "setup_complete"
