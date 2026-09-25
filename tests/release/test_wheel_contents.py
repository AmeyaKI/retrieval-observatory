from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import tarfile
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("check_release", ROOT / "scripts" / "check_release.py")
assert _spec is not None and _spec.loader is not None
check_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_release)

INDEX_HTML = '<html><head><script type="module" src="/assets/index-abc.js"></script></head></html>'


@pytest.fixture
def release_wheel() -> Path:
    value = os.environ.get("RETOBS_RELEASE_WHEEL")
    if value is None:
        pytest.skip("RETOBS_RELEASE_WHEEL is required for installed-wheel release tests")
    wheel = Path(value).resolve()
    if not wheel.is_file():
        pytest.fail(f"RETOBS_RELEASE_WHEEL does not point to a wheel: {wheel}")
    return wheel


@pytest.fixture
def release_sdist() -> Path:
    value = os.environ.get("RETOBS_RELEASE_SDIST")
    if value is None:
        pytest.skip("RETOBS_RELEASE_SDIST is required for sdist release tests")
    sdist = Path(value).resolve()
    if not sdist.is_file():
        pytest.fail(f"RETOBS_RELEASE_SDIST does not point to an sdist: {sdist}")
    return sdist


def _wheel(path: Path, extra: dict[str, str] | None = None, drop: str | None = None) -> Path:
    files = {name: "" for name in check_release.WHEEL_REQUIRED}
    files["retrieval_observatory/dashboard/ui/dist/index.html"] = INDEX_HTML
    files["retrieval_observatory/dashboard/ui/dist/assets/index-abc.js"] = ""
    files.update(extra or {})
    files.pop(drop or "", None)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def _sdist(path: Path, files: dict[str, str]) -> Path:
    base = {"PKG-INFO": "", "pyproject.toml": "", "retrieval_observatory/__init__.py": "", **files}
    with tarfile.open(path, "w:gz") as archive:
        for name, content in base.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(f"retrieval_observatory-0.0.0/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


def test_release_wheel_contains_runtime_assets_and_no_retired_or_local_material(release_wheel: Path) -> None:
    check_release._check_wheel_contents(release_wheel)
    with zipfile.ZipFile(release_wheel) as archive:
        names = set(archive.namelist())
    assert check_release.WHEEL_REQUIRED <= names
    assert not any(name.startswith("retrieval_observatory/experimental/") for name in names)
    assert not any(name.endswith(".pyc") for name in names)


def test_release_sdist_carries_no_local_only_material(release_sdist: Path) -> None:
    check_release._check_sdist(release_sdist)


def test_wheel_check_accepts_a_complete_wheel(tmp_path: Path) -> None:
    check_release._check_wheel_contents(_wheel(tmp_path / "ok.whl"))


@pytest.mark.parametrize(
    "drop",
    [
        "retrieval_observatory/examples/golden_fixture.py",
        "retrieval_observatory/examples/release-policy-golden-v3.yaml",
        "retrieval_observatory/examples/agent_integration/SKILL.md",
        "retrieval_observatory/dashboard/ui/dist/assets/index-abc.js",
    ],
)
def test_wheel_check_rejects_a_missing_runtime_file(tmp_path: Path, drop: str) -> None:
    with pytest.raises(SystemExit):
        check_release._check_wheel_contents(_wheel(tmp_path / "missing.whl", drop=drop))


@pytest.mark.parametrize(
    "name",
    [
        "retrieval_observatory/experimental/__init__.py",
        "retrieval_observatory/tracing/replay.py",
        "retrieval_observatory/tracing/monitor/drift.py",
        "retrieval_observatory/metrics/pareto.py",
        "retrieval_observatory/dashboard/ui/src/App.tsx",
        "retrieval_observatory/sdk/__pycache__/api.cpython-312.pyc",
        "retrieval_observatory/.retobs/results.db",
        "retrieval_observatory/docs/migrating-to-focused-retobs.md",
    ],
)
def test_wheel_check_rejects_retired_or_local_material(tmp_path: Path, name: str) -> None:
    with pytest.raises(SystemExit):
        check_release._check_wheel_contents(_wheel(tmp_path / "extra.whl", extra={name: ""}))


def test_sdist_check_accepts_package_sources(tmp_path: Path) -> None:
    check_release._check_sdist(_sdist(tmp_path / "ok.tar.gz", {"README.md": "# retobs", "LICENSE": "MIT"}))


@pytest.mark.parametrize(
    "files",
    [
        {"RETOBS_MASTER_PLAN.md": ""},
        {"docs/rebuild/RETIREMENT_INVENTORY.md": ""},
        {"HANDOFF.md": ""},
        {"STUDY_BRIEF.md": ""},
        {"SESSION_FLAGSHIP_DEMO.jsonl": ""},
        {"NEXT_SESSION.md": ""},
        {".retobs/results.db": ""},
        {".claude/settings.json": ""},
        {"retrieval_observatory/.claude/notes.txt": ""},
        {"Screenshot 2026-07-17.png": ""},
        {"retrieval_observatory/config/defaults.py": "ROOT = '/Users/someone/project'\n"},
    ],
)
def test_sdist_check_rejects_local_only_material(tmp_path: Path, files: dict[str, str]) -> None:
    with pytest.raises(SystemExit):
        check_release._check_sdist(_sdist(tmp_path / "bad.tar.gz", files))
