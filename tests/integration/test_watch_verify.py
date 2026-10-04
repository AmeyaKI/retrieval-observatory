"""After apply, verify names the exact function behind any gap between the plan and the watched search."""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from retrieval_observatory.cli import app
from retrieval_observatory.integrations.model import IntegrationManifest, OperatorMapping
from retrieval_observatory.integrations.verify import verify_observed_traces

EXTERNAL = Path(__file__).resolve().parents[1] / "external_projects"
PY = shlex.quote(sys.executable)
COMMAND = f"cd services/search && {PY} -m retrieval_app.pipeline widget pricing d-setup"
WATCH_CODES = {"watched_step_unmarked", "declared_step_not_watched", "declared_link_differs_from_watch"}


def copy(tmp_path: Path, source: Path) -> Path:
    return Path(shutil.copytree(source, tmp_path / source.name, ignore=shutil.ignore_patterns("__pycache__")))


def invoke(*args: str):
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result


def verify(root: Path) -> dict:
    result = CliRunner().invoke(app, ["integrate", str(root), "--phase", "verify"])
    return json.loads(result.output)


def plan_apply_run(root: Path, edit=None) -> dict:
    plan_file = root / "retobs" / "integration-plan.json"
    invoke("integrate", str(root), "--phase", "plan", "--watch", COMMAND, "--output", str(plan_file))
    if edit is not None:
        payload = json.loads(plan_file.read_text())
        edit(payload["plan"])
        plan_file.write_text(json.dumps(payload))
        invoke("integrate", str(root), "--phase", "plan", "--plan", str(plan_file), "--output", str(plan_file))
    invoke("integrate", str(root), "--phase", "apply", "--plan", str(plan_file))
    subprocess.run(COMMAND, shell=True, cwd=root, check=True, capture_output=True)
    subprocess.run(COMMAND, shell=True, cwd=root, check=True, capture_output=True)
    return verify(root)


def topology_failures(result: dict) -> list[dict]:
    return result["capabilities"]["topology_observed"]["failures"]


def codes(result: dict) -> set[str]:
    return {item["code"] for item in topology_failures(result)}


def test_the_watched_plan_matches_what_runs(tmp_path: Path) -> None:
    result = plan_apply_run(copy(tmp_path, EXTERNAL / "messy_monorepo"))
    assert not codes(result) & WATCH_CODES


def test_a_dropped_step_is_named_with_the_function_that_did_it(tmp_path: Path) -> None:
    def drop_filter(plan: dict) -> None:
        plan["operators"] = [op for op in plan["operators"] if op["symbol"] != "anchor_filter"]
        for op in plan["operators"]:
            op["parent_ids"] = ["fuse_results" if parent == "anchor_filter" else parent for parent in op["parent_ids"]]

    result = plan_apply_run(copy(tmp_path, EXTERNAL / "messy_monorepo"), drop_filter)
    unmarked = [item for item in topology_failures(result) if item["code"] == "watched_step_unmarked"]
    assert len(unmarked) == 1
    assert "anchor_filter" in unmarked[0]["detail"] and "services/search/retrieval_app/filters.py" in unmarked[0]["detail"]
    links = [item for item in topology_failures(result) if item["code"] == "declared_link_differs_from_watch"]
    assert any("rerank_candidates" in item["detail"] and "anchor_filter (not in the plan)" in item["detail"] for item in links)
    assert result["capabilities"]["topology_observed"]["status"] == "partial"


def test_an_extra_step_the_watch_never_ran_is_named(tmp_path: Path) -> None:
    def add_unwatched(plan: dict) -> None:
        source = next(op for op in plan["operators"] if op["symbol"] == "anchor_filter")
        plan["operators"].append({**source, "op_id": "bench_search", "op_type": "SOURCE", "symbol": "search",
                                  "relative_path": "baselines/other_engine/search.py", "parent_ids": []})

    result = plan_apply_run(copy(tmp_path, EXTERNAL / "messy_monorepo"), add_unwatched)
    unwatched = [item for item in topology_failures(result) if item["code"] == "declared_step_not_watched"]
    assert [item["op_id"] for item in unwatched] == ["bench_search"]


def test_the_ready_capture_spec_from_the_plan_records_the_fusion_inputs_exactly(tmp_path: Path) -> None:
    root = copy(tmp_path, EXTERNAL / "messy_monorepo")

    def answer_the_capture_question(plan: dict) -> None:
        lines = [match for question in plan["open_questions"] for match in re.findall(r"`([^`]+)`", question)
                 if match.startswith("fuse_results_capture = ")]
        assert len(lines) == 1, plan["open_questions"]
        (root / "retobs_adapter.py").write_text(f"from retrieval_observatory.tracing.capture import CaptureSpec\n\n{lines[0]}\n")
        next(op for op in plan["operators"] if op["op_id"] == "fuse_results")["capture"] = "retobs_adapter:fuse_results_capture"

    result = plan_apply_run(root, answer_the_capture_question)
    capture = result["capabilities"]["actual_input_output_capture"]
    assert not [item for item in capture["failures"] if item["code"] == "inferred_inputs" and item["op_id"] == "fuse_results"]
    assert capture["evidence"]["by_operator"]["fuse_results"]["recorded"] == 2
    assert capture["status"] == "ready"
    assert not codes(result) & WATCH_CODES


def test_a_function_folded_into_a_watched_step_ran_but_only_in_its_own_file(tmp_path: Path) -> None:
    def docs(*ids: str) -> dict:
        return {"candidates": {"count": len(ids), "ids": list(ids), "container": "list", "item_type": "dict", "ids_are_strings": False}}

    def record(id: int, symbol: str, path: str, start: int, end: int, parent: int | None, inputs: list, output: dict) -> dict:
        return {"id": id, "parent": parent, "thread": "MainThread", "symbol": symbol, "path": path, "line": 1, "callable": "function",
                "start": start, "end": end, "inputs": inputs, "output": output, "error": None, "ms": 0.1, "scalar_children": []}

    calls = [
        record(3, "trim", "app/lane.py", 3, 4, 2, [{"param": "candidates", **docs("x", "y", "z")}], docs("x", "y")),
        record(2, "lane", "app/lane.py", 2, 5, 1, [{"param": "query", "text": "q"}], docs("x", "y")),
        record(1, "retrieve", "app/pipeline.py", 1, 6, None, [{"param": "query", "text": "q"}], docs("x", "y")),
    ]
    (tmp_path / "retobs").mkdir()
    (tmp_path / "retobs" / "watch.json").write_text(json.dumps({"schema_version": 1, "commands": [
        {"command": "c", "exit_code": 0, "failure": None, "processes": [{"calls": calls, "truncated": False, "notes": []}]},
    ]}))
    manifest = IntegrationManifest(1, "plan", "svc", "pipe", (
        OperatorMapping("lane", "SOURCE", "lane", "app/lane.py"),
        OperatorMapping("trim", "FILTER", "trim", "app/lane.py", ("lane",)),
        OperatorMapping("other_trim", "FILTER", "trim", "app/other.py", ("lane",)),
    ), {}, ())
    failures = verify_observed_traces(manifest, [], project_root=tmp_path).capabilities["topology_observed"]["failures"]
    assert [item["op_id"] for item in failures if item["code"] == "declared_step_not_watched"] == ["other_trim"]


def test_an_empty_or_unrelated_watch_file_reports_nothing(tmp_path: Path) -> None:
    root = copy(tmp_path, EXTERNAL / "messy_monorepo")
    plan_apply_run(root)
    watch_file = root / "retobs" / "watch.json"
    watch_file.write_text("")
    assert not codes(verify(root)) & WATCH_CODES
    other = copy(tmp_path, EXTERNAL / "watch_fixtures" / "bundle")
    command = f"{PY} -c {shlex.quote('from app.pipeline import retrieve; retrieve(' + repr('q') + ')')}"
    invoke("integrate", str(other), "--phase", "plan", "--watch", command, "--output", str(other / "retobs" / "plan.json"))
    shutil.copyfile(other / "retobs" / "watch.json", watch_file)
    assert json.loads(watch_file.read_text())["commands"][0]["processes"]
    assert not codes(verify(root)) & WATCH_CODES
