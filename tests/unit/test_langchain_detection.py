"""LangChain retrievers are recognized by class when langchain-core is importable and by the
surviving duck-typed contract otherwise; framework detection is not outvoted by plain files."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from retrieval_observatory.cli import app
from retrieval_observatory.integrations.detect import detect_project
from retrieval_observatory.mcp.server import _integrate_project
from retrieval_observatory.sdk.wrappers import _is_langchain_retriever


class _DuckRetriever:
    def invoke(self, query):
        return []

    def _get_relevant_documents(self, query, *, run_manager=None):
        return []


class _NotARetriever:
    def invoke(self, query):
        return []


def test_duck_typed_retriever_without_public_alias_is_recognized() -> None:
    assert _is_langchain_retriever(_DuckRetriever())
    assert not _is_langchain_retriever(_NotARetriever())


def test_base_retriever_subclass_is_recognized_by_isinstance() -> None:
    langchain_core = pytest.importorskip("langchain_core")
    from langchain_core.retrievers import BaseRetriever

    class Keyword(BaseRetriever):
        def _get_relevant_documents(self, query, *, run_manager):
            return []

    assert _is_langchain_retriever(Keyword())
    del langchain_core


def test_framework_signal_beats_the_python_baseline(tmp_path: Path) -> None:
    for index in range(5):
        (tmp_path / f"helper{index}.py").write_text("def util():\n    return 1\n", encoding="utf-8")
    (tmp_path / "retriever.py").write_text("from langchain_core.retrievers import BaseRetriever\n", encoding="utf-8")
    assert detect_project(tmp_path).framework == "langchain"


def test_cli_framework_override_reaches_the_plan(tmp_path: Path) -> None:
    (tmp_path / "search.py").write_text("def retrieve(query):\n    return []\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["integrate", str(tmp_path), "--phase", "plan", "--framework", "http"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["plan"]["framework"] == "http"


async def test_mcp_framework_override_reaches_the_plan(tmp_path: Path) -> None:
    (tmp_path / "search.py").write_text("def retrieve(query):\n    return []\n", encoding="utf-8")
    planned = await _integrate_project(project_root=str(tmp_path), phase="plan", framework="llamaindex")
    assert planned["plan"]["framework"] == "llamaindex"
