from __future__ import annotations

import argparse
from email.parser import Parser
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import venv
import zipfile

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"release check: {message}", file=sys.stderr)
    raise SystemExit(1)


def package_version() -> str:
    raw = (ROOT / "pyproject.toml").read_bytes()
    if tomllib is not None:
        return str(tomllib.loads(raw.decode("utf-8"))["project"]["version"])
    match = re.search(rb'(?m)^version\s*=\s*"([^"]+)"', raw)
    if not match:
        fail("could not parse project.version from pyproject.toml")
    return match.group(1).decode("utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wheel_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_paths = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            fail(f"wheel has {len(metadata_paths)} METADATA files: {wheel}")
        version = Parser().parsestr(archive.read(metadata_paths[0]).decode("utf-8")).get("Version")
    if not version:
        fail(f"wheel METADATA has no Version: {wheel}")
    return version


def _wheel_runtime_version(wheel: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="retobs-release-version-") as directory:
        env_dir = Path(directory) / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        python = env_dir / "bin" / "python"
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)], check=True, capture_output=True, text=True)
        return subprocess.run(
            [str(python), "-c", "import importlib.metadata; print(importlib.metadata.version('retrieval-observatory'))"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()


def _unreleased_headings(changelog: str) -> set[str]:
    section = changelog.split("## [Unreleased]", 1)
    if len(section) != 2:
        fail("CHANGELOG.md has no [Unreleased] section")
    body = section[1].split("\n## ", 1)[0]
    return set(re.findall(r"^### (Added|Changed|Fixed|Removed)$", body, flags=re.MULTILINE))


def _check_assets(version: str, require_assets: bool) -> None:
    manifest_path = ROOT / "docs" / "assets" / "manifest.json"
    if require_assets and not manifest_path.exists():
        fail("docs/assets/manifest.json is missing; run scripts/generate_demo_assets.py")
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("retobs_version") != version:
        fail(f"demo assets are for {manifest.get('retobs_version')}, package is {version}")
    for name, expected_hash in manifest.get("files", {}).items():
        path = manifest_path.parent / name
        if not path.exists():
            fail(f"generated asset is missing: {name}")
        if _sha256(path) != expected_hash:
            fail(f"generated asset changed without manifest regeneration: {name}")


def _check_wheel_contents(wheel: Path) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    required = {
        "retrieval_observatory/dashboard/ui/dist/index.html",
        "retrieval_observatory/examples/evaluate_scifact.yaml",
    }
    missing = sorted(required - names)
    if missing:
        fail(f"wheel is missing required runtime assets: {', '.join(missing)}")
    removed = sorted(name for name in names if "quickstart" in name.lower() or "migration" in name.lower())
    if removed:
        fail(f"wheel contains removed material: {', '.join(removed)}")


def _check_evidence(path: Path, version: str, wheel: Path) -> None:
    spec = importlib.util.spec_from_file_location("release_evidence", ROOT / "scripts" / "generate_release_evidence.py")
    if spec is None or spec.loader is None:
        fail("could not load release evidence contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence = json.loads(path.read_text(encoding="utf-8"))
    if evidence.get("version") != version or evidence.get("distribution", {}).get("version") != version:
        fail("release evidence version does not match pyproject.toml")
    if evidence.get("distribution", {}).get("sha256") != _sha256(wheel):
        fail("release evidence references a different wheel digest")
    gates = {gate.get("id"): gate for gate in evidence.get("gates", [])}
    missing = sorted(module.REQUIRED_GATES - gates.keys())
    if missing:
        fail(f"release evidence is missing gates: {', '.join(missing)}")
    for gate_id in module.REQUIRED_GATES:
        gate = gates[gate_id]
        if gate.get("status") != "passed" or not gate.get("command") or not gate.get("artifacts"):
            fail(f"release evidence gate is incomplete: {gate_id}")
        if gate.get("wheel_sha256") != _sha256(wheel):
            fail(f"release evidence gate references a different wheel digest: {gate_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the source, wheel, generated assets, and generated release evidence agree.")
    parser.add_argument("--require-assets", action="store_true")
    parser.add_argument("--require-wheel", type=Path)
    parser.add_argument("--require-evidence", type=Path)
    args = parser.parse_args()
    if bool(args.require_wheel) != bool(args.require_evidence):
        fail("--require-wheel and --require-evidence must be used together")

    version = package_version()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    missing_headings = {"Added", "Changed", "Fixed", "Removed"} - _unreleased_headings(changelog)
    if missing_headings:
        fail(f"[Unreleased] is missing headings: {', '.join(sorted(missing_headings))}")

    for checker in ("check_public_surface.py", "check_public_vocabulary.py", "check_markdown_links.py"):
        subprocess.run([sys.executable, str(ROOT / "scripts" / checker)], check=True)
    _check_assets(version, args.require_assets)

    if args.require_wheel and args.require_evidence:
        wheel = args.require_wheel.resolve()
        evidence = args.require_evidence.resolve()
        if not wheel.is_file():
            fail(f"wheel does not exist: {wheel}")
        if not evidence.is_file():
            fail(f"release evidence does not exist: {evidence}")
        metadata_version = _wheel_version(wheel)
        runtime_version = _wheel_runtime_version(wheel)
        if {version, metadata_version, runtime_version} != {version}:
            fail(f"version mismatch: pyproject={version} wheel={metadata_version} runtime={runtime_version}")
        _check_wheel_contents(wheel)
        _check_evidence(evidence, version, wheel)
    print(f"Release checks passed for retobs {version}.")


if __name__ == "__main__":
    main()
