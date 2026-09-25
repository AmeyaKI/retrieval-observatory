from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_release = _load("check_release")
evidence_generator = _load("generate_release_evidence")
VERSION = "9.9.9"


def test_changelog_must_carry_the_pyproject_version_heading() -> None:
    check_release._check_changelog_version("## [Unreleased]\n\n## [9.9.9] — 2026-09-24\n", VERSION)
    with pytest.raises(SystemExit):
        check_release._check_changelog_version("## [Unreleased]\n\n## [9.9.8] — 2026-09-24\n", VERSION)
    with pytest.raises(SystemExit):
        check_release._check_changelog_version("See [9.9.9] notes.\n", VERSION)


def _candidate(tmp_path: Path, smoke_checks: dict[str, dict]) -> tuple[Path, Path, Path]:
    dist, results = tmp_path / "dist", tmp_path / "results"
    dist.mkdir()
    results.mkdir()
    wheel = dist / f"retrieval_observatory-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"retrieval_observatory-{VERSION}.dist-info/METADATA", f"Metadata-Version: 2.1\nVersion: {VERSION}\n")
    sdist = dist / f"retrieval_observatory-{VERSION}.tar.gz"
    sdist.write_bytes(b"sdist")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    for gate in evidence_generator.REQUIRED_GATES:
        (results / f"{gate}.json").write_text(json.dumps({
            "id": gate, "status": "passed", "command": f"check {gate}", "artifacts": [f"{gate}.txt"],
            "wheel_sha256": digest, "timestamp": "2026-09-24T00:00:00Z",
            "environment": {"python": "3.12.4", "platform": "Linux-x86_64"},
        }), encoding="utf-8")
    (results / "wheel-smoke-3.12.json").write_text(json.dumps({
        "python": {"version": "3.12.4"}, "platform": "Linux-x86_64", "required_extras": ["dashboard", "mcp"], "checks": smoke_checks,
    }), encoding="utf-8")
    for fixture in evidence_generator.EXTERNAL_GATE_FIXTURES.values():
        (results / fixture).mkdir()
        (results / fixture / "capabilities.json").write_text(json.dumps({"lineage": {"status": "ready", "failures": []}}), encoding="utf-8")
    return dist, results, sdist


def test_generated_evidence_satisfies_the_release_check(tmp_path: Path) -> None:
    checks = {"import_origin": {"status": "passed"}, "serve_loopback": {"status": "skipped", "reason": "the 'dashboard' extra is not installed"}}
    dist, results, sdist = _candidate(tmp_path, checks)
    evidence = evidence_generator.generate(results, dist, ["Ubuntu only."])
    assert evidence["artifacts"] == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (sdist, next(dist.glob("*.whl")))}
    assert evidence["skipped_checks"] == [{"source": "wheel-smoke-3.12.json", "check": "serve_loopback", "reason": checks["serve_loopback"]["reason"]}]
    assert evidence["wheel_smoke"][0]["summary"] == {"passed": 1, "failed": 0, "skipped": 1}
    assert set(evidence["fixture_capabilities"]) == set(evidence_generator.EXTERNAL_GATE_FIXTURES.values())
    assert all(gate["environment"]["python"] == "3.12.4" for gate in evidence["gates"])
    path = tmp_path / "release-evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    check_release._check_evidence(path, VERSION, next(dist.glob("*.whl")), sdist)

    evidence["artifacts"][sdist.name] = "0" * 64
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(SystemExit):
        check_release._check_evidence(path, VERSION, next(dist.glob("*.whl")), sdist)


@pytest.mark.parametrize(
    "checks",
    [
        {"import_origin": {"status": "failed", "error": "imported from the checkout"}},
        {"serve_loopback": {"status": "skipped"}},
    ],
)
def test_generator_rejects_failed_or_unexplained_smoke_checks(tmp_path: Path, checks: dict[str, dict]) -> None:
    dist, results, _ = _candidate(tmp_path, checks)
    with pytest.raises(ValueError):
        evidence_generator.generate(results, dist)


def test_release_check_rejects_evidence_without_fixture_capabilities(tmp_path: Path) -> None:
    dist, results, sdist = _candidate(tmp_path, {"import_origin": {"status": "passed"}})
    evidence = evidence_generator.generate(results, dist, [])
    evidence["fixture_capabilities"].pop("langchain_retriever")
    path = tmp_path / "release-evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(SystemExit):
        check_release._check_evidence(path, VERSION, next(dist.glob("*.whl")), sdist)
