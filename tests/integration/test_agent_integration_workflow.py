"""The agent-assisted onboarding workflow end to end, on the class-based multi-module hybrid fixture:
static plan -> reviewed re-plan -> apply -> declared scenarios -> verify (all eight capabilities) ->
labeled evaluation -> Connect record -> revert. Every subprocess runs from a pristine tmp copy."""
from __future__ import annotations

import importlib.resources
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.integrations.model import CAPABILITY_NAMES
from retrieval_observatory.integrations.planner import INSTRUMENTATION_MARKER
from retrieval_observatory.integrations.record import get_integration_record, integration_id
from retrieval_observatory.integrations.registry import describe_integration
from retrieval_observatory.mcp.server import _integrate_project
from retrieval_observatory.store.sqlite import SQLiteStore

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "external_projects"))
from plan_review import apply_plan_overrides  # noqa: E402

FIXTURE = REPO / "tests" / "external_projects" / "hybrid_multi_module"
STATIC_OPERATOR_IDS = {"retrieve", "intentrouter_route", "lexicallane_search", "denselane_search", "rrf_fusion", "reranker_rerank"}
REVIEWED_OPERATOR_IDS = {"intent_router", "lexical", "dense", "rrf_fusion", "rerank"}
OBSERVED_FILES = ("app/gate.py", "app/lanes.py", "app/fusion.py", "app/rerank.py")
ENTRYPOINT_FILE = "app/pipeline.py"
FINAL_ONLY_APP = (
    "def _call_endpoint(payload):\n"
    "    # Stands in for the HTTP round trip to a remote search service.\n"
    '    return {"hits": [{"id": "d1", "score": 0.9}, {"id": "d2", "score": 0.4}]}\n\n\n'
    "def search(query: str) -> list[dict]:\n"
    '    return _call_endpoint({"query": query})["hits"]\n'
)


def _run(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    return subprocess.run([sys.executable, *argv], cwd=root, env=env, capture_output=True, text=True, timeout=180)


def _oracle(root: Path) -> list:
    result = _run(root, "-m", "app.pipeline")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


async def _plan(root: Path, **kwargs) -> dict:
    planned = await _integrate_project(project_root=str(root), phase="plan", **kwargs)
    assert planned["status"] == "planned"
    return planned


async def test_reviewed_plan_apply_scenarios_verify_and_evaluate(tmp_path: Path) -> None:
    pristine, root = tmp_path / "pristine", tmp_path / "project"
    shutil.copytree(FIXTURE, pristine)
    shutil.copytree(FIXTURE, root)
    expected = json.loads((root / "expected.json").read_text(encoding="utf-8"))

    # 1. The static plan is a proposal: name-matched operators, no cross-module parents, honest questions.
    planned = await _plan(root)
    plan = planned["plan"]
    assert {op["op_id"] for op in plan["operators"]} == STATIC_OPERATOR_IDS
    assert all(op["parent_ids"] == [] for op in plan["operators"])
    assert plan["discovery"]["entrypoint"] == {"file": ENTRYPOINT_FILE, "symbol": "retrieve", "kind": "function"}
    assert any("rrf_fusion" in question and "actual inputs cannot be read statically" in question for question in plan["open_questions"])
    assert any("intentrouter_route" in question and "one scenario per route" in question for question in plan["open_questions"])
    assert all(scenario["command"] for scenario in plan["scenarios"])

    # 2. Review, then re-plan from the reviewed file: patches are regenerated from the reviewed operators.
    plan_path = root / "retobs" / "integration-plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(apply_plan_overrides(planned, expected["plan_overrides"]), indent=2), encoding="utf-8")
    replanned = await _plan(root, plan_path=str(plan_path))
    plan = replanned["plan"]
    plan_path.write_text(json.dumps(replanned, indent=2), encoding="utf-8")
    assert {op["op_id"] for op in plan["operators"]} == REVIEWED_OPERATOR_IDS
    edges = {(parent, op["op_id"]) for op in plan["operators"] for parent in op["parent_ids"]}
    assert edges == {tuple(edge) for edge in expected["required_edges"]}
    assert next(op for op in plan["operators"] if op["op_id"] == "rrf_fusion")["input_mapping"] == "capture"
    assert plan["unresolved"] == []
    assert [scenario["scenario_id"] for scenario in plan["scenarios"]] == expected["scenario_ids"]
    assert all(scenario["command"] for scenario in plan["scenarios"])
    # The planner expects `partial` route coverage for any GATE before the routes are measured; verify
    # below reports the measured value for the declared per-route scenarios.
    assert {name for name, status in plan["expected_capabilities"].items() if status != "ready"} <= {"declared_route_coverage"}

    # 3. Apply edits only the listed files and leaves the pipeline's behavior unchanged.
    before = _oracle(pristine)
    applied = await _integrate_project(project_root=str(root), phase="apply", plan_path=str(plan_path))
    assert applied["status"] == "applied"
    for relative in OBSERVED_FILES:
        source = (root / relative).read_text(encoding="utf-8")
        assert INSTRUMENTATION_MARKER in source and "@observe(" in source, relative
    entry_source = (root / ENTRYPOINT_FILE).read_text(encoding="utf-8")
    assert INSTRUMENTATION_MARKER in entry_source and "@trace_scope(" in entry_source and "@observe(" not in entry_source
    assert _oracle(root) == before
    assert [[document["id"] for document in item["documents"]] for item in before] == [
        expected["expected_final_doc_ids"][scenario] for scenario in expected["scenario_ids"]
    ]

    # 4. Run every declared scenario command; each call persists one trace.
    for scenario in plan["scenarios"]:
        argv = shlex.split(scenario["command"])
        assert argv[0] == "python"
        exercised = _run(root, *argv[1:])
        assert exercised.returncode == 0, exercised.stderr
        assert "could not persist trace" not in exercised.stderr

    # 5. Verify measures all eight capabilities, including the lexical-only route.
    verified = await _integrate_project(project_root=str(root), phase="verify", plan_path=str(plan_path))
    not_ready = {name: value["failures"] for name, value in verified["capabilities"].items() if value["status"] != "ready"}
    assert verified["status"] == "ready", not_ready
    assert set(verified["capabilities"]) == set(CAPABILITY_NAMES) and not not_ready
    assert set(verified["observed_operator_ids"]) == REVIEWED_OPERATOR_IDS
    assert set(verified["capabilities"]["declared_route_coverage"]["evidence"]["observed_routes"]) == {"hybrid", "lexical_only"}

    # 6. The plan's benchmark action evaluates the instrumented entrypoint against the discovered labels.
    setup = next(action for action in plan["actions"] if action["kind"] == "benchmark_setup")
    argv = shlex.split(setup["command"])
    assert argv[:2] == ["retobs", "evaluate"] and "--name hybrid-multi-module-v1" in setup["command"]
    evaluated = _run(root, "-m", "retrieval_observatory.cli", *argv[1:], "--format", "json")
    assert evaluated.returncode == 0, evaluated.stderr[-2000:]
    report = json.loads(evaluated.stdout)
    assert report["evidence_health"] == "ready"
    assert {key.split("|")[2] for key in report["metrics"]} >= {"recall@10", "ndcg@10"}

    # 7. Connect reads the persisted record and links it to the evaluation run.
    registry = DbRegistry([str(root / ".retobs" / "results.db")])
    client = TestClient(create_app(registry=registry))
    response = client.get(f"/dbs/{registry.default_db_id}/integrations/{integration_id(plan['service_id'], plan['pipeline_id'])}")
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["status"] == "ready" and record["depth"] == "internal"
    assert record["investigation"]["run_id"]

    # 8. Revert restores exactly the patched files.
    reverted = await _integrate_project(project_root=str(root), phase="revert")
    assert reverted["status"] == "reverted"
    for relative in (*OBSERVED_FILES, ENTRYPOINT_FILE):
        assert (root / relative).read_bytes() == (pristine / relative).read_bytes(), relative
    assert not (root / "retobs" / "integration.yaml").exists()


async def test_final_only_integration_is_classified_final_only(tmp_path: Path) -> None:
    root = tmp_path / "remote_search"
    root.mkdir()
    (root / "app.py").write_text(FINAL_ONLY_APP, encoding="utf-8")

    planned = await _plan(root)
    plan = planned["plan"]
    assert [(op["op_id"], op["op_type"], op["parent_ids"]) for op in plan["operators"]] == [("search", "SOURCE", [])]
    assert plan["discovery"]["entrypoint"] == {"file": "app.py", "symbol": "search", "kind": "function"}
    assert plan["expected_capabilities"]["judgment_mapping"] == "unavailable"
    plan_path = root / "retobs" / "integration-plan.json"
    plan_path.parent.mkdir()
    plan_path.write_text(json.dumps(planned), encoding="utf-8")
    applied = await _integrate_project(project_root=str(root), phase="apply", plan_path=str(plan_path))
    assert applied["status"] == "applied"
    for _ in range(2):
        exercised = _run(root, "-c", "from app import search; search('remote question')")
        assert exercised.returncode == 0, exercised.stderr

    verified = await _integrate_project(project_root=str(root), phase="verify")
    assert verified["capabilities"]["actual_input_output_capture"]["status"] == "ready"
    assert verified["capabilities"]["final_output_capture"]["status"] == "ready"
    assert verified["capabilities"]["judgment_mapping"]["status"] == "unavailable"
    assert verified["status"] == "partial"
    store = SQLiteStore(str(root / ".retobs" / "results.db"))
    await store.init_db()
    record = await get_integration_record(store, integration_id(plan["service_id"], plan["pipeline_id"]))
    assert record is not None and record["depth"] == "final_only"
    assert all(operator["parent_ids"] == [] for operator in record["operators"])
    assert not any("parent" in question or "lineage" in question for question in record["open_questions"])


async def test_runbook_is_packaged_and_discoverable(tmp_path: Path) -> None:
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    plan = (await _plan(root))["plan"]

    runbook = Path(plan["discovery"]["runbook"])
    assert runbook.name == "SKILL.md" and runbook.is_file()
    packaged = importlib.resources.files("retrieval_observatory") / "examples" / "agent_integration" / "SKILL.md"
    assert packaged.is_file()
    lines = packaged.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---"
    frontmatter = lines[1 : lines.index("---", 1)]
    assert any(line.startswith("name:") for line in frontmatter)
    assert any(line.startswith("description:") for line in frontmatter)
    assert describe_integration()["runbook_path"] == str(runbook)
    assert describe_integration("python")["runbook_path"] == str(runbook)
