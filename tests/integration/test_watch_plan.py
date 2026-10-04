"""`retobs integrate --phase plan --watch` proposes exactly the steps that ran, linked by data flow."""
from __future__ import annotations

import json
import shlex
import shutil
import sys
from pathlib import Path

from typer.testing import CliRunner

from retrieval_observatory.cli import app

EXTERNAL = Path(__file__).resolve().parents[1] / "external_projects"
PY = shlex.quote(sys.executable)


def copy(tmp_path: Path, name: str) -> Path:
    source = EXTERNAL / "watch_fixtures" / name if (EXTERNAL / "watch_fixtures" / name).is_dir() else EXTERNAL / name
    return Path(shutil.copytree(source, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__")))


def call(query: str, entry: str = "retrieve", *, asynchronous: bool = False) -> str:
    body = f"import asyncio; from app.pipeline import {entry}; asyncio.run({entry}({query!r}))" if asynchronous else (
        f"from app.pipeline import {entry}; {entry}({query!r})"
    )
    return f"{PY} -c {shlex.quote(body)}"


def plan(root: Path, *commands: str) -> dict:
    args = ["integrate", str(root), "--phase", "plan", "--output", str(root / "retobs" / "integration-plan.json")]
    for command in commands:
        args += ["--watch", command]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    return json.loads((root / "retobs" / "integration-plan.json").read_text())["plan"]


def operators(plan_payload: dict) -> dict[str, dict]:
    return {op["symbol"]: op for op in plan_payload["operators"]}


def test_messy_monorepo_plan_is_exactly_the_pipeline_that_ran(tmp_path: Path) -> None:
    root = copy(tmp_path, "messy_monorepo")
    command = f"cd services/search && {PY} -m retrieval_app.pipeline widget pricing d-setup"
    payload = plan(root, command)
    ops = operators(payload)
    assert payload["discovery"]["method"] == "watched"
    assert payload["discovery"]["entrypoint"] == {"file": "services/search/retrieval_app/pipeline.py", "symbol": "retrieve", "kind": "function"}
    assert {symbol: op["op_type"] for symbol, op in ops.items()} == {
        "keyword_search": "SOURCE", "vector_search": "SOURCE", "fuse_results": "FUSE",
        "anchor_filter": "FILTER", "rerank_candidates": "RERANK",
    }
    assert ops["fuse_results"]["parent_ids"] == ["keyword_search", "vector_search"]
    assert ops["anchor_filter"]["parent_ids"] == ["fuse_results"]
    assert ops["rerank_candidates"]["parent_ids"] == ["anchor_filter"]
    # RERANK because the watched search reordered the documents, not because of the name.
    assert "taken from" not in ops["rerank_candidates"]["notes"]
    watched_steps = {step["symbol"]: step for step in payload["discovery"]["watch"]["steps"]}
    assert watched_steps["vector_search"]["inside"] == ["filter_candidates took 3 returned 2"]
    assert all(scenario["command"] == command for scenario in payload["scenarios"])
    reasons = {(item["relative_path"], item["symbol"]): item.get("reason") for item in payload["discovery"]["low_confidence_operators"]}
    assert reasons[("services/search/retrieval_app/pipeline.py", "retrieve")] == "not_seen_in_watch"
    assert not payload["unresolved"]


def test_bundle_step_gets_a_capture_question(tmp_path: Path) -> None:
    payload = plan(copy(tmp_path, "bundle"), call("q"))
    ops = operators(payload)
    assert ops["screen"]["op_type"] == "FILTER"
    assert ops["order_by_length"]["parent_ids"] == ["screen"]
    assert any("screen" in question and "index:0" in question and "retobs_adapter.py" in question for question in payload["open_questions"])


def test_thread_pool_lanes_belong_to_the_search(tmp_path: Path) -> None:
    ops = operators(plan(copy(tmp_path, "threads"), call("q")))
    assert ops["merge_lanes"]["parent_ids"] == ["lane_terms", "lane_vectors"]


def test_async_lanes(tmp_path: Path) -> None:
    payload = plan(copy(tmp_path, "async_lanes"), call("q", asynchronous=True))
    ops = operators(payload)
    assert ops["lane_terms"]["invocation"] == "async"
    assert ops["merge_lanes"]["parent_ids"] == ["lane_terms", "lane_vectors"]
    assert ops["rescore"]["op_type"] == "RERANK" and ops["rescore"]["parent_ids"] == ["merge_lanes"]
    assert payload["discovery"]["entrypoint"]["kind"] == "async_function"


def test_two_paths_give_conditional_steps_routes_and_a_gate(tmp_path: Path) -> None:
    payload = plan(copy(tmp_path, "routes"), call("id:42"), call("widget pricing"))
    ops = operators(payload)
    assert ops["pick_route"]["op_type"] == "GATE"
    assert {scenario["route"] for scenario in payload["scenarios"] if scenario["route"]} == {"keyword", "hybrid"}
    assert set(payload["discovery"]["watch"]["conditional"]) == {"lane_vectors", "merge_lanes"}


def test_passages_to_documents_is_a_transform(tmp_path: Path) -> None:
    ops = operators(plan(copy(tmp_path, "passages"), call("q")))
    assert ops["to_documents"]["op_type"] == "TRANSFORM" and ops["to_documents"]["parent_ids"] == ["find_passages"]


def test_an_inline_cut_is_noted_not_invented(tmp_path: Path) -> None:
    payload = plan(copy(tmp_path, "inline_cut"), call("q"))
    assert set(operators(payload)) == {"lexical", "order_by_id"}
    assert any("retrieve changed the documents itself after order_by_id (3 → 2)" in note for note in payload["discovery"]["watch"]["notes"])


def test_a_failed_watch_falls_back_to_guessing_and_says_why(tmp_path: Path) -> None:
    payload = plan(copy(tmp_path, "bundle"), f"{PY} -c \"raise SystemExit(3)\"")
    assert payload["discovery"]["method"] == "guessed"
    assert any("exit code 3" in question for question in payload["open_questions"])
