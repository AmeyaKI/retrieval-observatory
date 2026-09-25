"""Validate an installed retrieval-observatory wheel outside its source checkout.

Run with the interpreter of a clean venv the wheel was installed into, from a directory outside the
repository. Every check runs; the JSON written to ``--output`` records each check's status. A check
is ``skipped`` only when an optional extra is absent (with the reason recorded) and never counts as
passed; ``--require-extra`` turns that skip into a failure. Exit status is 1 when any check failed.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "contracts" / "public_surface.json").is_file():
    ROOT = Path(__file__).resolve().parent  # the release evidence bundle keeps the same layout
V2_POLICY = ROOT / "examples" / "ci" / "release-policy.yaml"
CORPUS = {"d1": "hybrid retrieval combines lexical and dense search", "d2": "rerankers rescore candidates"}
QUERIES = [{"query_id": "q1", "text": "lexical dense hybrid"}]
QRELS = {"q1": {"d1": 1}}

#: Installed files `retobs demo`, `retobs serve`, and the agent runbook read at runtime.
#: The package loads no files from the repository's `contracts/` directory.
RUNTIME_RESOURCES = (
    "dashboard/ui/dist/index.html",
    "examples/golden_fixture.py",
    "examples/release-policy-golden-v3.yaml",
    "examples/evaluate_scifact.yaml",
    "examples/agent_integration/SKILL.md",
    "examples/agent_integration/references/plan-review.md",
    "examples/agent_integration/references/retobs_adapter_example.py",
)
#: Modules retired by the focused rebuild (docs/rebuild retirement inventory, T19/T20).
RETIRED_MODULES = (
    "retrieval_observatory.experimental",
    "retrieval_observatory.experimental.forge",
    "retrieval_observatory.experimental.classifier",
    "retrieval_observatory.experimental.advisor",
    "retrieval_observatory.experimental.diagram",
    "retrieval_observatory.forge",
    "retrieval_observatory.classifier",
    "retrieval_observatory.advisor",
    "retrieval_observatory.diagram",
    "retrieval_observatory.tracing.replay",
    "retrieval_observatory.tracing.attribution",
    "retrieval_observatory.tracing.enrich",
    "retrieval_observatory.tracing.monitor",
    "retrieval_observatory.metrics.pareto",
    "retrieval_observatory.analysis.cohorts",
    "retrieval_observatory.analysis.corpus_health",
    "retrieval_observatory.analysis.loss_attribution",
    "retrieval_observatory.analysis.service",
)
#: Top-level modules of optional extras; the core import and `retobs --help` must not need them.
OPTIONAL_MODULES = (
    "fastapi", "uvicorn", "starlette", "multipart", "mcp", "asyncpg", "pgvector", "qdrant_client",
    "langchain_core", "llama_index", "sentence_transformers", "torch", "faiss", "beir", "datasets",
    "rank_bm25", "cohere", "anthropic", "openai", "google",
)
NO_EXTRAS_SCRIPT = r"""
import importlib.abc, sys
BLOCKED = set(sys.argv[1].split(","))
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError(f"blocked optional dependency: {name}", name=name)
        return None
sys.meta_path.insert(0, Blocker())
import retrieval_observatory
from retrieval_observatory import compare, evaluate, inspect_document, inspect_query
from retrieval_observatory.cli import app
sys.argv = ["retobs", "--help"]
try:
    app()
except SystemExit as exit:
    assert exit.code in (0, None), exit.code
loaded = sorted(name for name in sys.modules if name.split(".")[0] in BLOCKED)
assert not loaded, loaded
"""


class Skipped(Exception):
    """An optional check that cannot run in this environment; the message is the reason."""


def retrieve(_: str) -> list[str]:
    return ["d1", "d2"]


def _json_safe(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _isolated_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    env["PYTHONUNBUFFERED"] = "1"
    return env


def installed_origin(module_file: str) -> Path:
    """The module's file, asserted to live inside this interpreter's environment (not a checkout)."""
    path, prefix = Path(module_file).resolve(), Path(sys.prefix).resolve()
    if prefix not in path.parents:
        raise AssertionError(f"retrieval_observatory imported from {path}, outside the interpreter environment {prefix}")
    return path


class Smoke:
    def __init__(self, workdir: Path, required_extras: set[str]) -> None:
        import retrieval_observatory

        self.workdir = workdir
        self.required_extras = required_extras
        self.package_dir = Path(retrieval_observatory.__file__).resolve().parent
        self.retobs = Path(sys.executable).with_name("retobs")
        self.demo: dict[str, Any] | None = None

    def _cli(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [str(self.retobs), *args], cwd=self.workdir, env=_isolated_env(), capture_output=True, text=True, timeout=300
        )
        if check and completed.returncode != 0:
            raise AssertionError(f"retobs {' '.join(args)} exited {completed.returncode}: {completed.stderr[-2000:]}")
        return completed

    def _optional(self, extra: str, *modules: str) -> None:
        missing = [module for module in modules if importlib.util.find_spec(module) is None]
        if not missing:
            return
        reason = f"the '{extra}' extra is not installed (missing {', '.join(missing)})"
        if extra in self.required_extras:
            raise AssertionError(f"{reason}, but --require-extra {extra} was given")
        raise Skipped(reason)

    def _demo(self) -> dict[str, Any]:
        if self.demo is None:
            out = self.workdir / "demo"
            self._cli("demo", "--output-dir", str(out), "--db", str(out / "demo.db"))
            self.demo = json.loads((out / "demo_manifest.json").read_text(encoding="utf-8"))
        return self.demo

    # ── checks ────────────────────────────────────────────────────────────────────────────────

    def import_origin(self) -> dict[str, Any]:
        import retrieval_observatory

        return {"module_file": str(installed_origin(retrieval_observatory.__file__)), "sys_prefix": str(Path(sys.prefix).resolve())}

    def installed_resources(self) -> dict[str, Any]:
        missing = [name for name in RUNTIME_RESOURCES if not (self.package_dir / name).is_file()]
        dist = self.package_dir / "dashboard" / "ui" / "dist"
        referenced: list[str] = []
        if (dist / "index.html").is_file():
            html = (dist / "index.html").read_text(encoding="utf-8")
            referenced = sorted(set(re.findall(r"""(?:src|href)=["']/?(assets/[^"']+)["']""", html)))
            if not referenced:
                raise AssertionError("dashboard index.html references no bundled assets")
            missing += [f"dashboard/ui/dist/{name}" for name in referenced if not (dist / name).is_file()]
        if missing:
            raise AssertionError(f"installed package is missing runtime files: {', '.join(missing)}")
        return {"resources": list(RUNTIME_RESOURCES), "dashboard_assets": referenced}

    def retired_modules_absent(self) -> dict[str, Any]:
        present = []
        for name in RETIRED_MODULES:
            try:
                spec = importlib.util.find_spec(name)
            except ModuleNotFoundError:
                spec = None  # a retired parent package is gone, so the child cannot be found either
            if spec is not None:
                present.append(name)
        if present:
            raise AssertionError(f"retired modules are importable: {', '.join(present)}")
        return {"absent": list(RETIRED_MODULES)}

    def core_without_extras(self) -> dict[str, Any]:
        subprocess.run(
            [sys.executable, "-c", NO_EXTRAS_SCRIPT, ",".join(OPTIONAL_MODULES)],
            cwd=self.workdir, env=_isolated_env(), check=True, capture_output=True, text=True, timeout=120,
        )
        return {"blocked_modules": list(OPTIONAL_MODULES), "commands": ["import retrieval_observatory", "retobs --help"]}

    def public_surface(self) -> dict[str, Any]:
        self._optional("mcp", "mcp")
        contract = json.loads((ROOT / "contracts" / "public_surface.json").read_text(encoding="utf-8"))
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_public_surface.py"), "--json"],
            cwd=self.workdir, env=_isolated_env(), capture_output=True, text=True, timeout=120,
        )
        result = json.loads(completed.stdout)
        if completed.returncode != 0 or not result["valid"]:
            raise AssertionError(f"public surface differs from contracts/public_surface.json: {result['mismatches']}")
        import typer

        from retrieval_observatory.cli import app

        cli_names = sorted(typer.main.get_command(app).commands)
        if cli_names != sorted(contract["cli_commands"]):
            raise AssertionError(f"CLI commands {cli_names} != contract {sorted(contract['cli_commands'])}")
        return {"cli_commands": cli_names}

    def mcp_tool_registration(self) -> dict[str, Any]:
        self._optional("mcp", "mcp")
        from retrieval_observatory.mcp.server import build_server

        contract = json.loads((ROOT / "contracts" / "public_surface.json").read_text(encoding="utf-8"))
        names = sorted(tool.name for tool in asyncio.run(build_server().list_tools()))
        if names != sorted(contract["mcp_tools"]):
            raise AssertionError(f"MCP tools {names} != contract {sorted(contract['mcp_tools'])}")
        return {"mcp_tools": names}

    def sdk_evaluate(self) -> dict[str, Any]:
        import retrieval_observatory as ro

        db_path = self.workdir / "sdk" / "run.db"
        db_path.parent.mkdir()
        report = ro.evaluate(retrieve, queries=QUERIES, corpus=CORPUS, qrels=QRELS, db_path=str(db_path))
        evidence = ro.inspect_query(report.run_id, "q1", db_path=str(db_path))
        assert evidence["scope"]["run_id"] == report.run_id
        assert evidence["ground_truth"]["relevant_doc_ids"] == ["d1"]
        return {"run_id": report.run_id}

    def production_trace(self) -> dict[str, Any]:
        import retrieval_observatory as ro

        return asyncio.run(_record_production_trace(ro, self.workdir / "production.db"))

    def serve_loopback(self) -> dict[str, Any]:
        self._optional("dashboard", "fastapi", "uvicorn")
        db_path = self.workdir / "serve.db"
        self._cli("demo", "--output-dir", str(self.workdir / "serve"), "--db", str(db_path))
        process = subprocess.Popen(
            [str(self.retobs), "serve", "--port", "0", "--db", str(db_path)],
            cwd=self.workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=_isolated_env(),
        )
        try:
            time.sleep(1)
            if process.poll() is not None:
                raise AssertionError(f"retobs serve exited early: {process.communicate()[0]}")
        finally:
            process.terminate()
            output, _ = process.communicate(timeout=10)
        assert "http://127.0.0.1:0" in output, output
        return {"serve_output": output}

    def demo_compare_audit(self) -> dict[str, Any]:
        demo = self._demo()
        artifacts = self.workdir / "audit"
        completed = self._cli(
            "compare", demo["baseline_run_id"], demo["validation_run_id"], "--db", demo["db_path"],
            "--policy", demo["policy_path"], "--artifacts", str(artifacts), "--fail-on", "hold-or-block-or-fail",
            check=False,
        )
        assert completed.returncode == 0, f"compare exited {completed.returncode}: {completed.stdout[-1500:]}{completed.stderr[-1500:]}"
        audit = json.loads((artifacts / "release-audit.json").read_text(encoding="utf-8"))
        html = (artifacts / "release-audit.html").read_text(encoding="utf-8")
        assert audit["decision"]["status"] == "PASS", audit["decision"]
        # A standalone file: no scripts and no loaded resource (image, stylesheet, font) that needs a
        # server or network. Plain <a href> links into the dashboard are navigation, not loads.
        loads = re.findall(
            r"""\bsrc\s*=\s*["'](?!data:)([^"']*)|<link\b[^>]*\bhref\s*=\s*["']([^"']*)|url\(\s*["']?(?!data:)([^)"']*)|@import""",
            html,
            flags=re.IGNORECASE,
        )
        assert "<script" not in html.lower() and not loads, loads
        return {"decision": audit["decision"]["status"], "artifacts": ["release-audit.json", "release-audit.html"], "html_bytes": len(html)}

    def inspect_document(self) -> dict[str, Any]:
        demo = self._demo()
        completed = self._cli(
            "inspect-document", demo["baseline_run_id"], demo["repaired_document"], "--db", demo["db_path"], "--format", "json"
        )
        envelope = json.loads(completed.stdout)
        outcomes = sorted({row["outcome"] for row in envelope["rows"]})
        assert "relevant_excluded" in outcomes, outcomes
        return {"entity": demo["repaired_document"], "outcomes": outcomes}

    def storage_migrate_v2(self) -> dict[str, Any]:
        from retrieval_observatory.store.base import InvestigationFilter, InvestigationScope
        from retrieval_observatory.store.sqlite import SQLiteStore

        db_path = self.workdir / "legacy" / "legacy.db"
        db_path.parent.mkdir()
        asyncio.run(_v2_database(db_path))
        report = json.loads(self._cli("storage", "migrate", "--db", str(db_path)).stdout)
        assert report["status"] == "migrated" and (report["from_version"], report["to_version"]) == (2, 3), report

        async def _read() -> dict[str, Any]:
            store = SQLiteStore(str(db_path), read_only=True)
            await store.init_db()
            assert store.investigation_tables_available
            scope = InvestigationScope(run_id="run-v2", pipeline_id="bm25", evaluation_digest="eval")
            page = await store.list_investigation_pairs(scope, InvestigationFilter(outcome="loss"))
            return {
                "runs": [run["run_id"] for run in await store.list_runs()],
                "traces": [trace.trace_id for trace in await store.get_traces("run-v2")],
                "investigation_pairs": page.total,
            }

        reads = asyncio.run(_read())
        assert reads["runs"] == ["run-v2"] and reads["traces"] == ["t1"], reads
        return {"migration": {key: report[key] for key in ("status", "from_version", "to_version", "tables_added")}, "reads": reads}

    def v2_policy_conversion(self) -> dict[str, Any]:
        import yaml

        from retrieval_observatory.release.policy import ReleasePolicy, load_release_policy
        from retrieval_observatory.store.sqlite import SQLiteStore

        if not V2_POLICY.is_file():
            raise AssertionError(f"v2 policy example is missing: {V2_POLICY}")
        demo = self._demo()

        async def _first_unbranched_stage() -> tuple[str, int, int]:
            store = SQLiteStore(demo["db_path"], read_only=True)
            await store.init_db()
            rows = [row for row in await store.get_metrics(demo["baseline_run_id"]) if row["metric_name"] == "recall"]
            row = min((row for row in rows if row["branch_id"] is None and row["stage_index"] >= 0), key=lambda row: row["stage_index"])
            return row["pipeline_id"], row["stage_index"], row["k"]

        # The example's positional selector, re-pointed at an unbranched stage of the demo pipeline so
        # the conversion must map it to one operator from the runs' traces.
        pipeline_id, stage, k = asyncio.run(_first_unbranched_stage())
        payload = yaml.safe_load(V2_POLICY.read_text(encoding="utf-8"))
        for guard in payload["metrics"]:
            guard["metric"] = f"{pipeline_id}|stage{stage}|recall@{k}"
        policy = self.workdir / "release-policy-v2.yaml"
        policy.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        loaded = load_release_policy(policy)
        assert isinstance(loaded, ReleasePolicy) and loaded.schema_version == 2, type(loaded)
        artifacts = self.workdir / "audit-v2"
        self._cli(
            "compare", demo["baseline_run_id"], demo["validation_run_id"], "--db", demo["db_path"],
            "--policy", str(policy), "--artifacts", str(artifacts),
        )
        audit = json.loads((artifacts / "release-audit.json").read_text(encoding="utf-8"))
        conversion = audit["policy"]["conversion"]
        assert audit["policy"]["schema_version"] == 2, audit["policy"]
        assert conversion["policy"] is not None and not conversion["unresolved"], conversion
        return {
            "policy_id": loaded.id,
            "v2_selectors": [guard["metric"] for guard in payload["metrics"]],
            "v3_targets": [check["target"] for check in conversion["policy"]["metrics"]],
        }


async def _record_production_trace(ro: Any, db_path: Path) -> dict[str, Any]:
    from retrieval_observatory.store.base import TraceQuery

    recorder = ro.init("wheel-production", db=str(db_path))
    await recorder.sink.start()
    context = recorder.start_trace("lexical dense hybrid", "wheel-pipeline", query_id="production-q1")
    context.span("SOURCE", "wheel_source", [{"id": "d1", "score": 1.0, "rank": 1}], 1.0, op_id="wheel_source")
    recorder.finish(context)
    flushed = await recorder.sink.flush()
    assert not flushed.timed_out
    await recorder.sink.shutdown()
    health = recorder.health()
    assert health.accepted == 1 and health.exported == 1
    assert health.serialization_failures == 0 and health.permanent_failures == 0

    store = recorder.store
    await store.save_instrumentation_health(health)
    services = await store.list_services()
    traces = await store.list_traces(TraceQuery(service_id="wheel-production", pipeline_id="wheel-pipeline"))
    assert "wheel-production" in {service.service_id for service in services}
    assert len(traces) == 1 and traces[0].run_id is None
    return {"trace_id": traces[0].trace_id, "telemetry_health": _json_safe(asdict(health))}


async def _v2_database(db_path: Path) -> None:
    """A populated schema-v2 file, built as tests/unit/test_schema_v3_migration.py builds it."""
    from retrieval_observatory.store.sqlite import SQLiteStore
    from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace

    store = SQLiteStore(str(db_path))
    await store.init_db()
    await store.save_run("run-v2", "exp", "{}")
    await store.save_traces([
        RetrievalTrace(
            trace_id="t1", service_id="bench", run_id="run-v2", query_id="q1", query_text="hello", pipeline_id="bm25",
            spans=(OperatorSpan.source("source", "Source", (Candidate("d1", 1.0, 1),)),), final_op_ids=("source",),
        )
    ])
    await store.save_qrels("run-v2", {"q1": {"d1": 1}})
    await store.save_metric("run-v2", "bm25", "q1", 0, "recall", 10, 1.0)
    with sqlite3.connect(db_path) as db:
        for table in ("investigation_pairs", "investigation_projections", "investigation_summaries"):
            db.execute(f"DROP TABLE {table}")
        db.execute("PRAGMA user_version = 2")
        db.commit()


CHECKS: tuple[str, ...] = (
    "import_origin",
    "installed_resources",
    "retired_modules_absent",
    "core_without_extras",
    "public_surface",
    "mcp_tool_registration",
    "sdk_evaluate",
    "production_trace",
    "serve_loopback",
    "demo_compare_audit",
    "inspect_document",
    "storage_migrate_v2",
    "v2_policy_conversion",
)


def _run_check(check: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return {"status": "passed", "detail": _json_safe(check())}
    except Skipped as skip:
        return {"status": "skipped", "reason": str(skip)}
    except Exception as error:  # every check runs; each failure is recorded, then the smoke exits 1
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else ""
        return {"status": "failed", "error": f"{type(error).__name__}: {error}", "trace": (detail or traceback.format_exc())[-3000:]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True, help="Write the wheel-smoke result JSON here.")
    parser.add_argument("--expected-version", required=True, help="Expected installed distribution version.")
    parser.add_argument(
        "--require-extra", action="append", default=[], choices=["dashboard", "mcp"],
        help="Fail (instead of skip) the checks that need this extra. Repeatable.",
    )
    args = parser.parse_args()

    distribution_version = importlib.metadata.version("retrieval-observatory")
    if distribution_version != args.expected_version:
        parser.error(f"installed version {distribution_version} != expected {args.expected_version}")
    with tempfile.TemporaryDirectory(prefix="retobs-wheel-smoke-") as directory:
        smoke = Smoke(Path(directory).resolve(), set(args.require_extra))
        checks = {name: _run_check(getattr(smoke, name)) for name in CHECKS}
    counts = {status: sum(1 for check in checks.values() if check["status"] == status) for status in ("passed", "failed", "skipped")}
    payload = {
        "distribution_version": distribution_version,
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation()},
        "platform": platform.platform(),
        "sys_prefix": str(Path(sys.prefix).resolve()),
        "import_path": str(smoke.package_dir),
        "required_extras": sorted(args.require_extra),
        "checks": checks,
        "summary": counts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for name, check in checks.items():
        note = check.get("reason") or check.get("error") or ""
        print(f"{name}: {check['status'].upper()}{' — ' + note if note else ''}")
    print(f"Wheel smoke: {counts['passed']} passed, {counts['failed']} failed, {counts['skipped']} skipped")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
