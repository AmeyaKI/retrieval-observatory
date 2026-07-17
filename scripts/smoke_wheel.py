from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "contracts" / "public_surface.json").is_file():
    ROOT = Path(__file__).resolve().parent
CORPUS = {"d1": "hybrid retrieval combines lexical and dense search", "d2": "rerankers rescore candidates"}
QUERIES = [{"query_id": "q1", "text": "lexical dense hybrid"}]
QRELS = {"q1": {"d1": 1}}


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


async def _record_production_trace(ro: Any, db_path: Path) -> dict[str, Any]:
    from retrieval_observatory.store.base import TraceQuery

    recorder = ro.init("wheel-production", db=str(db_path))
    await recorder.sink.start()
    context = recorder.start_trace("lexical dense hybrid", "wheel-pipeline", query_id="production-q1")
    context.span(
        "SOURCE",
        "wheel_source",
        [{"id": "d1", "score": 1.0, "rank": 1}],
        1.0,
        op_id="wheel_source",
    )
    recorder.finish(context)
    flushed = await recorder.sink.flush()
    assert not flushed.timed_out
    await recorder.sink.shutdown()
    health = recorder.health()
    assert health.accepted == 1
    assert health.exported == 1
    assert health.serialization_failures == 0
    assert health.permanent_failures == 0

    store = recorder.store
    await store.save_instrumentation_health(health)
    services = await store.list_services()
    traces = await store.list_traces(TraceQuery(service_id="wheel-production", pipeline_id="wheel-pipeline"))
    assert "wheel-production" in {service.service_id for service in services}
    assert len(traces) == 1
    assert traces[0].run_id is None
    return {
        "service_ids": [service.service_id for service in services],
        "trace_id": traces[0].trace_id,
        "run_id": traces[0].run_id,
        "telemetry_health": _json_safe(asdict(health)),
    }


def _assert_public_inventory(contract: dict[str, Any]) -> dict[str, list[str]]:
    import typer

    from retrieval_observatory.cli import app
    from retrieval_observatory.mcp.server import build_server

    cli_names = sorted(typer.main.get_command(app).commands)
    mcp_names = sorted(tool.name for tool in asyncio.run(build_server().list_tools()))
    assert cli_names == sorted(contract["cli_commands"])
    assert mcp_names == sorted(contract["mcp_tools"])
    return {"cli_commands": cli_names, "mcp_tools": mcp_names}


def _assert_loopback_server(retobs: Path, db_path: Path) -> str:
    process = subprocess.Popen(
        [str(retobs), "serve", "--port", "0", "--db", str(db_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=_isolated_env(),
    )
    try:
        time.sleep(1)
        if process.poll() is not None:
            output = process.communicate()[0]
            raise AssertionError(f"retobs serve exited early: {output}")
    finally:
        process.terminate()
        output, _ = process.communicate(timeout=10)
    assert "http://127.0.0.1:0" in output
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an installed retrieval-observatory wheel outside its source checkout.")
    parser.add_argument("--output", type=Path, required=True, help="Write canonical wheel-smoke evidence here.")
    parser.add_argument("--expected-version", required=True, help="Expected installed distribution version.")
    args = parser.parse_args()

    import retrieval_observatory as ro

    package_dir = Path(ro.__file__).resolve().parent
    assert "site-packages" in package_dir.parts
    distribution_version = importlib.metadata.version("retrieval-observatory")
    assert distribution_version == args.expected_version

    contract = json.loads((ROOT / "contracts" / "public_surface.json").read_text(encoding="utf-8"))
    public_check = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_public_surface.py"), "--json"],
        cwd=tempfile.gettempdir(),
        env=_isolated_env(),
        check=True,
        capture_output=True,
        text=True,
    )
    inventory = _assert_public_inventory(contract)

    with tempfile.TemporaryDirectory(prefix="retobs-wheel-smoke-") as directory:
        db_path = Path(directory) / "run.db"
        production_db_path = Path(directory) / "production.db"
        report = ro.evaluate(retrieve, queries=QUERIES, corpus=CORPUS, qrels=QRELS, db_path=str(db_path))
        assert report.run_id
        evidence = ro.inspect_query(report.run_id, "q1", db_path=str(db_path))
        assert evidence["scope"]["run_id"] == report.run_id
        assert evidence["ground_truth"]["relevant_doc_ids"] == ["d1"]
        production = asyncio.run(_record_production_trace(ro, production_db_path))
        server_output = _assert_loopback_server(Path(sys.executable).with_name("retobs"), production_db_path)

    ui_index = package_dir / "dashboard" / "ui" / "dist" / "index.html"
    example = package_dir / "examples" / "evaluate_scifact.yaml"
    assert ui_index.is_file()
    assert example.is_file()
    payload = {
        "distribution_version": distribution_version,
        "import_path": str(package_dir),
        "public_surface": json.loads(public_check.stdout),
        "inventory": inventory,
        "run_id": report.run_id,
        "production": production,
        "serve_output": server_output,
        "assets": {"ui_index": str(ui_index), "example": str(example)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Wheel release smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
