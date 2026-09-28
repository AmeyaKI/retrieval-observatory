"""The unreviewed plan for a messy repository proposes the reachable pipeline, not its distractors.

``messy_monorepo`` has a hybrid pipeline (two lanes -> fuse -> filter -> rerank) reachable from
``services/search/retrieval_app/pipeline.py:retrieve``; ``retrieval_app`` is importable only with
``services/search`` on the path (no ``__init__.py`` above it). Around it: a checked-in virtualenv
and a ``pyvenv.cfg`` environment, ``scripts/`` utilities named ``search*``, an unrelated
``analytics/`` module with ``filter_*``/``rank_*`` functions, a comparison system's own
``search``, report aggregators, an eval runner's gates, a bench runner that imports the pipeline,
an exported notebook, predicates/factories/formatters on the pipeline's own import path, the same
``filter_candidates`` name in both lanes, a label CSV that is not a qrels file, and a bench
queries file plus fixture labels and an empty corpus that must not be taken for the real judgments.
"""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from retrieval_observatory.integrations.detect import detect_project
from retrieval_observatory.integrations.planner import build_integration_plan

FIXTURE = Path(__file__).parent / "messy_monorepo"
APP = "services/search/retrieval_app"
PIPELINE = {
    (f"{APP}/lanes/keyword.py", "keyword_search"),
    (f"{APP}/lanes/keyword.py", "filter_candidates"),
    (f"{APP}/lanes/vector.py", "vector_search"),
    (f"{APP}/lanes/vector.py", "filter_candidates"),
    (f"{APP}/fusion.py", "fuse_results"),
    (f"{APP}/filters.py", "anchor_filter"),
    (f"{APP}/rerank.py", "rerank_candidates"),
}
ENTRYPOINT = {"file": f"{APP}/pipeline.py", "symbol": "retrieve", "kind": "function"}
ENVIRONMENT_DIRS = (".venv-local", "env/", "site-packages")


def _copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "messy_monorepo", ignore=shutil.ignore_patterns("__pycache__")))


def test_unreviewed_plan_proposes_exactly_the_reachable_pipeline(tmp_path: Path) -> None:
    plan = build_integration_plan(_copy(tmp_path))

    proposed = {(op.relative_path, op.symbol) for op in plan.operators}
    assert plan.discovery["entrypoint"] == ENTRYPOINT
    # The entrypoint itself matches the SOURCE name rule; it is the only operator beyond the pipeline.
    assert proposed == PIPELINE | {(f"{APP}/pipeline.py", "retrieve")}
    reasons: dict[str, set[tuple[str, str]]] = {}
    for item in plan.discovery["low_confidence_operators"]:
        reasons.setdefault(str(item.get("reason")), set()).add((item["relative_path"], item["symbol"]))
    assert {
        ("analytics/reports.py", "filter_bots"),
        ("analytics/reports.py", "rerank_pages"),
        ("baselines/other_engine/search.py", "search"),
    } <= reasons["unreachable_from_entrypoint"]
    assert {
        ("scripts/search_logs.py", "search"),
        ("scripts/search_tickets.py", "search_tickets"),
        ("notebooks/explore_retrieval.py", "search_examples"),
        ("reports/summary.py", "filter_rows_by_system"),
        ("eval_runner/gates.py", "evaluate_gates"),
        ("bench_runner/run_bench.py", "search"),
        ("bench_runner/run_bench.py", "search_all"),
    } <= reasons["non_runtime_dir"]
    assert {
        (f"{APP}/intents.py", "has_task_intent"),
        (f"{APP}/intents.py", "range_intent"),
        (f"{APP}/intents.py", "format_gate_value"),
        (f"{APP}/models.py", "get_cross_encoder"),
    } <= reasons["not_operator_shape"]
    # An aggregator is not a GATE: "gate" inside "aggregate" is not a name token.
    everywhere = proposed | {pair for found in reasons.values() for pair in found}
    assert ("reports/summary.py", "aggregate_by_system_and_category") not in everywhere
    assert not plan.unresolved


def test_same_named_operators_in_two_modules_get_distinct_ids(tmp_path: Path) -> None:
    plan = build_integration_plan(_copy(tmp_path))

    ops = {(op.relative_path, op.symbol): op for op in plan.operators}
    keyword_filter = ops[(f"{APP}/lanes/keyword.py", "filter_candidates")]
    vector_filter = ops[(f"{APP}/lanes/vector.py", "filter_candidates")]
    assert (keyword_filter.op_id, vector_filter.op_id) == (
        "retrieval_app_lanes_keyword__filter_candidates", "retrieval_app_lanes_vector__filter_candidates",
    )
    assert len({op.op_id for op in plan.operators}) == len(plan.operators)
    assert ops[(f"{APP}/lanes/keyword.py", "keyword_search")].parent_ids == (keyword_filter.op_id,)
    assert ops[(f"{APP}/lanes/vector.py", "vector_search")].parent_ids == (vector_filter.op_id,)
    keyword_patch = next(patch for patch in plan.patches if patch.relative_path == f"{APP}/lanes/keyword.py")
    assert f'op_id="{keyword_filter.op_id}"' in keyword_patch.replacement
    plan.validate_for_apply()


def test_unreviewed_plan_never_touches_environments_or_tests(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    plan = build_integration_plan(root)

    paths = [
        *(candidate.file for candidate in detect_project(root).entrypoints),
        *(item["relative_path"] for item in plan.discovery["low_confidence_operators"]),
        *(op.relative_path for op in plan.operators),
        *plan.discovery["datasets"],
        *(patch.relative_path for patch in plan.patches),
    ]
    assert paths
    assert not [path for path in paths if any(part in path for part in ENVIRONMENT_DIRS) or path.startswith("tests/")]


def test_unreviewed_plan_picks_the_real_qrels_and_runnable_commands(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    plan = build_integration_plan(root)

    assert (plan.judgments["queries"], plan.judgments["qrels"], plan.judgments["corpus"], plan.judgments["status"]) == (
        "data/queries.jsonl", "data/qrels.jsonl", "data/corpus.jsonl", "resolved",
    )
    assert [scenario.query_text for scenario in plan.scenarios] == ["widget pricing", "widget pricing"]
    commands = [scenario.command for scenario in plan.scenarios]
    assert commands and all(
        command
        and "sys.path.insert(0, 'services/search')" in command
        and "from retrieval_app.pipeline import retrieve" in command
        and "retrieve('widget pricing')" in command
        for command in commands
    )
    argv = shlex.split(commands[0])
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    completed = subprocess.run([sys.executable, *argv[1:]], cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr


def test_trap_fixture_files_are_not_gitignored() -> None:
    """The virtualenv and dataset traps must be committed: an ignored fixture file would silently vanish from CI."""
    if shutil.which("git") is None:
        return
    files = [
        FIXTURE / ".venv-local" / "pyvenv.cfg",
        FIXTURE / "env" / "lib" / "python3.12" / "site-packages" / "helper_lib" / "search.py",
        *(FIXTURE / name for name in ("bench_suite/queries.json", "fixtures/labels.json", "fixtures/corpus.json")),
    ]
    ignored = subprocess.run(["git", "check-ignore", *map(str, files)], cwd=FIXTURE, capture_output=True, text=True)
    assert ignored.stdout == ""
