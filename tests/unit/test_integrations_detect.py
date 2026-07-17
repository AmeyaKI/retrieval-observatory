"""Framework and entrypoint detection for the canonical integration planner."""
from pathlib import Path

from retrieval_observatory.integrations.detect import detect_project


def test_detect_python_retrieve_function(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "search.py").write_text(
        "def retrieve(query: str):\n    return []\n",
        encoding="utf-8",
    )
    result = detect_project(tmp_path)
    assert result.framework == "python"
    assert result.entrypoints
    assert result.entrypoints[0].symbol == "retrieve"


def test_detect_langchain(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "from langchain_core.retrievers import BaseRetriever\n",
        encoding="utf-8",
    )
    result = detect_project(tmp_path)
    assert result.framework == "langchain"


def test_detect_fastapi_route(tmp_path: Path):
    (tmp_path / "server.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n@app.get('/search')\ndef search(q: str): ...\n",
        encoding="utf-8",
    )
    result = detect_project(tmp_path)
    assert result.framework in {"fastapi", "http"}
    assert result.http_routes
