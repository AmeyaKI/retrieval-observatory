from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "external_projects"
FIXTURE_EXTRAS = {
    "python_callable": None,
    "fastapi_hybrid_dag": None,
    "langchain_retriever": "langchain",
    "llamaindex_retriever": "llamaindex",
}

DOCUMENTED_INTEGRATION_COMMANDS = {
    "plan": ("integrate", ".", "--phase", "plan", "--output", "retobs/integration-plan.json"),
    "apply": ("integrate", ".", "--phase", "apply", "--plan", "retobs/integration-plan.json"),
    "verify": ("integrate", ".", "--phase", "verify", "--plan", "retobs/integration-plan.json"),
}

DOCUMENTED_MCP_SCRIPT = r'''
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from retrieval_observatory.mcp.server import _integrate_project


parser = argparse.ArgumentParser()
parser.add_argument("--project-root", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
project_root = args.project_root.resolve()
plan_path = project_root / "retobs" / "integration-plan.json"
plan_path.parent.mkdir(parents=True, exist_ok=True)

plan = asyncio.run(_integrate_project(project_root=str(project_root), phase="plan"))
plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
apply = asyncio.run(_integrate_project(project_root=str(project_root), phase="apply", plan_path=str(plan_path)))
verify = asyncio.run(_integrate_project(project_root=str(project_root), phase="verify", plan_path=str(plan_path)))
args.output.write_text(json.dumps({"plan": plan, "apply": apply, "verify": verify}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
'''


EXERCISE_SCRIPT = r'''
from __future__ import annotations

import argparse
import asyncio
import json
import runpy
from pathlib import Path

from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace
from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.tracing import init


def record(call, *, service_id, pipeline_id, query_id, query_text):
    start_trace(ObserveContext(None, query_id, query_text, pipeline_id, service_id))
    try:
        value = call()
    except BaseException as exc:
        trace = finish_trace("ERROR", str(exc))
        return trace, None
    return finish_trace(), value


def fastapi_fixture(project, expected):
    from fastapi.testclient import TestClient

    namespace = runpy.run_path(str(project / "app" / "main.py"))
    app = namespace["app"]
    traces = []
    responses = []
    payloads = [
        {"query_id": "q-hybrid", "query": "hybrid query", "scenario": "hybrid"},
        {"query_id": "q-hybrid-repeat", "query": "hybrid query", "scenario": "hybrid"},
        {"query_id": "q-lexical", "query": "lexical query", "scenario": "lexical_only"},
        {"query_id": "q-gate", "query": "skip query", "scenario": "gate_skip"},
        {"query_id": "q-error", "query": "error query", "scenario": "retriever_error"},
    ]
    with TestClient(app) as client:
        for payload in payloads:
            trace, response = record(
                lambda payload=payload: client.post("/retrieve", json=payload),
                service_id=expected["service_id"],
                pipeline_id=expected["pipeline_id"],
                query_id=payload["query_id"],
                query_text=payload["query"],
            )
            traces.append(trace)
            responses.append({"status_code": response.status_code, "body": response.json()})
    return traces, {"responses": responses}


def callable_fixture(project, expected, symbol):
    namespace = runpy.run_path(str(project / "app" / ("retriever.py" if symbol == "retrieve" else "pipeline.py")))
    retrieve = namespace[symbol]
    traces = []
    for query_id, query in (("q-one", "current"), ("q-two", "current history")):
        trace, _ = record(
            lambda query=query: retrieve(query),
            service_id=expected["service_id"],
            pipeline_id=expected["pipeline_id"],
            query_id=query_id,
            query_text=query,
        )
        traces.append(trace)
    return traces, {}


def telemetry_failure_fixture(project):
    from fastapi.testclient import TestClient
    from retrieval_observatory.tracing import TelemetryConfig, TraceRecorder
    from retrieval_observatory.tracing.integrations.fastapi import instrument_fastapi
    from retrieval_observatory.tracing.sink import BufferedTraceSink

    class FailingExporter:
        async def export(self, batch):
            raise RuntimeError("injected exporter failure")

        async def close(self):
            return None

    payloads = [
        {"query_id": "q-hybrid", "query": "hybrid query", "scenario": "hybrid"},
        {"query_id": "q-gate", "query": "skip query", "scenario": "gate_skip"},
        {"query_id": "q-error", "query": "error query", "scenario": "retriever_error"},
    ]
    disabled = runpy.run_path(str(project / "app" / "main.py"))["app"]
    with TestClient(disabled) as client:
        golden = [(response.status_code, response.json()) for response in (client.post("/retrieve", json=item) for item in payloads)]

    config = TelemetryConfig(max_retries=0, export_timeout_s=0.01)
    sink = BufferedTraceSink(FailingExporter(), config, service_id="external-hybrid-api")
    recorder = TraceRecorder("external-hybrid-api", sink)
    enabled = runpy.run_path(str(project / "app" / "main.py"))["app"]
    instrument_fastapi(enabled, recorder, pipeline_id="hybrid-search-v1")
    with TestClient(enabled) as client:
        observed = [(response.status_code, response.json()) for response in (client.post("/retrieve", json=item) for item in payloads)]

    health = recorder.health()
    assert observed == golden
    assert health.permanent_failures >= 1
    assert health.exported == 0
    assert health.queue_depth <= config.queue_capacity
    return {
        "accepted": health.accepted,
        "exported_traces": health.exported,
        "serialization_failures": health.serialization_failures,
        "export_failures": health.permanent_failures,
        "queue_depth": health.queue_depth,
        "queue_capacity": config.queue_capacity,
    }


async def persist(traces, expected, db_path):
    recorder = init(expected["service_id"], db=str(db_path))
    await recorder.sink.start()
    for trace in traces:
        assert recorder.sink.offer(trace)
    flushed = await recorder.sink.flush()
    assert not flushed.timed_out
    await recorder.sink.shutdown()
    store = recorder.store
    await store.init_db()
    await store.save_instrumentation_health(recorder.health())
    services = await store.list_services()
    persisted = await store.list_traces(
        TraceQuery(service_id=expected["service_id"], pipeline_id=expected["pipeline_id"])
    )
    assert expected["service_id"] in {service.service_id for service in services}, (services, recorder.health())
    assert persisted, recorder.health()
    assert all(trace.run_id is None for trace in persisted)
    return {
        "services": [service.service_id for service in services],
        "traces": [{"trace_id": trace.trace_id, "run_id": trace.run_id} for trace in persisted],
    }


parser = argparse.ArgumentParser()
parser.add_argument("--fixture", required=True)
parser.add_argument("--project", type=Path, required=True)
parser.add_argument("--expected", type=Path, required=True)
parser.add_argument("--db", type=Path, required=True)
parser.add_argument("--production", type=Path, required=True)
parser.add_argument("--telemetry-health", type=Path, required=True)
args = parser.parse_args()
expected = json.loads(args.expected.read_text(encoding="utf-8"))
if args.fixture == "fastapi_hybrid_dag":
    traces, production = fastapi_fixture(args.project, expected)
    telemetry = telemetry_failure_fixture(args.project)
else:
    symbol = "retrieve" if args.fixture == "python_callable" else expected["required_operator_ids"][0]
    traces, production = callable_fixture(args.project, expected, symbol)
    telemetry = {"serialization_failures": 0, "export_failures": 0}
production.update(asyncio.run(persist(traces, expected, args.db)))
args.production.write_text(json.dumps(production, indent=2, sort_keys=True) + "\n", encoding="utf-8")
args.telemetry_health.write_text(json.dumps(telemetry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
'''


def _canonical_json(text: str) -> str:
    return json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _isolated_env(venv: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    env["PATH"] = f"{venv / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    return env


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, check=True, capture_output=True, text=True)


def _fixture_command(python: Path, fixture: str) -> list[str]:
    app_file = "main.py" if fixture == "fastapi_hybrid_dag" else ("retriever.py" if fixture == "python_callable" else "pipeline.py")
    return [str(python), str(Path("app") / app_file)]


def _run_fixture(python: Path, fixture: str, project: Path, env: dict[str, str]) -> str:
    result = _run(_fixture_command(python, fixture), cwd=project, env=env)
    return _canonical_json(result.stdout)


def _wheel_spec(wheel: Path, fixture: str) -> str:
    extras = ["dashboard", "mcp"]
    if framework_extra := FIXTURE_EXTRAS[fixture]:
        extras.append(framework_extra)
    return f"{wheel}[{','.join(extras)}]"


def _assert_fixture_result(expected: dict[str, Any], verification: dict[str, Any], telemetry: dict[str, Any]) -> None:
    observed_edges = {
        (parent, node)
        for variant in verification["topology_variants"]
        for node, parents in ast.literal_eval(variant["signature"])
        for parent in parents
    }
    assert set(expected["required_operator_ids"]) <= set(verification["observed_operator_ids"])
    assert {tuple(edge) for edge in expected["required_edges"]} <= observed_edges
    assert verification["status"] == "ready"
    assert all(verification["capabilities"][name]["available"] for name in expected["required_capabilities"])
    assert verification["telemetry_health"]["serialization_failures"] == 0
    assert verification["telemetry_health"]["export_failures"] == 0
    assert telemetry["serialization_failures"] == 0


def _prepare_documented_callable(project: Path) -> None:
    package = project / "mypackage"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "search.py").write_text("from app.retriever import retrieve\n", encoding="utf-8")
    data = project / "data"
    data.mkdir(exist_ok=True)
    (data / "queries.jsonl").write_text('{"query_id":"q-docs","text":"current"}\n', encoding="utf-8")
    (data / "corpus.jsonl").write_text('{"id":"d-callable-current","text":"current retrieval policy"}\n', encoding="utf-8")
    (data / "qrels.jsonl").write_text('{"query_id":"q-docs","relevant_doc_ids":["d-callable-current"]}\n', encoding="utf-8")


def _exercise_fixture(wheel: Path, fixture: str, artifacts: Path, keep_workdir: bool) -> None:
    expected = json.loads((FIXTURE_ROOT / fixture / "expected.json").read_text(encoding="utf-8"))
    fixture_artifacts = artifacts / fixture
    fixture_artifacts.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix=f"retobs-{fixture}-"))
    try:
        project = workdir / fixture
        shutil.copytree(FIXTURE_ROOT / fixture, project)
        documented_project = workdir / f"{fixture}-docs"
        shutil.copytree(FIXTURE_ROOT / fixture, documented_project)
        venv = workdir / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True, text=True)
        env = _isolated_env(venv)
        python = venv / "bin" / "python"
        pip = [str(python), "-m", "pip"]
        _run([*pip, "install", "--index-url", "https://pypi.org/simple", _wheel_spec(wheel, fixture)], cwd=workdir, env=env)

        before = _run_fixture(python, fixture, project, env)
        (fixture_artifacts / "before.json").write_text(before, encoding="utf-8")
        db_path = project / ".retobs" / "results.db"
        retobs = venv / "bin" / "retobs"
        documented = {}
        for phase in ("plan", "apply"):
            command = DOCUMENTED_INTEGRATION_COMMANDS[phase]
            result = _run([str(retobs), *command], cwd=project, env=env)
            output = result.stdout.strip()
            documented[phase] = {
                "command": ["retobs", *command],
                "stderr": result.stderr,
                "stdout": result.stdout,
            }
            if phase == "plan":
                documented[phase]["payload"] = json.loads((project / "retobs" / "integration-plan.json").read_text(encoding="utf-8"))
            else:
                documented[phase]["payload"] = json.loads(output)
        after = _run_fixture(python, fixture, project, env)
        (fixture_artifacts / "after.json").write_text(after, encoding="utf-8")
        assert before == after

        exercise = workdir / "exercise_fixture.py"
        exercise.write_text(EXERCISE_SCRIPT, encoding="utf-8")
        _run(
            [
                str(python), str(exercise), "--fixture", fixture, "--project", str(project), "--expected", str(project / "expected.json"),
                "--db", str(db_path), "--production", str(fixture_artifacts / "production.json"),
                "--telemetry-health", str(fixture_artifacts / "telemetry-health.json"),
            ],
            cwd=workdir,
            env=env,
        )
        phase = "verify"
        command = DOCUMENTED_INTEGRATION_COMMANDS[phase]
        result = _run([str(retobs), *command], cwd=project, env=env)
        documented[phase] = {
            "command": ["retobs", *command],
            "payload": json.loads(result.stdout),
            "stderr": result.stderr,
            "stdout": result.stdout,
        }
        (fixture_artifacts / "documented-cli.json").write_text(
            json.dumps(documented, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        shutil.copy(project / "retobs" / "integration-plan.json", fixture_artifacts / "plan.json")
        (fixture_artifacts / "apply.json").write_text(
            json.dumps(documented["apply"]["payload"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        mcp_script = workdir / "documented_mcp.py"
        mcp_script.write_text(DOCUMENTED_MCP_SCRIPT, encoding="utf-8")
        _run(
            [str(python), str(mcp_script), "--project-root", str(documented_project), "--output", str(fixture_artifacts / "documented-mcp.json")],
            cwd=workdir,
            env=env,
        )
        if fixture == "python_callable":
            _prepare_documented_callable(documented_project)
            result = _run(
                [
                    str(retobs), "evaluate", "mypackage.search:retrieve", "--queries", "data/queries.jsonl",
                    "--qrels", "data/qrels.jsonl", "--corpus", "data/corpus.jsonl",
                ],
                cwd=documented_project,
                env=env,
            )
            (fixture_artifacts / "documented-evaluate.txt").write_text(result.stdout, encoding="utf-8")
        _run(
            [str(retobs), "integrate", str(project), "--phase", "verify", "--plan", str(fixture_artifacts / "plan.json"), "--output", str(fixture_artifacts / "verification.json"), "--db", str(db_path)],
            cwd=workdir,
            env=env,
        )
        verification = json.loads((fixture_artifacts / "verification.json").read_text(encoding="utf-8"))
        telemetry = json.loads((fixture_artifacts / "telemetry-health.json").read_text(encoding="utf-8"))
        _assert_fixture_result(expected, verification, telemetry)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(error.stderr or error.stdout or str(error)) from error
    finally:
        if keep_workdir:
            print(f"{fixture}: retained {workdir}")
        else:
            shutil.rmtree(workdir)


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise external retrieval fixtures against one installed wheel.")
    parser.add_argument("--wheel", type=Path, required=True, help="Exact wheel under test.")
    parser.add_argument("--fixture", choices=[*FIXTURE_EXTRAS, "all"], required=True, help="Fixture selector.")
    parser.add_argument("--artifacts", type=Path, required=True, help="Output root for fixture evidence.")
    parser.add_argument("--keep-workdir", action="store_true", help="Retain copied fixture work directories for debugging.")
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    if not wheel.is_file():
        parser.error(f"wheel does not exist: {wheel}")
    selected = tuple(FIXTURE_EXTRAS) if args.fixture == "all" else (args.fixture,)
    for fixture in selected:
        _exercise_fixture(wheel, fixture, args.artifacts.resolve(), args.keep_workdir)
        print(f"{fixture}: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
