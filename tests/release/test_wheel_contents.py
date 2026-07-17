from __future__ import annotations

import os
from pathlib import Path
import zipfile

import pytest


@pytest.fixture
def release_wheel() -> Path:
    value = os.environ.get("RETOBS_RELEASE_WHEEL")
    if value is None:
        pytest.skip("RETOBS_RELEASE_WHEEL is required for installed-wheel release tests")
    wheel = Path(value).resolve()
    if not wheel.is_file():
        pytest.fail(f"RETOBS_RELEASE_WHEEL does not point to a wheel: {wheel}")
    return wheel


def test_release_wheel_contains_required_runtime_assets(release_wheel: Path) -> None:
    with zipfile.ZipFile(release_wheel) as archive:
        names = set(archive.namelist())
    required_suffixes = {
        "retrieval_observatory/dashboard/ui/dist/index.html",
        "retrieval_observatory/examples/evaluate_scifact.yaml",
    }
    assert required_suffixes <= names
    assert not any("quickstart" in name.lower() for name in names)
    assert not any("migration" in name.lower() for name in names)
