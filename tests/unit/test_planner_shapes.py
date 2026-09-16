"""Planner discovery on the three project shapes, plus the rules that keep test code and
name-only matches out of the plan."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from retrieval_observatory.integrations.apply import apply_integration_plan
from retrieval_observatory.integrations.planner import build_integration_plan

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
from integration_projects import materialize  # noqa: E402


def test_proj_a_plan_has_only_retrieve_and_skips_tests(tmp_path: Path) -> None:
    plan = build_integration_plan(materialize("proj_a", tmp_path))
    assert [(op.symbol, op.op_type, op.confidence) for op in plan.operators] == [("retrieve", "SOURCE", 0.9)]
    assert plan.scenarios[0].expected_operator_ids == ("retrieve",)
    assert [patch.relative_path for patch in plan.patches] == ["search/retriever.py"]
    assert plan.discovery["entrypoint"] == {"file": "search/retriever.py", "symbol": "retrieve", "kind": "function"}
    replacement = plan.patches[0].replacement
    assert replacement.index("@trace_scope(") < replacement.index("@observe(")
    assert 'db_path=".retobs/results.db"' in replacement


def test_proj_b_plan_instruments_class_methods_and_treats_route_as_entrypoint(tmp_path: Path) -> None:
    plan = build_integration_plan(materialize("proj_b", tmp_path))
    assert [(op.symbol, op.op_type) for op in plan.operators] == [("Searcher.search", "SOURCE"), ("Searcher.rerank", "RERANK")]
    assert [op.op_id for op in plan.operators] == ["searcher_search", "searcher_rerank"]
    assert plan.framework == "fastapi"
    assert plan.discovery["entrypoint"] == {"file": "app/main.py", "symbol": "search", "kind": "http_route"}
    main_patch = next(patch for patch in plan.patches if patch.relative_path == "app/main.py")
    assert "@observe(" not in main_patch.replacement
    lines = main_patch.replacement.splitlines()
    assert lines[lines.index('@app.post("/search")') + 1].startswith("@trace_scope(")
    searcher_patch = next(patch for patch in plan.patches if patch.relative_path == "app/searcher.py")
    assert '    @observe("SOURCE", op_id="searcher_search", parent_ids=())\n    def search(' in searcher_patch.replacement


def test_proj_c_plan_finds_the_retriever_method_and_langchain(tmp_path: Path) -> None:
    plan = build_integration_plan(materialize("proj_c", tmp_path))
    assert [(op.symbol, op.op_type) for op in plan.operators] == [("KeywordRetriever._get_relevant_documents", "SOURCE")]
    assert plan.framework == "langchain"
    assert [item["symbol"] for item in plan.discovery["low_confidence_operators"]] == ["build_retriever"]
    assert plan.discovery["low_confidence_operators"][0]["confidence"] == 0.6
    assert plan.discovery["entrypoint"]["symbol"] == "KeywordRetriever._get_relevant_documents"
    plan.validate_for_apply()


def test_name_only_hits_are_not_instrumented(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "def build_retriever(k=4):\n    return object()\n\n"
        "def retrieve(query, k=4):\n    return []\n\n"
        "def search_config():\n    pass\n",
        encoding="utf-8",
    )
    plan = build_integration_plan(tmp_path)
    assert [op.symbol for op in plan.operators] == ["retrieve"]
    assert {item["symbol"] for item in plan.discovery["low_confidence_operators"]} == {"build_retriever", "search_config"}


def test_test_files_and_test_functions_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "search.py").write_text("def retrieve(query):\n    return []\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_search.py").write_text("def retrieve(query):\n    return []\n", encoding="utf-8")
    (tmp_path / "search_test.py").write_text("def search(query):\n    return []\n", encoding="utf-8")
    (tmp_path / "helpers.py").write_text("def test_retrieve(query):\n    return []\n", encoding="utf-8")
    plan = build_integration_plan(tmp_path)
    assert [op.symbol for op in plan.operators] == ["retrieve"]
    assert [patch.relative_path for patch in plan.patches] == ["search.py"]


def test_replanning_an_applied_project_adds_nothing(tmp_path: Path) -> None:
    root = materialize("proj_a", tmp_path)
    plan = build_integration_plan(root)
    apply_integration_plan(plan)
    again = build_integration_plan(root)
    assert again.patches == ()
    with pytest.raises(ValueError, match="already applied \\(manifest present\\)"):
        apply_integration_plan(plan)
