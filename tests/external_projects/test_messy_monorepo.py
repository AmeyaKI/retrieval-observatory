"""The unreviewed plan for a messy repository proposes the reachable pipeline, not its distractors.

``messy_monorepo`` has a hybrid pipeline (two lanes -> fuse -> filter -> rerank) reachable from
``retrieval_app/pipeline.py:retrieve`` next to a checked-in virtualenv and a ``pyvenv.cfg``
environment, ``scripts/`` utilities named ``search*``, an unrelated ``analytics/`` module with
``filter_*``/``rank_*`` functions, a tests dir, an exported notebook, and a label CSV that is not
a qrels file.
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
PIPELINE = {
    ("retrieval_app/lanes/keyword.py", "keyword_search"),
    ("retrieval_app/lanes/vector.py", "vector_search"),
    ("retrieval_app/fusion.py", "fuse_results"),
    ("retrieval_app/filters.py", "anchor_filter"),
    ("retrieval_app/rerank.py", "rerank_candidates"),
}
ENTRYPOINT = {"file": "retrieval_app/pipeline.py", "symbol": "retrieve", "kind": "function"}
ENVIRONMENT_DIRS = (".venv-local", "env/", "site-packages")


def _copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "messy_monorepo", ignore=shutil.ignore_patterns("__pycache__")))


def test_unreviewed_plan_proposes_exactly_the_reachable_pipeline(tmp_path: Path) -> None:
    plan = build_integration_plan(_copy(tmp_path))

    proposed = {(op.relative_path, op.symbol) for op in plan.operators}
    assert plan.discovery["entrypoint"] == ENTRYPOINT
    assert PIPELINE <= proposed
    # The entrypoint itself matches the SOURCE name rule; it is the only operator beyond the pipeline.
    assert proposed - PIPELINE <= {("retrieval_app/pipeline.py", "retrieve")}
    unreachable = {
        (item["relative_path"], item["symbol"])
        for item in plan.discovery["low_confidence_operators"]
        if item.get("reason") == "unreachable_from_entrypoint"
    }
    assert {
        ("scripts/search_logs.py", "search"),
        ("scripts/search_tickets.py", "search_tickets"),
        ("analytics/reports.py", "filter_bots"),
        ("analytics/reports.py", "rerank_pages"),
        ("notebooks/explore_retrieval.py", "search_examples"),
    } <= unreachable
    assert not plan.unresolved


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

    assert (plan.judgments["queries"], plan.judgments["qrels"], plan.judgments["corpus"]) == (
        "data/queries.jsonl", "data/qrels.jsonl", "data/corpus.jsonl",
    )
    commands = [scenario.command for scenario in plan.scenarios]
    assert commands and all(command and "from retrieval_app.pipeline import retrieve" in command for command in commands)
    argv = shlex.split(commands[0])
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    completed = subprocess.run([sys.executable, *argv[1:]], cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr
