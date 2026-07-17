from __future__ import annotations

import argparse
from datetime import UTC, datetime
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
        evidence.append(
            {
                "id": gate_id,
                "status": "passed",
                "command": gate["command"],
                "artifacts": gate["artifacts"],
                "wheel_sha256": wheel_digest,
                "timestamp": timestamp,
            }
        )
    return evidence


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
        "| Gate | Status | Command | Evidence artifact |",
        "|---|---|---|---|",
    ]
    for gate in evidence["gates"]:
        command = gate["command"].replace("|", "\\|")
        artifacts = "<br>".join(gate["artifacts"])
        lines.append(f"| {gate['id']} | {gate['status']} | `{command}` | {artifacts} |")
    return "\n".join(lines) + "\n"


def generate(results_dir: Path, dist: Path) -> dict[str, Any]:
    wheel = _wheel(dist)
    wheel_digest = _sha256(wheel)
    evidence = {
        "version": _wheel_version(wheel),
        "source_commit": _source_commit(),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "distribution": {
            "path": str(wheel),
            "sha256": wheel_digest,
            "version": _wheel_version(wheel),
        },
        "gates": _validate_gates(_result_files(results_dir), wheel_digest),
    }
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate machine-verifiable release evidence from gate result files.")
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = generate(args.results_dir, args.dist)
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
