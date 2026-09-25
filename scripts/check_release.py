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
import tarfile
import tempfile
import venv
import zipfile

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "retrieval_observatory/"
#: Wheel files `retobs demo`, `retobs serve`, and the agent runbook read at runtime. The package
#: loads nothing from the repository's `contracts/` directory, so no contract file ships.
WHEEL_REQUIRED = {
    "retrieval_observatory/dashboard/ui/dist/index.html",
    "retrieval_observatory/examples/__init__.py",
    "retrieval_observatory/examples/golden_fixture.py",
    "retrieval_observatory/examples/release-policy-golden-v3.yaml",
    "retrieval_observatory/examples/evaluate_scifact.yaml",
    "retrieval_observatory/examples/agent_integration/SKILL.md",
    "retrieval_observatory/examples/agent_integration/references/plan-review.md",
    "retrieval_observatory/examples/agent_integration/references/retobs_adapter_example.py",
}
#: Packages and modules retired by the focused rebuild (T19/T20); none may ship again.
WHEEL_RETIRED_PREFIXES = (
    "retrieval_observatory/experimental/",
    "retrieval_observatory/forge/",
    "retrieval_observatory/advisor/",
    "retrieval_observatory/classifier/",
    "retrieval_observatory/diagram/",
    "retrieval_observatory/tracing/monitor/",
    "retrieval_observatory/dashboard/ui/src/",
    "retrieval_observatory/dashboard/ui/node_modules/",
)
WHEEL_RETIRED_FILES = {
    "retrieval_observatory/tracing/replay.py",
    "retrieval_observatory/tracing/attribution.py",
    "retrieval_observatory/tracing/enrich.py",
    "retrieval_observatory/metrics/pareto.py",
    "retrieval_observatory/analysis/cohorts.py",
    "retrieval_observatory/analysis/corpus_health.py",
    "retrieval_observatory/analysis/loss_attribution.py",
    "retrieval_observatory/analysis/service.py",
}
#: Local-only material (the "never publish" block of .gitignore, plus local data and caches).
LOCAL_ONLY = re.compile(
    r"(^|/)(RETOBS_MASTER_PLAN[^/]*|HANDOFF[^/]*|STUDY_BRIEF[^/]*|[A-Z_]*SESSION[^/]*|SHIP_PLAN[^/]*|BREAKDOWN\.md"
    r"|CLOUD_DEPLOY_BRIEF[^/]*|TODO|\.env|\.DS_Store|export_session\.py|[^/]*\.db|[^/]*\.pyc|[^/]*\.bak-[^/]*)$"
    r"|(^|/)(\.retobs|\.claude|\.prompts|\.archive|__pycache__|node_modules|artifacts)/"
    r"|(^|/)docs/(rebuild|superpowers|verification)/|(^|/)results/study/"
)
#: Top-level entries a setuptools sdist of this project may contain.
SDIST_TOP_LEVEL = {
    "PKG-INFO", "pyproject.toml", "setup.cfg", "MANIFEST.in", "README.md", "LICENSE",
    "retrieval_observatory", "retrieval_observatory.egg-info",
}


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


def _check_changelog_version(changelog: str, version: str) -> None:
    if not re.search(rf"^## \[{re.escape(version)}\]", changelog, flags=re.MULTILINE):
        fail(f"CHANGELOG.md has no '## [{version}]' heading for the pyproject version")


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
        index = PACKAGE + "dashboard/ui/dist/index.html"
        html = archive.read(index).decode("utf-8") if index in names else ""
    assets = {PACKAGE + "dashboard/ui/dist/" + name for name in re.findall(r"""(?:src|href)=["']/?(assets/[^"']+)["']""", html)}
    missing = sorted((WHEEL_REQUIRED | assets) - names)
    if missing:
        fail(f"wheel is missing required runtime assets: {', '.join(missing)}")
    if not assets:
        fail("wheel dashboard index.html references no bundled assets")
    removed = sorted(
        name for name in names
        if name.startswith(WHEEL_RETIRED_PREFIXES) or name in WHEEL_RETIRED_FILES or LOCAL_ONLY.search(name)
        # Docs are not package data; the only markdown the wheel ships is the agent runbook.
        or (name.endswith(".md") and not name.startswith(PACKAGE + "examples/agent_integration/"))
    )
    if removed:
        fail(f"wheel contains retired or local-only material: {', '.join(removed)}")


def _check_sdist(sdist: Path) -> None:
    offending: list[str] = []
    with tarfile.open(sdist, "r:gz") as archive:
        for member in archive.getmembers():
            relative = member.name.split("/", 1)[1] if "/" in member.name else ""
            if not relative:
                continue
            if relative.split("/", 1)[0] not in SDIST_TOP_LEVEL or LOCAL_ONLY.search(relative):
                offending.append(relative)
            elif member.isfile():
                handle = archive.extractfile(member)
                if handle is not None and b"/Users/" in handle.read():
                    offending.append(f"{relative} (contains a local /Users/ path)")
    if offending:
        fail(f"sdist contains local-only material: {', '.join(sorted(offending))}")


def _check_evidence(path: Path, version: str, wheel: Path, sdist: Path | None = None) -> None:
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
    if not re.fullmatch(r"[0-9a-f]{40}", str(evidence.get("source_commit"))):
        fail(f"release evidence has no source commit: {evidence.get('source_commit')!r}")
    hashes = evidence.get("artifacts", {})
    for artifact in (wheel, sdist):
        if artifact is not None and hashes.get(artifact.name) != _sha256(artifact):
            fail(f"release evidence records a different or no SHA-256 for {artifact.name}")
    smokes = evidence.get("wheel_smoke", [])
    if not smokes or any(smoke.get("summary", {}).get("failed") != 0 for smoke in smokes):
        fail("release evidence has no wheel-smoke results or one has failed checks")
    if any(not skipped.get("reason") for skipped in evidence.get("skipped_checks", [])):
        fail("release evidence has a skipped check without a reason")
    fixtures = {module.EXTERNAL_GATE_FIXTURES[gate] for gate in module.REQUIRED_GATES & module.EXTERNAL_GATE_FIXTURES.keys()}
    if not fixtures <= evidence.get("fixture_capabilities", {}).keys():
        fail(f"release evidence lacks fixture capability results for: {', '.join(sorted(fixtures - evidence.get('fixture_capabilities', {}).keys()))}")
    limitations = evidence.get("known_limitations")
    if not isinstance(limitations, list) or not all(isinstance(item, str) and item.strip() for item in limitations):
        fail("release evidence has no known-limitations list")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the source, wheel, generated assets, and generated release evidence agree.")
    parser.add_argument("--require-assets", action="store_true")
    parser.add_argument("--require-wheel", type=Path)
    parser.add_argument("--require-evidence", type=Path)
    parser.add_argument("--require-sdist", type=Path, help="Verify the sdist carries no local-only material (and its digest, with evidence).")
    args = parser.parse_args()
    if bool(args.require_wheel) != bool(args.require_evidence):
        fail("--require-wheel and --require-evidence must be used together")

    version = package_version()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    missing_headings = {"Added", "Changed", "Fixed", "Removed"} - _unreleased_headings(changelog)
    if missing_headings:
        fail(f"[Unreleased] is missing headings: {', '.join(sorted(missing_headings))}")
    _check_changelog_version(changelog, version)

    for checker in ("check_public_surface.py", "check_public_vocabulary.py", "check_markdown_links.py"):
        subprocess.run([sys.executable, str(ROOT / "scripts" / checker)], check=True)
    _check_assets(version, args.require_assets)

    sdist = args.require_sdist.resolve() if args.require_sdist else None
    if sdist is not None:
        if not sdist.is_file():
            fail(f"sdist does not exist: {sdist}")
        _check_sdist(sdist)

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
        _check_evidence(evidence, version, wheel, sdist)
    print(f"Release checks passed for retobs {version}.")


if __name__ == "__main__":
    main()
