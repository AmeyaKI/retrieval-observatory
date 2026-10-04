"""`retobs integrate --phase plan --watch` proposes exactly the steps that ran, linked by data flow."""
from __future__ import annotations

import ast
import json
import re
import shlex
import shutil
import sys
from pathlib import Path

from typer.testing import CliRunner

from retrieval_observatory.cli import app
from retrieval_observatory.integrations.model import IntegrationPlan
from retrieval_observatory.integrations.planner import SCENARIO_QUERY_TEXT
from retrieval_observatory.integrations.watch_map import WatchedStep
from retrieval_observatory.integrations.watch_plan import _capture_question, _recreate

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
    left_out = {(item["relative_path"], item["symbol"]): item for item in payload["discovery"]["low_confidence_operators"]}
    assert left_out[("services/search/retrieval_app/pipeline.py", "retrieve")]["reason"] == "not_seen_in_watch"
    # Both lanes' filter_candidates ran, folded into their lane: they are not "never seen".
    for lane in ("keyword", "vector"):
        folded = left_out[(f"services/search/retrieval_app/lanes/{lane}.py", "filter_candidates")]
        assert (folded["reason"], folded["step"]) == ("folded_into_step", f"{lane}_search")
    assert not payload["unresolved"]
    # fuse_results(keyword_hits, vector_hits): parameters not named after its parents get an exact inputs mapping.
    assert sum(
        '`fuse_results_capture = CaptureSpec(inputs=lambda bound: {"keyword_search": bound.arguments["keyword_hits"], '
        '"vector_search": bound.arguments["vector_hits"]})`' in question
        for question in payload["open_questions"]
    ) == 1


def snippet(questions: list[str], name: str) -> str:
    """The ready ``retobs_adapter.py`` line an open question gives for ``name``."""
    found = [match for question in questions for match in re.findall(r"`([^`]+)`", question) if match.startswith(f"{name} = ")]
    assert len(found) == 1, questions
    return found[0]


LANES_IN_A_TUPLE = '''\
def lexical(words):
    return [{"id": "a"}, {"id": "b"}, {"id": "c"}]


def dense(words):
    return [{"id": "b"}, {"id": "d"}]


def merge(lanes):
    seen = {}
    for lane in lanes:
        for hit in lane:
            seen.setdefault(hit["id"], hit)
    return [hit for hit in seen.values() if hit["id"] != "c"], [hit for hit in seen.values() if hit["id"] == "c"]


def order(hits):
    return list(reversed(hits))


def retrieve(words):
    kept, _dropped = merge((lexical(words), dense(words)))
    return order(kept)
'''


def lanes_in_a_tuple(tmp_path: Path) -> Path:
    root = tmp_path / "lanes_in_a_tuple"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "pipeline.py").write_text(LANES_IN_A_TUPLE)
    (root / "pyproject.toml").write_text('[project]\nname = "lanes-in-a-tuple-fixture"\nversion = "0.1.0"\n')
    return root


def test_lanes_handed_over_in_one_tuple_and_a_bundle_return_get_one_capture_spec(tmp_path: Path) -> None:
    payload = plan(lanes_in_a_tuple(tmp_path), call("widget pricing"))
    ops = operators(payload)
    assert ops["merge"]["parent_ids"] == ["lexical", "dense"] and ops["order"]["parent_ids"] == ["merge"]
    line = snippet(payload["open_questions"], "merge_capture")
    assert line == (
        'merge_capture = CaptureSpec(inputs=lambda bound: {"lexical": bound.arguments["lanes"][0], '
        '"dense": bound.arguments["lanes"][1]}, outputs=lambda result: result[0])'
    )
    ast.parse(line)
    # The entrypoint's parameter is not query-named, so the watch kept no question text.
    assert {scenario["query_text"] for scenario in payload["scenarios"]} == {SCENARIO_QUERY_TEXT}
    assert sum("query_text" in question and SCENARIO_QUERY_TEXT in question for question in payload["open_questions"]) == 1


def test_capture_specs_read_named_and_attribute_slots() -> None:
    step = WatchedStep(
        op_id="merge", symbol="merge", relative_path="app/pipeline.py", op_type="FUSE", parent_ids=("lexical", "dense"),
        inputs_from=(("lanes[key:lexical]", "lexical"), ("lanes[attr:documents]", "dense")), output_bundle="key:kept",
    )
    line = snippet([_capture_question(step)], "merge_capture")
    assert line == (
        'merge_capture = CaptureSpec(inputs=lambda bound: {"lexical": bound.arguments["lanes"]["lexical"], '
        '"dense": bound.arguments["lanes"].documents}, outputs=lambda result: result["kept"])'
    )
    ast.parse(line)


def test_bundle_step_gets_a_capture_question(tmp_path: Path) -> None:
    payload = plan(copy(tmp_path, "bundle"), call("q"))
    ops = operators(payload)
    assert ops["screen"]["op_type"] == "FILTER"
    assert ops["order_by_length"]["parent_ids"] == ["screen"]
    assert any("screen" in question and "index:0" in question and "retobs_adapter.py" in question for question in payload["open_questions"])
    # Until that CaptureSpec is in place the bundle is read as the documents: say so, inside plan_id.
    assert payload["expected_capabilities"]["actual_input_output_capture"] == "partial"
    assert _recreate(IntegrationPlan.from_dict(payload)).plan_id == payload["plan_id"]
    assert not any(SCENARIO_QUERY_TEXT in question for question in payload["open_questions"])


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


def test_an_async_entrypoint_gets_a_benchmark_command(tmp_path: Path) -> None:
    root = copy(tmp_path, "async_lanes")
    shutil.copytree(EXTERNAL / "messy_monorepo" / "data", root / "data")
    payload = plan(root, call("q", asynchronous=True))
    setup = next(action for action in payload["actions"] if action["kind"] == "benchmark_setup")
    assert setup["command"] and setup["command"].startswith("retobs evaluate app.pipeline:retrieve --queries data/queries.jsonl")


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
    assert replan(tmp_path / "bundle")["discovery"]["watch_fallback_reason"] == payload["discovery"]["watch_fallback_reason"]


def replan(root: Path) -> dict:
    plan_file = root / "retobs" / "integration-plan.json"
    result = CliRunner().invoke(app, ["integrate", str(root), "--phase", "plan", "--plan", str(plan_file), "--output", str(plan_file)])
    assert result.exit_code == 0, result.output
    return json.loads(plan_file.read_text())["plan"]


def test_a_plan_without_a_watch_says_it_guessed(tmp_path: Path) -> None:
    assert plan(copy(tmp_path, "bundle"))["discovery"]["method"] == "guessed"


def test_re_planning_keeps_what_the_watch_saw(tmp_path: Path) -> None:
    root = copy(tmp_path, "messy_monorepo")
    first = plan(root, f"cd services/search && {PY} -m retrieval_app.pipeline widget pricing d-setup")
    again = replan(root)
    assert again["discovery"]["method"] == "watched"
    assert again["discovery"]["watch"] == first["discovery"]["watch"]
    from_watch = [item for item in first["discovery"]["low_confidence_operators"]
                  if item.get("reason") in ("not_seen_in_watch", "folded_into_step")]
    assert len(from_watch) == 3
    assert [item for item in again["discovery"]["low_confidence_operators"] if item in from_watch] == from_watch
