from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import venv

import pytest


@pytest.fixture
def release_python(tmp_path: Path) -> Path:
    wheel_value = os.environ.get("RETOBS_RELEASE_WHEEL")
    if wheel_value is None:
        pytest.skip("RETOBS_RELEASE_WHEEL is required for installed-wheel release tests")
    wheel = Path(wheel_value).resolve()
    if not wheel.is_file():
        pytest.fail(f"RETOBS_RELEASE_WHEEL does not point to a wheel: {wheel}")
    venv_dir = tmp_path / "release-venv"
    venv.EnvBuilder(with_pip=True).create(venv_dir)
    python = venv_dir / "bin" / "python"
    subprocess.run([python, "-m", "pip", "install", str(wheel)], check=True, capture_output=True, text=True)
    return python


def test_release_python_imports_installed_distribution(tmp_path: Path, release_python: Path) -> None:
    result = subprocess.run(
        [release_python, "-c", "import json,retrieval_observatory as r; print(json.dumps({'file': r.__file__}))"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": str(release_python.parent)},
    )
    imported = Path(json.loads(result.stdout)["file"]).resolve()
    assert "site-packages" in imported.parts
    assert "retrieval-observatory" not in str(imported.parent.parent)
