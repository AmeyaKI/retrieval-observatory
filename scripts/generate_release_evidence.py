from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
import zipfile


REQUIRED_GATES = {
    "public_surface",
    "removed_vocabulary",
    "markdown_links",
    "ruff",
    "python_unit_contracts",
    "python_integration",
    "sqlite_store",
    "postgres_store",
    "ui_vitest",
    "ui_build",
    "browser_desktop_mobile",
    "wheel_metadata",
    "wheel_smoke",
    "external_python",
    "external_fastapi",
    "external_langchain",
    "external_llamaindex",
    "artifact_digest",
}

#: External-fixture gates and the fixture whose capabilities.json each one produces.
EXTERNAL_GATE_FIXTURES = {
    "external_python": "python_callable",
    "external_fastapi": "fastapi_hybrid_dag",
    "external_langchain": "langchain_retriever",
    "external_llamaindex": "llamaindex_retriever",
}

WORKFLOW_PROOFS = {
    "retrieval_release_decision": {
        "gate": "python_integration",
        "tests": ["tests/integration/test_release_decision_workflow.py"],
    },
    "candidate_lineage_workflow": {
        "gate": "python_integration",
        "tests": ["tests/integration/test_candidate_lineage_workflow.py"],
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wheel(dist: Path) -> Path:
    wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"expected exactly one wheel in {dist}, found {len(wheels)}")
    return wheels[0]


def _wheel_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_paths = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise ValueError(f"expected exactly one wheel METADATA file in {wheel}")
        metadata = Parser().parsestr(archive.read(metadata_paths[0]).decode("utf-8"))
    version = metadata.get("Version")
    if not version:
        raise ValueError(f"wheel METADATA has no Version: {wheel}")
    return version


def _source_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _result_files(results_dir: Path) -> dict[str, dict[str, Any]]:
    gates: dict[str, dict[str, Any]] = {}
    for path in sorted(results_dir.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "id" not in payload:
            continue
        gate_id = payload["id"]
        if not isinstance(gate_id, str):
            raise ValueError(f"result {path} has a non-string gate id")
        if gate_id in gates:
            raise ValueError(f"duplicate result for gate {gate_id}: {path}")
        gates[gate_id] = payload
    return gates


def _validate_gates(gates: dict[str, dict[str, Any]], wheel_digest: str) -> list[dict[str, Any]]:
    missing = sorted(REQUIRED_GATES - gates.keys())
    if missing:
        raise ValueError(f"missing required gate results: {', '.join(missing)}")
    evidence: list[dict[str, Any]] = []
    for gate_id in sorted(REQUIRED_GATES):
        gate = gates[gate_id]
        if gate.get("status") != "passed":
            raise ValueError(f"gate {gate_id} did not pass: {gate.get('status')!r}")
        if not isinstance(gate.get("command"), str) or not gate["command"].strip():
            raise ValueError(f"gate {gate_id} has no command")
        if not isinstance(gate.get("artifacts"), list) or not gate["artifacts"]:
            raise ValueError(f"gate {gate_id} has no evidence artifacts")
        if gate.get("wheel_sha256") != wheel_digest:
            raise ValueError(f"gate {gate_id} references a different wheel digest")
        timestamp = gate.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp:
            raise ValueError(f"gate {gate_id} has no timestamp")
        entry = {
            "id": gate_id,
            "status": "passed",
            "command": gate["command"],
            "artifacts": gate["artifacts"],
            "wheel_sha256": wheel_digest,
            "timestamp": timestamp,
        }
        if isinstance(gate.get("environment"), dict):
            entry["environment"] = gate["environment"]
        evidence.append(entry)
    return evidence


def _artifact_hashes(dist: Path) -> dict[str, str]:
    return {path.name: _sha256(path) for path in sorted(dist.iterdir()) if path.name.endswith((".whl", ".tar.gz"))}


def _wheel_smokes(results_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Per-interpreter wheel-smoke summaries, and every skipped optional check with its reason."""
    smokes: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for path in sorted(results_dir.rglob("wheel-smoke-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        checks = payload.get("checks", {})
        failed = sorted(name for name, check in checks.items() if check.get("status") not in ("passed", "skipped"))
        if failed:
            raise ValueError(f"wheel smoke {path.name} has failed checks: {', '.join(failed)}")
        for name, check in sorted(checks.items()):
            if check["status"] == "skipped":
                if not check.get("reason"):
                    raise ValueError(f"wheel smoke {path.name} skipped {name} without a reason")
                skipped.append({"source": path.name, "check": name, "reason": check["reason"]})
        smokes.append(
            {
                "file": path.name,
                "python": payload.get("python", {}).get("version"),
                "platform": payload.get("platform"),
                "required_extras": payload.get("required_extras", []),
                "summary": {status: sum(1 for check in checks.values() if check["status"] == status) for status in ("passed", "failed", "skipped")},
            }
        )
    return smokes, skipped


def _fixture_capabilities(results_dir: Path) -> dict[str, dict[str, str]]:
    return {
        path.parent.name: {name: capability["status"] for name, capability in sorted(json.loads(path.read_text(encoding="utf-8")).items())}
        for path in sorted(results_dir.rglob("capabilities.json"))
    }


def _markdown(evidence: dict[str, Any]) -> str:
    distribution = evidence["distribution"]
    lines = [
        "# retobs release evidence",
        "",
        f"- Version: `{evidence['version']}`",
        f"- Wheel SHA-256: `{distribution['sha256']}`",
        f"- Source commit: `{evidence['source_commit']}`",
        f"- Generated: `{evidence['generated_at']}`",
        "",
        "| Gate | Status | Command | Evidence artifact | Environment |",
        "|---|---|---|---|---|",
    ]
    for gate in evidence["gates"]:
        command = gate["command"].replace("|", "\\|")
        artifacts = "<br>".join(gate["artifacts"])
        environment = gate.get("environment", {})
        where = f"Python {environment['python']} · {environment['platform']}" if environment else "not recorded"
        lines.append(f"| {gate['id']} | {gate['status']} | `{command}` | {artifacts} | {where} |")
    lines.extend(["", "## Artifacts", ""])
    lines.extend(f"- `{name}`: `{digest}`" for name, digest in evidence["artifacts"].items())
    lines.extend(["", "## Wheel smoke by interpreter", ""])
    for smoke in evidence["wheel_smoke"]:
        summary = smoke["summary"]
        lines.append(
            f"- Python {smoke['python']} ({smoke['platform']}): {summary['passed']} passed, "
            f"{summary['failed']} failed, {summary['skipped']} skipped"
        )
    lines.extend(["", "## Fixture capabilities", ""])
    for fixture, capabilities in evidence["fixture_capabilities"].items():
        lines.append(f"- `{fixture}`: " + ", ".join(f"{name}={status}" for name, status in capabilities.items()))
    lines.extend(["", "## Skipped optional checks", ""])
    lines.extend(f"- `{item['check']}` ({item['source']}): {item['reason']}" for item in evidence["skipped_checks"])
    if not evidence["skipped_checks"]:
        lines.append("- None")
    lines.extend(["", "## Known limitations", ""])
    lines.extend(f"- {item}" for item in evidence["known_limitations"])
    if not evidence["known_limitations"]:
        lines.append("- None recorded")
    lines.extend(["", "## Workflow proofs", ""])
    for proof in evidence["workflow_proofs"]:
        lines.append(f"- `{proof['id']}` — `{proof['gate']}`: {', '.join(proof['tests'])}")
    return "\n".join(lines) + "\n"


def generate(results_dir: Path, dist: Path, known_limitations: list[str] | None = None) -> dict[str, Any]:
    wheel = _wheel(dist)
    wheel_digest = _sha256(wheel)
    smokes, skipped = _wheel_smokes(results_dir)
    evidence = {
        "version": _wheel_version(wheel),
        "source_commit": _source_commit(),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "distribution": {
            "path": str(wheel),
            "sha256": wheel_digest,
            "version": _wheel_version(wheel),
        },
        "artifacts": _artifact_hashes(dist),
        "gates": _validate_gates(_result_files(results_dir), wheel_digest),
        "wheel_smoke": smokes,
        "skipped_checks": skipped,
        "fixture_capabilities": _fixture_capabilities(results_dir),
        "known_limitations": [item.strip() for item in known_limitations or [] if item.strip()],
        "workflow_proofs": [
            {"id": proof_id, **proof}
            for proof_id, proof in sorted(WORKFLOW_PROOFS.items())
        ],
    }
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate machine-verifiable release evidence from gate result files.")
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument(
        "--known-limitation", action="append", default=[], help="A known limitation of this candidate to record. Repeatable."
    )
    args = parser.parse_args()
    try:
        evidence = generate(args.results_dir, args.dist, args.known_limitation)
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        print(f"release evidence: {error}", file=sys.stderr)
        return 1
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_markdown.write_text(_markdown(evidence), encoding="utf-8")
    print(f"Generated release evidence for {evidence['distribution']['path']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
