"""Planner rules for large, messy repositories: import roots, non-runtime dirs, operator shape,
unique op_ids, validated judgments, and scenarios that call the entrypoint with a real query."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from retrieval_observatory.integrations import planner
from retrieval_observatory.integrations.detect import is_non_runtime_path
from retrieval_observatory.integrations.planner import SCENARIO_QUERY_TEXT, build_integration_plan

QUERIES = '{"query_id": "q1", "text": "widget pricing"}\n{"query_id": "q2", "text": "widget setup"}\n'
QRELS = '{"query_id": "q1", "relevant_doc_ids": ["d1"]}\n{"query_id": "q2", "relevant_doc_ids": ["d2"]}\n'
CORPUS = '{"id": "d1", "text": "pricing"}\n{"id": "d2", "text": "setup"}\n'
APP = "def bm25(query):\n    return []\n\ndef retrieve(query):\n    return bm25(query)\n"


def _project(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _low(plan, reason: str) -> set[str]:
    return {item["symbol"] for item in plan.discovery["low_confidence_operators"] if item.get("reason") == reason}


def _run(command: str, root: Path) -> subprocess.CompletedProcess[str]:
    argv = shlex.split(command)
    assert argv[:2] == ["python", "-c"]
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    return subprocess.run([sys.executable, *argv[1:]], cwd=root, env=env, capture_output=True, text=True, timeout=60)


# -- import roots ---------------------------------------------------------------------------------


def test_packages_below_a_non_package_dir_are_reachable_and_runnable(tmp_path: Path) -> None:
    root = _project(tmp_path, {
        "services/api/ticket_search/__init__.py": "",
        "services/api/ticket_search/lanes.py": "def bm25(query):\n    return [{'id': 'd1', 'score': 1.0}]\n",
        "services/api/ticket_search/entry.py": (
            "from ticket_search.lanes import bm25\n\n"
            "def retrieve(query):\n    print(query)\n    return bm25(query)\n"
        ),
        "tools/search_dump.py": "def search_dump(query):\n    return [query]\n",
    })
    plan = build_integration_plan(root)

    assert plan.discovery["entrypoint"]["file"] == "services/api/ticket_search/entry.py"
    assert {op.symbol for op in plan.operators} == {"bm25", "retrieve"}
    assert _low(plan, "unreachable_from_entrypoint") == {"search_dump"}
    command = plan.scenarios[0].command
    assert command.startswith("python -c") and "sys.path.insert(0, 'services/api')" in command
    completed = _run(command, root)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == SCENARIO_QUERY_TEXT


def test_no_sys_path_insert_when_the_import_root_is_the_project_root(tmp_path: Path) -> None:
    plan = build_integration_plan(_project(tmp_path, {"app.py": APP}))

    assert plan.scenarios[0].command == f'python -c "from app import retrieve; retrieve({SCENARIO_QUERY_TEXT!r})"'


def test_an_entrypoint_that_reaches_no_operator_proposes_none(tmp_path: Path) -> None:
    # ``retrieve(request)`` takes no query-like parameter, so it is not itself an operator, and it
    # loads the lane dynamically, so no import reaches ``bm25_search``.
    root = _project(tmp_path, {
        "service/entry.py": (
            "import importlib\n\n"
            "def retrieve(request):\n    return importlib.import_module('lanes.bm25_lane').bm25_search(request['q'])\n"
        ),
        "lanes/bm25_lane.py": "def bm25_search(query):\n    return []\n",
    })
    plan = build_integration_plan(root)

    assert plan.discovery["entrypoint"]["file"] == "service/entry.py"
    assert plan.operators == ()
    assert _low(plan, "unreachable_from_entrypoint") == {"bm25_search"}
    assert [item for item in plan.unresolved if "no operator is reachable by import from service/entry.py:retrieve" in item]
    assert "no retrieval operators discovered" not in plan.unresolved


# -- non-runtime dirs -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("bench/run.py", True), ("BENCH/run.py", True), ("Evals/run.py", True), ("bench_suite/run.py", True),
        ("eval_labels/load.py", True), ("evaluation/x.py", True), ("pkg/harness/x.py", True),
        ("reports/x.py", True), ("scripts/x.py", True), ("notebooks/x.py", True), ("fixtures/x.py", True),
        ("examples/x.py", True), ("experiments/x.py", True),
        ("app/search.py", False), ("services/retrieval/x.py", False), ("bench.py", False), ("app/evaluator_x.py", False),
    ],
)
def test_non_runtime_dirs(path: str, expected: bool) -> None:
    assert is_non_runtime_path(path) is expected


def test_non_runtime_files_are_never_proposed_or_the_entrypoint(tmp_path: Path) -> None:
    root = _project(tmp_path, {
        "app.py": APP,
        "benchmarks/driver.py": "from app import retrieve\n\ndef search(query):\n    return retrieve(query)\n\ndef rerank_all(query, results):\n    return results\n",
    })
    plan = build_integration_plan(root)

    assert plan.discovery["entrypoint"]["file"] == "app.py"
    assert {op.symbol for op in plan.operators} == {"bm25", "retrieve"}
    assert _low(plan, "non_runtime_dir") == {"search", "rerank_all"}


# -- operator shape -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "op_type"),
    [
        ("aggregate_by_system", None), ("aggregate_by_system_and_category", None), ("navigate", None),
        ("researcher_notes", None), ("route_query", "GATE"), ("intent_gate", "GATE"), ("choose_route", "GATE"),
        ("QueryRouter", "GATE"), ("rrf", "FUSE"), ("reciprocal_rank_fusion", "FUSE"), ("temporal_filter", "FILTER"),
        ("rerank", "RERANK"), ("cross_encoder_score", "RERANK"), ("bm25", "SOURCE"), ("BM25Retriever", "SOURCE"),
        ("_get_relevant_documents", "SOURCE"), ("hybrid_search", "SOURCE"), ("keyword_search", "SOURCE"),
    ],
)
def test_type_rules_match_name_tokens(name: str, op_type: str | None) -> None:
    assert planner._op_type(name) == op_type


def test_predicates_factories_and_formatters_are_not_operators(tmp_path: Path) -> None:
    root = _project(tmp_path, {
        "app.py": (
            "def is_search_ready(query):\n    return True\n\n"
            "def has_filter_intent(query) -> bool:\n    return 'only' in query\n\n"
            "def get_reranker():\n    return object()\n\n"
            "def format_route(route):\n    return f'route={route}'\n\n"
            "def search_label(query) -> str:\n    return query.upper()\n\n"
            "def range_filter(candidates):\n    return len(candidates) > 2 and bool(candidates)\n\n"
            "def dense_hits(query):\n    return not query\n\n"
            "def filter_count(query, candidates) -> int:\n    return 3\n\n"
            "def filter_query(query):\n    return [query]\n\n"
            "def date_gate(candidates) -> bool:\n    return True\n\n"
            "def intent_gate(flag):\n    return 'hybrid'\n\n"
            "def route_query(query):\n    return 'hybrid' if 'how' in query else 'keyword'\n\n"
            "def bm25(query):\n    return []\n\n"
            "def retrieve(query):\n    route_query(query)\n    return bm25(query)\n"
        ),
    })
    plan = build_integration_plan(root)

    assert {op.symbol for op in plan.operators} == {"route_query", "bm25", "retrieve"}
    assert _low(plan, "not_operator_shape") == {
        "is_search_ready", "has_filter_intent", "get_reranker", "format_route", "search_label", "range_filter",
        "dense_hits", "filter_count", "filter_query", "date_gate", "intent_gate",
    }
    assert all("confidence" in item for item in plan.discovery["low_confidence_operators"])


# -- unique op_ids --------------------------------------------------------------------------------


def test_duplicate_op_ids_are_qualified_by_module(tmp_path: Path) -> None:
    root = _project(tmp_path, {
        "orders/__init__.py": "",
        "orders/keyword.py": "def rerank(query, candidates):\n    return candidates\n\ndef bm25(query):\n    return rerank(query, [])\n",
        "orders/vector.py": "def rerank(query, candidates):\n    return candidates\n\ndef dense(query):\n    return rerank(query, [])\n",
        "orders/entry.py": "from orders.keyword import bm25\nfrom orders.vector import dense\n\ndef retrieve(query):\n    return bm25(query) + dense(query)\n",
    })
    plan = build_integration_plan(root)

    ids = {(op.relative_path, op.symbol): op.op_id for op in plan.operators}
    assert ids[("orders/keyword.py", "rerank")] == "orders_keyword__rerank"
    assert ids[("orders/vector.py", "rerank")] == "orders_vector__rerank"
    ops = {op.op_id: op for op in plan.operators}
    assert ops["bm25"].parent_ids == ("orders_keyword__rerank",)
    assert ops["dense"].parent_ids == ("orders_vector__rerank",)
    assert ids[("orders/entry.py", "retrieve")] == "retrieve"


def test_input_mappings_follow_qualified_parent_ids(tmp_path: Path) -> None:
    root = _project(tmp_path, {
        "orders/__init__.py": "",
        "orders/hybrid.py": (
            "def bm25(query):\n    return []\n\ndef dense(query):\n    return []\n\n"
            "def fuse(bm25, dense):\n    return bm25 + dense\n\n"
            "def hybrid_search(query):\n    return fuse(bm25(query), dense(query))\n"
        ),
        "orders/other.py": "def bm25(query):\n    return []\n",
        "orders/entry.py": "from orders.hybrid import hybrid_search\nfrom orders.other import bm25\n\ndef retrieve(query):\n    return hybrid_search(query) + bm25(query)\n",
    })
    plan = build_integration_plan(root)

    fuse = next(op for op in plan.operators if op.symbol == "fuse")
    assert fuse.parent_ids == ("orders_hybrid__bm25", "dense")
    # The renamed parent no longer matches a parameter name: the mapping is not exact, and it is asked about.
    assert fuse.input_mapping == "default"
    assert any(question.startswith("operator fuse ") for question in plan.open_questions)


def test_loose_modules_with_one_name_still_get_distinct_ids(tmp_path: Path) -> None:
    root = _project(tmp_path, {
        "keyword_lane/lanes.py": "def rerank(query, candidates):\n    return candidates\n",
        "vector_lane/lanes.py": "def rerank(query, candidates):\n    return candidates\n",
        "app.py": (
            "import sys\nfrom keyword_lane import lanes as keyword\nfrom vector_lane import lanes as vector\n\n"
            "def retrieve(query):\n    return keyword.rerank(query, []) + vector.rerank(query, [])\n"
        ),
    })
    plan = build_integration_plan(root)

    ids = {op.relative_path: op.op_id for op in plan.operators if op.symbol == "rerank"}
    assert ids == {"keyword_lane/lanes.py": "keyword_lane_lanes__rerank", "vector_lane/lanes.py": "vector_lane_lanes__rerank"}
    plan.validate_for_apply()


def test_validate_for_apply_rejects_duplicate_op_ids(tmp_path: Path) -> None:
    plan = build_integration_plan(_project(tmp_path, {"app.py": APP}))
    duplicated = replace(plan, operators=tuple(replace(op, op_id="bm25") for op in plan.operators))

    with pytest.raises(ValueError, match="duplicate operator op_id: bm25"):
        duplicated.validate_for_apply()


# -- judgments ------------------------------------------------------------------------------------


def test_the_directory_holding_queries_and_qrels_wins(tmp_path: Path) -> None:
    root = _project(tmp_path, {
        "app.py": APP,
        "a_bench/queries.jsonl": '{"query_id": "b1", "text": "bench"}\n',
        "a_labels/judgments.jsonl": '{"query_id": "zz", "relevant_doc_ids": ["nope"]}\n',
        "data/queries.jsonl": QUERIES, "data/qrels.jsonl": QRELS, "data/corpus.jsonl": CORPUS,
    })
    plan = build_integration_plan(root)

    assert (plan.judgments["queries"], plan.judgments["qrels"], plan.judgments["corpus"], plan.judgments["status"]) == (
        "data/queries.jsonl", "data/qrels.jsonl", "data/corpus.jsonl", "resolved",
    )
    assert not any("judgments" in question for question in plan.open_questions)
    assert plan.scenarios[0].query_text == "widget pricing"


@pytest.mark.parametrize(
    ("qrels", "corpus", "note"),
    [
        ('{"query_id": "other", "relevant_doc_ids": ["d1"]}\n', CORPUS, "none of the 1 qrels query ids"),
        (QRELS, '{"id": "d1", "text": "pricing"}\n{"id": "d3", "text": "other"}\n', "1 of 2 qrels doc ids are not in the corpus"),
        (QRELS, "", "is empty"),
        ('{"query_id": "q1", "relevant_doc_ids": ["d1"]}\n{"query_id": "q9", "relevant_doc_ids": ["d1"]}\n', CORPUS, None),
    ],
)
def test_invalid_judgment_files_stay_candidate(tmp_path: Path, qrels: str, corpus: str, note: str | None) -> None:
    root = _project(tmp_path, {"app.py": APP, "data/queries.jsonl": QUERIES, "data/qrels.jsonl": qrels, "data/corpus.jsonl": corpus})
    plan = build_integration_plan(root)

    if note is None:
        # Partial overlap passes; the missing count is still reported.
        assert plan.judgments["status"] == "resolved"
        assert any("1 of 2 qrels query ids are not in the queries" in item for item in plan.judgments["notes"])
        return
    assert plan.judgments["status"] == "candidate"
    assert any(note in item for item in plan.judgments["notes"]), plan.judgments["notes"]
    assert any(question.startswith("judgments are candidate") for question in plan.open_questions)
    assert plan.expected_capabilities["judgment_mapping"] == "unavailable"
    assert next(action for action in plan.actions if action.kind == "benchmark_setup").command is None


def test_judgment_files_evaluate_cannot_read_stay_candidate(tmp_path: Path) -> None:
    root = _project(tmp_path, {
        "app.py": APP,
        "data/queries.jsonl": '{"query_id": "q1", "query": "no text key"}\n',
        "data/qrels.jsonl": QRELS,
    })
    plan = build_integration_plan(root)

    assert plan.judgments["status"] == "candidate"
    assert any("retobs evaluate" in item for item in plan.judgments["notes"])
    assert plan.scenarios[0].query_text == SCENARIO_QUERY_TEXT
    assert any("placeholder" in question for question in plan.open_questions)


def test_judgment_validation_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner, "JUDGMENT_ROW_LIMIT", 1)
    root = _project(tmp_path, {"app.py": APP, "data/queries.jsonl": QUERIES, "data/qrels.jsonl": QRELS, "data/corpus.jsonl": CORPUS})
    plan = build_integration_plan(root)

    assert plan.judgments["status"] == "resolved"
    assert any("first 1 rows" in item for item in plan.judgments["notes"])


# -- scenarios ------------------------------------------------------------------------------------


def test_scenario_query_with_quotes_survives_the_shell(tmp_path: Path) -> None:
    text = 'the "widget\'s" price $HOME `x` \\n'
    root = _project(tmp_path, {
        "app.py": "def retrieve(query):\n    print(query)\n    return []\n",
        "data/queries.jsonl": json.dumps({"query_id": "q1", "text": text}) + "\n",
        "data/qrels.jsonl": '{"query_id": "q1", "relevant_doc_ids": ["d1"]}\n',
    })
    plan = build_integration_plan(root)

    assert [scenario.query_text for scenario in plan.scenarios] == [text, text]
    completed = _run(plan.scenarios[0].command, root)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout[:-1] == text


# -- entrypoint candidates ------------------------------------------------------------------------


def test_the_real_entrypoint_is_chosen_behind_many_decoys(tmp_path: Path) -> None:
    # Twelve runtime ``search`` functions sort ahead of the pipeline's ``retrieve`` (same score, earlier path).
    decoys = {f"a{index:02d}/search.py": "def search(query):\n    return [query]\n" for index in range(12)}
    root = _project(tmp_path, {
        **decoys,
        "zz/pipeline.py": (
            "def bm25(query):\n    return []\n\n"
            "def rerank(query, candidates):\n    return candidates\n\n"
            "def retrieve(query):\n    return rerank(query, bm25(query))\n"
        ),
    })
    plan = build_integration_plan(root)

    assert plan.discovery["entrypoint"] == {"file": "zz/pipeline.py", "symbol": "retrieve", "kind": "function"}
    assert {op.symbol for op in plan.operators} == {"bm25", "rerank", "retrieve"}


# -- plan summary ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("files", "line"),
    [
        (
            {"data/queries.jsonl": QUERIES, "data/qrels.jsonl": QRELS, "data/corpus.jsonl": CORPUS},
            "Judgment files (resolved): queries data/queries.jsonl, qrels data/qrels.jsonl, corpus data/corpus.jsonl",
        ),
        (
            {"data/queries.jsonl": QUERIES, "data/qrels.jsonl": '{"query_id": "other", "relevant_doc_ids": ["d1"]}\n', "data/corpus.jsonl": CORPUS},
            "Judgment files (candidate: checks failed, see judgments.notes): queries data/queries.jsonl, qrels data/qrels.jsonl, corpus data/corpus.jsonl",
        ),
        ({"data/queries.jsonl": QUERIES}, "Judgment files (unresolved: see judgments.notes): queries data/queries.jsonl"),
        ({}, "Judgment files: none found"),
    ],
)
def test_plan_summary_states_the_judgments_status(tmp_path: Path, files: dict[str, str], line: str) -> None:
    from typer.testing import CliRunner

    from retrieval_observatory.cli import app

    root = _project(tmp_path / "project", {"app.py": APP, **files})
    plan_path = tmp_path / "plan.json"
    result = CliRunner().invoke(app, ["integrate", str(root), "--phase", "plan", "--output", str(plan_path)])

    assert result.exit_code == 0, result.output
    assert line in result.stdout.splitlines(), result.stdout
