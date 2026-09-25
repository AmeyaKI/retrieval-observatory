from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "external_projects"))
from conftest import FIXTURES  # noqa: E402


def test_external_fixtures_run_against_installed_wheel(tmp_path: Path) -> None:
    wheel = os.environ.get("RETOBS_RELEASE_WHEEL")
    if wheel is None:
        pytest.skip("RETOBS_RELEASE_WHEEL is required for installed-wheel release tests")
    wheel_path = Path(wheel).resolve()
    if not wheel_path.is_file():
        pytest.fail(f"RETOBS_RELEASE_WHEEL does not point to a wheel: {wheel_path}")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "smoke_external_project.py"),
            "--wheel",
            str(wheel_path),
            "--fixture",
            "all",
            "--artifacts",
            str(tmp_path / "external-fixtures"),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
    )
    # With a wheel named, a failing fixture fails this test; only an unset RETOBS_RELEASE_WHEEL skips.
    assert result.returncode == 0, f"external fixture smoke failed:\n{result.stdout[-3000:]}\n{result.stderr[-5000:]}"
    assert result.stdout.count(": PASS") == len(FIXTURES), result.stdout
