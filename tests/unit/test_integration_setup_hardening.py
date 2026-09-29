"""Setup defects an agent trial on a messy multi-module repository surfaced: virtualenvs scanned as
project code, capture references that break imports, a silent plan command, reviewer notes lost on
re-plan, capture coverage overstated, and scenarios left without a command."""
from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
from pathlib import Path

from typer.testing import CliRunner

from retrieval_observatory.cli import app
from retrieval_observatory.integrations.apply import apply_integration_plan
from retrieval_observatory.integrations.detect import detect_project
from retrieval_observatory.integrations.model import IntegrationManifest, IntegrationPlan, VerificationScenario
from retrieval_observatory.integrations.planner import build_integration_plan
from retrieval_observatory.integrations.verify import verify_observed_traces
from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace

TWO_STAGE = (
    "def keyword_search(query): return [{'id': 'a', 'score': 1.0}, {'id': 'b', 'score': 0.5}]\n"
    "def rerank(query, candidates): return list(reversed(candidates))\n"
    "def retrieve(query): return rerank(query, keyword_search(query))\n"
)
VENV_CFG = "home = /usr/bin\ninclude-system-site-packages = false\n"
VENDOR = "def retrieve(query): return [query]\nclass VendorRetriever:\n    def search(self, query): return [query]\n"


def _project(root: Path, files: dict[str, str]) -> Path:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _operators(plan: IntegrationPlan):
    return {operator.op_id: operator for operator in plan.operators}


def _with_capture(plan: IntegrationPlan, op_id: str, capture: str) -> IntegrationPlan:
    return replace(plan, operators=tuple(replace(op, capture=capture) if op.op_id == op_id else op for op in plan.operators))


# 1a: virtualenvs are never project code.


def test_detection_and_planning_skip_virtualenvs_and_site_packages(tmp_path: Path) -> None:
    root = _project(tmp_path, {
        "app.py": TWO_STAGE,
        ".venv-x/lib/python3.12/site-packages/somepkg/retriever.py": VENDOR,
        ".venv-x/lib/python3.12/site-packages/somepkg/qrels_schema.json": "{}\n",
        "env/pyvenv.cfg": VENV_CFG,
        "env/lib/python3.12/site-packages/otherpkg/search.py": "def search(query): return [query]\n",
        "venv312/pyvenv.cfg": VENV_CFG,
        "venv312/lib/rank_tools.py": "def rerank_all(query, docs): return docs\n",
        "vendor/dist-packages/lib/filters.py": "def filter_docs(candidates): return candidates\n",
    })

    detected = {candidate.file for candidate in detect_project(root).entrypoints}
    plan = build_integration_plan(root)

    assert detected == {"app.py"}
    seen = [
        *(op.relative_path for op in plan.operators),
        *(item["relative_path"] for item in plan.discovery["low_confidence_operators"]),
        *(item["file"] for item in plan.discovery["entrypoints"]),
        *plan.discovery["datasets"],
        *(patch.relative_path for patch in plan.patches),
    ]
    assert seen and all(path == "app.py" for path in seen), seen


# 2: a capture reference resolves by walking up from the module, never through sys.path.


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OBSERVED_MODULE = (
    "from retrieval_observatory.sdk.observe import observe\n"
    "@observe('SOURCE', op_id='keyword_search')\n"
    "def keyword_search(query): return [{'id': 'a', 'score': 1.0}, {'id': 'b', 'score': 0.5}]\n"
    "@observe('RERANK', op_id='rerank', parent_ids=('keyword_search',), capture='retobs_adapter:SYMBOL')\n"
    "def rerank(query, request): return list(reversed(request['hits']))\n"
    "def retrieve(query): return rerank(query, {'hits': keyword_search(query)})\n"
)
ADAPTER = (
    "from retrieval_observatory.tracing.capture import CaptureSpec\n"
    "rerank_capture = CaptureSpec(inputs=lambda bound: {'keyword_search': bound.arguments['request']['hits']})\n"
)


def test_string_capture_reference_resolves_the_adapter_above_the_module(tmp_path: Path) -> None:
    root = _project(tmp_path, {
        "retobs_adapter.py": ADAPTER,
        "pkg/sub/pipeline.py": OBSERVED_MODULE.replace("SYMBOL", "rerank_capture"),
    })
    module = _load_module(root / "pkg" / "sub" / "pipeline.py", "hardening_capture_ok")

    start_trace(ObserveContext(None, "q1", "widget pricing", "pipe", "svc"))
    assert module.retrieve("widget pricing") == [{"id": "b", "score": 0.5}, {"id": "a", "score": 1.0}]
    trace = finish_trace()

    span = next(span for span in trace.spans if span.op_id == "rerank")
    assert span.input_capture == "recorded"
    assert [candidate.doc_id for candidate in span.input_groups["keyword_search"]] == ["a", "b"]
    assert not trace.capture_failures


def test_unresolvable_capture_reference_is_a_recorded_failure_not_an_exception(tmp_path: Path) -> None:
    missing_file = _project(tmp_path / "no_adapter", {"pkg/pipeline.py": OBSERVED_MODULE.replace("SYMBOL", "rerank_capture")})
    missing_symbol = _project(tmp_path / "no_symbol", {
        "retobs_adapter.py": ADAPTER,
        "pkg/pipeline.py": OBSERVED_MODULE.replace("SYMBOL", "absent_capture"),
    })
    for index, root in enumerate((missing_file, missing_symbol)):
        module = _load_module(root / "pkg" / "pipeline.py", f"hardening_capture_missing_{index}")

        start_trace(ObserveContext(None, "q1", "widget pricing", "pipe", "svc"))
        assert module.retrieve("widget pricing") == [{"id": "b", "score": 0.5}, {"id": "a", "score": 1.0}]
        trace = finish_trace()

        span = next(span for span in trace.spans if span.op_id == "rerank")
        assert span.output_capture == "recorded"  # default capture still reads the returned list
        codes = [failure["code"] for failure in trace.capture_failures]
        assert codes == ["capture_reference_unresolved"], trace.capture_failures


def test_applied_capture_is_a_string_reference_without_an_import(tmp_path: Path) -> None:
    root = _project(tmp_path, {
        "app.py": TWO_STAGE,
        "retobs_adapter.py": ADAPTER.replace("request']['hits']", "candidates']"),
    })
    replanned = build_integration_plan(root, reviewed=_with_capture(build_integration_plan(root), "rerank", "retobs_adapter:rerank_capture"))

    replacement = replanned.patches[0].replacement
    assert 'capture="retobs_adapter:rerank_capture"' in replacement
    assert "import retobs_adapter" not in replacement
    assert not any("import retobs_adapter" in action.description for action in replanned.actions)


# 5a: the documented plan command says what it wrote and what to do next.


def test_plan_with_output_prints_a_summary_and_writes_unchanged_json(tmp_path: Path) -> None:
    root = _project(tmp_path / "project", {"app.py": TWO_STAGE, "data/queries.jsonl": "{}\n", "data/qrels.jsonl": "{}\n"})
    plan_path = tmp_path / "plan.json"
    runner = CliRunner()

    bare = runner.invoke(app, ["integrate", str(root), "--phase", "plan"])
    written = runner.invoke(app, ["integrate", str(root), "--phase", "plan", "--output", str(plan_path)])

    assert bare.exit_code == 0 and written.exit_code == 0, written.output
    assert plan_path.read_text(encoding="utf-8") == bare.stdout
    summary = written.stdout
    assert f"Plan written to {plan_path}" in summary
    assert "3 operators proposed" in summary
    assert "app.py:keyword_search" in summary and "app.py:rerank" in summary
    assert "Entrypoint: app.py:retrieve (function)" in summary
    assert "qrels data/qrels.jsonl" in summary
    assert "Scenarios: 2" in summary
    assert f"retobs integrate {root} --phase apply --plan {plan_path}" in summary
    assert not summary.lstrip().startswith("{")


def test_plan_summary_caps_the_operator_list_and_flags_missing_commands(tmp_path: Path) -> None:
    functions = "".join(f"def filter_{index}(candidates): return candidates\n" for index in range(25))
    root = _project(tmp_path / "project", {
        "app.py": "from fastapi import FastAPI\napp = FastAPI()\n" + functions + "@app.post('/search')\ndef search(query: str): return []\n",
    })
    plan_path = tmp_path / "plan.json"

    result = CliRunner().invoke(app, ["integrate", str(root), "--phase", "plan", "--output", str(plan_path)])

    assert result.exit_code == 0, result.output
    assert "25 operators proposed" in result.stdout
    assert "…and 5 more" in result.stdout
    assert "no command" in result.stdout


# 5b: reviewer notes survive a re-plan.


def test_reviewer_notes_survive_a_replan_through_json(tmp_path: Path) -> None:
    root = _project(tmp_path, {"app.py": TWO_STAGE})
    plan = build_integration_plan(root)
    payload = json.loads(json.dumps({"phase": "plan", "plan": plan.to_dict()}))
    payload["plan"]["notes"] = "Reviewed: rerank is the final stage; keyword lane only in staging."
    next(op for op in payload["plan"]["operators"] if op["op_id"] == "rerank")["notes"] = "cross-encoder; truncates to 10"

    replanned = build_integration_plan(root, reviewed=IntegrationPlan.from_dict(payload["plan"]))

    assert replanned.notes == "Reviewed: rerank is the final stage; keyword lane only in staging."
    assert _operators(replanned)["rerank"].notes == "cross-encoder; truncates to 10"
    assert _operators(replanned)["keyword_search"].notes is None
    assert IntegrationPlan.from_dict(json.loads(json.dumps(replanned.to_dict()))) == replanned


# 5c: the plan states which side of the boundary a CaptureSpec actually maps.


def test_capture_coverage_reflects_the_spec_provided(tmp_path: Path) -> None:
    root = _project(tmp_path, {
        "app.py": TWO_STAGE,
        "retobs_adapter.py": (
            "from retrieval_observatory.tracing.capture import CaptureSpec\n"
            "inputs_only = CaptureSpec(inputs=lambda bound: {'keyword_search': bound.arguments['candidates']})\n"
            "outputs_only = CaptureSpec(None, lambda result: result)\n"
        ),
    })
    plan = build_integration_plan(root)

    inputs_only = _operators(build_integration_plan(root, reviewed=_with_capture(plan, "rerank", "retobs_adapter:inputs_only")))["rerank"]
    outputs_only = _operators(build_integration_plan(root, reviewed=_with_capture(plan, "rerank", "retobs_adapter:outputs_only")))["rerank"]

    assert (inputs_only.input_mapping, inputs_only.output_mapping) == ("capture", "return")
    assert (outputs_only.input_mapping, outputs_only.output_mapping) == ("parameter:candidates", "capture")


# 1b(i): a scenario without a command is flagged at plan, apply and verify.


def test_blank_scenario_command_is_flagged_through_apply_and_verify(tmp_path: Path) -> None:
    root = _project(tmp_path, {"app.py": TWO_STAGE})
    plan = build_integration_plan(root)
    blank = replace(plan, scenarios=tuple(replace(scenario, command="  ") for scenario in plan.scenarios))

    replanned = build_integration_plan(root, reviewed=blank)

    assert all(scenario.command is None for scenario in replanned.scenarios)
    assert {q.split(":", 1)[0] for q in replanned.open_questions if "set command" in q} == {
        "scenario representative", "scenario representative-repeat",
    }
    applied = apply_integration_plan(replanned)
    check = next(check for check in applied.checks if check.check_id == "scenario_commands")
    assert check.status == "warn" and "representative" in " ".join(check.limitations) and check.fix

    manifest = IntegrationManifest.from_plan(replanned)
    coverage = verify_observed_traces(manifest, []).capabilities["declared_route_coverage"]
    assert {failure["code"] for failure in coverage["failures"]} == {"scenario_unobserved"}
    assert all("has no command" in failure["detail"] and "set the scenario's command" in failure["fix"] for failure in coverage["failures"])


def test_no_entrypoint_leaves_a_question_per_scenario(tmp_path: Path) -> None:
    root = _project(tmp_path, {"app.py": "VALUE = 1\n"})
    plan = build_integration_plan(root, reviewed=replace(
        build_integration_plan(root), scenarios=(VerificationScenario("only", "widget pricing", ()),),
    ))
    assert plan.scenarios[0].command is None
    assert any(q.startswith("scenario only:") for q in plan.open_questions)
