"""Plans state which evidence they capture; apply marks its edits; revert removes only those."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from retrieval_observatory.cli import app
from retrieval_observatory.integrations.apply import apply_integration_plan, revert_integration
from retrieval_observatory.integrations.model import (
    CAPABILITY_NAMES,
    CAPABILITY_STATUSES,
    IntegrationOptions,
    IntegrationPhase,
    IntegrationPlan,
    OperatorMapping,
)
from retrieval_observatory.integrations.planner import build_integration_plan
from retrieval_observatory.integrations.service import integrate_project
from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
from integration_projects import DATA_FILES  # noqa: E402

MARKER = "# retobs instrumentation: added by 'retobs integrate --phase apply'; remove with '--phase revert'"

PIPELINE = (
    "def bm25(query): return [{'id': 'a', 'score': 1.0}]\n"
    "def dense(query): return [{'id': 'b', 'score': 0.9}]\n"
    "def rrf(*lanes): return [item for lane in lanes for item in lane]\n"
    "def temporal_filter(candidates): return candidates\n"
    "async def rerank(query, candidates): return candidates\n"
    "async def retrieve(query):\n"
    "    fused = rrf(bm25(query), dense(query))\n"
    "    filtered = temporal_filter(fused)\n"
    "    return await rerank(query, filtered)\n"
)
TWO_STAGE = (
    "def bm25(query): return [{'id': 'a', 'score': 1.0}, {'id': 'b', 'score': 0.5}]\n"
    "def rerank(query, candidates): return list(reversed(candidates))\n"
    "def retrieve(query): return rerank(query, bm25(query))\n"
)
FASTAPI_ROUTE = (
    "from fastapi import FastAPI\n"
    "app = FastAPI()\n"
    "def bm25(query): return []\n"
    "@app.post('/search')\n"
    "def search(query: str): return bm25(query)\n"
)


def _project(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _operators(plan: IntegrationPlan) -> dict[str, OperatorMapping]:
    return {operator.op_id: operator for operator in plan.operators}


def _with_capture(plan: IntegrationPlan, op_id: str, capture: str) -> IntegrationPlan:
    return replace(
        plan,
        operators=tuple(replace(op, capture=capture) if op.op_id == op_id else op for op in plan.operators),
    )


def _load(root: Path, name: str, monkeypatch):
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.delitem(sys.modules, "retobs_adapter", raising=False)
    spec = importlib.util.spec_from_file_location(name, root / "app.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_plan_states_input_output_mappings_per_operator(tmp_path: Path) -> None:
    plan = build_integration_plan(_project(tmp_path, {"app.py": PIPELINE}))
    ops = _operators(plan)

    assert (ops["bm25"].input_mapping, ops["bm25"].output_mapping, ops["bm25"].invocation) == ("query:query", "return", "sync")
    assert ops["rrf"].parent_ids == ("bm25", "dense")
    assert ops["rrf"].input_mapping == "positional_lanes:lanes"
    assert ops["temporal_filter"].input_mapping == "parameter:candidates"
    assert ops["rerank"].input_mapping == "parameter:candidates"
    assert ops["rerank"].invocation == "async"


def test_plan_declares_final_boundary_and_identity(tmp_path: Path) -> None:
    plan = build_integration_plan(_project(tmp_path, {
        "app.py": "def bm25(query): return []\ndef retrieve(query_id, query): return bm25(query)\n",
    }))

    assert plan.boundary.kind == "entrypoint_return"
    assert (plan.boundary.symbol, plan.boundary.relative_path) == ("retrieve", "app.py")
    assert plan.identity.query_id == "argument:query_id"
    assert plan.identity.query_text_parameter == "query"
    assert plan.identity.candidate_id_field == "id"


def test_plan_maps_discovered_judgment_files(tmp_path: Path) -> None:
    root = _project(tmp_path, {"app.py": TWO_STAGE, **DATA_FILES})
    plan = build_integration_plan(root)

    assert plan.judgments["status"] == "resolved"
    assert plan.judgments["queries"] == "data/queries.jsonl"
    assert plan.judgments["qrels"] == "data/qrels.jsonl"
    assert plan.judgments["corpus"] == "data/corpus.jsonl"
    setup = next(action for action in plan.actions if action.kind == "benchmark_setup")
    assert setup.command is not None
    assert setup.command.startswith("retobs evaluate app.py:retrieve ")
    assert "--queries data/queries.jsonl" in setup.command
    assert "--qrels data/qrels.jsonl" in setup.command
    assert "--corpus data/corpus.jsonl" in setup.command
    assert plan.expected_capabilities["judgment_mapping"] == "ready"

    for name in ("data/qrels.jsonl", "data/qrels_rows.jsonl"):
        (root / name).unlink()
    without = build_integration_plan(root)

    assert without.judgments["status"] == "unresolved"
    assert without.judgments["qrels"] is None
    assert any("qrels" in note for note in without.judgments["notes"])
    assert without.expected_capabilities["judgment_mapping"] == "unavailable"
    assert next(action for action in without.actions if action.kind == "benchmark_setup").command is None


def test_plan_expected_capabilities_cover_every_name(tmp_path: Path) -> None:
    plan = build_integration_plan(_project(tmp_path, {"app.py": TWO_STAGE}))

    assert set(plan.expected_capabilities) == set(CAPABILITY_NAMES)
    assert all(status in CAPABILITY_STATUSES for status in plan.expected_capabilities.values())


def test_plan_actions_separate_install_edits_benchmark_and_scenarios(tmp_path: Path) -> None:
    plan = build_integration_plan(_project(tmp_path, {"app.py": TWO_STAGE, **DATA_FILES}))
    kinds = [action.kind for action in plan.actions]

    assert {"install", "source_edit", "benchmark_setup", "scenario_execution"} <= set(kinds)
    assert all((action.performed_by == "apply") == (action.kind == "source_edit") for action in plan.actions)
    assert next(action for action in plan.actions if action.kind == "install").command.startswith("pip install")
    assert kinds.count("source_edit") == len(plan.patches)
    assert kinds.count("scenario_execution") == len(plan.scenarios)
    assert [action.command for action in plan.actions if action.kind == "scenario_execution"] == [
        scenario.command for scenario in plan.scenarios
    ]


def test_gate_operator_yields_partial_route_coverage_and_a_question(tmp_path: Path) -> None:
    plan = build_integration_plan(_project(tmp_path, {
        "app.py": (
            "def intent_gate(query): return 'hybrid'\n"
            "def bm25(query, route): return []\n"
            "def retrieve(query):\n"
            "    route = intent_gate(query)\n"
            "    return bm25(query, route)\n"
        ),
    }))

    assert _operators(plan)["intent_gate"].op_type == "GATE"
    assert plan.expected_capabilities["declared_route_coverage"] == "partial"
    assert any("intent_gate" in question and "route" in question for question in plan.open_questions)


def test_scenarios_include_a_repeat_with_commands(tmp_path: Path) -> None:
    plan = build_integration_plan(_project(tmp_path / "plain", {"app.py": TWO_STAGE}))

    assert [scenario.scenario_id for scenario in plan.scenarios] == ["representative", "representative-repeat"]
    assert len({scenario.query_text for scenario in plan.scenarios}) == 1
    assert all(scenario.command is not None and scenario.command.startswith("python -c") for scenario in plan.scenarios)
    assert "from app import retrieve" in plan.scenarios[0].command

    routed = build_integration_plan(_project(tmp_path / "routed", {"app.py": FASTAPI_ROUTE}))

    assert routed.discovery["entrypoint"]["kind"] == "http_route"
    assert all(scenario.command is None for scenario in routed.scenarios)
    assert any("/search" in question for question in routed.open_questions)


def test_unmapped_operator_input_raises_an_open_question(tmp_path: Path) -> None:
    root = _project(tmp_path, {
        "app.py": "def bm25(query): return []\ndef rrf_fuse(): return bm25('fixed')\ndef retrieve(query): return rrf_fuse()\n",
    })
    plan = build_integration_plan(root)
    assert "rrf_fuse" not in _operators(plan)
    reviewed = replace(
        plan,
        operators=(*plan.operators, OperatorMapping("rrf_fuse", "FUSE", "rrf_fuse", "app.py", ("bm25",), 0.9)),
    )

    replanned = build_integration_plan(root, reviewed=reviewed)

    assert _operators(replanned)["rrf_fuse"].input_mapping == "unavailable"
    assert any("rrf_fuse" in question and "retobs_adapter" in question for question in replanned.open_questions)


def test_replan_with_capture_regenerates_patch_and_hook_runs(tmp_path: Path, monkeypatch) -> None:
    root = _project(tmp_path, {"app.py": TWO_STAGE})
    plan = build_integration_plan(root)
    assert _operators(plan)["rerank"].parent_ids == ("bm25",)
    (root / "retobs_adapter.py").write_text(
        "from retrieval_observatory.tracing.capture import CaptureSpec\n"
        'rerank_capture = CaptureSpec(inputs=lambda bound: {"bm25": bound.arguments["candidates"]})\n',
        encoding="utf-8",
    )

    replanned = build_integration_plan(root, reviewed=_with_capture(plan, "rerank", "retobs_adapter:rerank_capture"))

    assert replanned.plan_id != plan.plan_id
    assert _operators(replanned)["rerank"].capture == "retobs_adapter:rerank_capture"
    replacement = replanned.patches[0].replacement
    assert "capture=retobs_adapter.rerank_capture" in replacement
    assert "\nimport retobs_adapter\n" in replacement
    compile(replacement, "app.py", "exec")

    apply_integration_plan(replanned)
    module = _load(root, "t12_capture_app", monkeypatch)
    start_trace(ObserveContext(None, "q1", "query", replanned.pipeline_id, replanned.service_id))
    assert module.retrieve("query") == [{"id": "b", "score": 0.5}, {"id": "a", "score": 1.0}]
    trace = finish_trace()

    span = next(span for span in trace.spans if span.op_id == "rerank")
    assert span.input_capture == "recorded"
    assert set(span.input_groups) == {"bm25"}


def test_apply_refuses_missing_adapter_symbol(tmp_path: Path) -> None:
    root = _project(tmp_path, {"app.py": TWO_STAGE, "retobs_adapter.py": "unrelated = 1\n"})
    original = (root / "app.py").read_bytes()
    plan = build_integration_plan(root, reviewed=_with_capture(build_integration_plan(root), "rerank", "retobs_adapter:missing_capture"))

    with pytest.raises(ValueError, match=r"retobs_adapter\.py does not define missing_capture"):
        apply_integration_plan(plan)

    assert (root / "app.py").read_bytes() == original
    assert not (root / "retobs" / "integration.yaml").exists()


REVERT_PROJECT = {
    "search/__init__.py": "",
    "search/bm25.py": "def bm25_search(query): return []\n",
    "app.py": "from search.bm25 import bm25_search\ndef retrieve(query): return bm25_search(query)\n",
    "util.py": "VALUE = 1\n",
}


async def _applied(root: Path) -> tuple[IntegrationPlan, dict[str, bytes]]:
    originals = {relative: (root / relative).read_bytes() for relative in REVERT_PROJECT}
    planned = await integrate_project(root, IntegrationPhase.PLAN, IntegrationOptions())
    plan = planned.plan
    assert plan is not None and sorted(patch.relative_path for patch in plan.patches) == ["app.py", "search/bm25.py"]
    (root / "retobs").mkdir()
    (root / "retobs" / "integration-plan.json").write_text(json.dumps(planned.to_dict()), encoding="utf-8")
    applied = await integrate_project(root, IntegrationPhase.APPLY, IntegrationOptions(plan=plan))
    assert applied.status == "applied"
    return plan, originals


async def test_apply_marks_edits_and_revert_restores_only_retobs_edits(tmp_path: Path) -> None:
    root = _project(tmp_path, REVERT_PROJECT)
    plan, originals = await _applied(root)
    for relative in ("app.py", "search/bm25.py"):
        assert MARKER in (root / relative).read_text(encoding="utf-8")
    assert (root / "util.py").read_bytes() == originals["util.py"]

    reverted = await integrate_project(root, IntegrationPhase.REVERT, IntegrationOptions())

    assert reverted.phase == "revert" and reverted.status == "reverted"
    assert set(reverted.changed_files) == {"app.py", "search/bm25.py", "retobs/integration.yaml"}
    for relative, content in originals.items():
        assert (root / relative).read_bytes() == content
    assert not (root / "retobs" / "integration.yaml").exists()
    assert (root / "retobs" / "integration-plan.json").is_file()


async def test_revert_refuses_when_a_file_changed_after_apply(tmp_path: Path) -> None:
    root = _project(tmp_path, REVERT_PROJECT)
    await _applied(root)
    edited = (root / "app.py").read_text(encoding="utf-8") + "# local change\n"
    (root / "app.py").write_text(edited, encoding="utf-8")
    instrumented = (root / "search" / "bm25.py").read_bytes()

    with pytest.raises(ValueError, match=r"cannot revert app\.py: modified since apply"):
        await integrate_project(root, IntegrationPhase.REVERT, IntegrationOptions())

    assert (root / "app.py").read_text(encoding="utf-8") == edited
    assert (root / "search" / "bm25.py").read_bytes() == instrumented
    assert (root / "retobs" / "integration.yaml").is_file()


def test_revert_without_manifest_reports_failed(tmp_path: Path) -> None:
    result = revert_integration(tmp_path)
    assert result.phase == "revert" and result.status == "failed"
    assert result.errors and "retobs/integration.yaml" in result.errors[0]


def test_replan_reports_unknown_symbol_as_unresolved(tmp_path: Path) -> None:
    root = _project(tmp_path, {"app.py": TWO_STAGE})
    plan = build_integration_plan(root)
    reviewed = replace(plan, operators=(*plan.operators, OperatorMapping("ghost", "RERANK", "Ghost.rerank", "app.py", ("bm25",), 0.9)))

    replanned = build_integration_plan(root, reviewed=reviewed)

    assert any("ghost" in item and "Ghost.rerank" in item and "app.py" in item for item in replanned.unresolved)
    with pytest.raises(ValueError, match="unresolved"):
        replanned.validate_for_apply()


def test_plan_json_roundtrip_preserves_new_fields(tmp_path: Path) -> None:
    plan = build_integration_plan(_project(tmp_path, {"app.py": PIPELINE, **DATA_FILES}))

    restored = IntegrationPlan.from_dict(json.loads(json.dumps(plan.to_dict())))

    assert restored == plan
    assert restored.actions and restored.boundary.kind == "entrypoint_return"
    assert restored.expected_capabilities == plan.expected_capabilities


def test_cli_revert_phase(tmp_path: Path) -> None:
    root = _project(tmp_path / "proj", {"app.py": TWO_STAGE})
    original = (root / "app.py").read_bytes()
    plan_path = tmp_path / "plan.json"
    runner = CliRunner()
    assert runner.invoke(app, ["integrate", str(root), "--phase", "plan", "--output", str(plan_path)]).exit_code == 0
    assert runner.invoke(app, ["integrate", str(root), "--phase", "apply", "--plan", str(plan_path)]).exit_code == 0
    assert (root / "app.py").read_bytes() != original

    reverted = runner.invoke(app, ["integrate", str(root), "--phase", "revert"])

    assert reverted.exit_code == 0, reverted.output
    assert json.loads(reverted.output)["status"] == "reverted"
    assert (root / "app.py").read_bytes() == original
    assert sha256(original).hexdigest() == sha256((root / "app.py").read_bytes()).hexdigest()
    assert not (root / "retobs" / "integration.yaml").exists()


def test_planner_never_proposes_adapter_helpers_as_operators(tmp_path: Path) -> None:
    """``retobs_adapter.py`` defines CaptureSpecs; a helper named ``fusion_inputs`` is not a FUSE operator."""
    _project(tmp_path, {
        "app.py": TWO_STAGE,
        "retobs_adapter.py": "def fusion_inputs(bound): return {}\ndef rerank_inputs(bound): return {}\n",
    })
    plan = build_integration_plan(tmp_path)
    assert {op.relative_path for op in plan.operators} == {"app.py"}
    assert not any(patch.relative_path == "retobs_adapter.py" for patch in plan.patches)


def test_positional_lanes_are_expected_partial_with_a_capture_question(tmp_path: Path) -> None:
    _project(tmp_path, {"app.py": PIPELINE})
    plan = build_integration_plan(tmp_path)
    assert _operators(plan)["rrf"].input_mapping == "positional_lanes:lanes"
    assert plan.expected_capabilities["actual_input_output_capture"] == "partial"
    assert any("rrf" in q and "position" in q and "retobs_adapter" in q for q in plan.open_questions)
    # The review adds the capture and drops the `retrieve` wrapper from the operators (it stays the entrypoint).
    reviewed = _with_capture(plan, "rrf", "retobs_adapter:rrf_capture")
    reviewed = replace(reviewed, operators=tuple(op for op in reviewed.operators if op.op_id != "retrieve"))
    with_capture = build_integration_plan(tmp_path, reviewed=reviewed)
    assert _operators(with_capture)["rrf"].input_mapping == "capture"
    assert with_capture.expected_capabilities["actual_input_output_capture"] == "ready"
    assert not any("rrf" in q for q in with_capture.open_questions)
    assert "@trace_scope(" in with_capture.patches[0].replacement


def test_declared_routes_satisfy_the_gate_expectation(tmp_path: Path) -> None:
    _project(tmp_path, {"app.py": (
        "def intent_gate(query): return 'hybrid'\n"
        "def bm25(query, route): return [{'id': 'a', 'score': 1.0}]\n"
        "def retrieve(query): return bm25(query, intent_gate(query))\n"
    )})
    plan = build_integration_plan(tmp_path)
    assert plan.expected_capabilities["declared_route_coverage"] == "partial"
    routed = replace(
        plan,
        scenarios=tuple(replace(scenario, route="hybrid") for scenario in plan.scenarios),
    )
    reviewed = build_integration_plan(tmp_path, reviewed=routed)
    assert reviewed.expected_capabilities["declared_route_coverage"] == "ready"
    assert not any(q.startswith("gate ") for q in reviewed.open_questions)
