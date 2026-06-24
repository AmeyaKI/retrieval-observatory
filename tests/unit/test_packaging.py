from pathlib import Path

import pytest

from retobs import EXAMPLES_DIR, PACKAGE_DIR


def test_public_retobs_import():
    import retobs

    assert retobs.benchmark is not None
    assert (retobs.EXAMPLES_DIR / "quickstart_scifact.yaml").is_file()


def test_bundled_examples_exist():
    assert (EXAMPLES_DIR / "quickstart_scifact.yaml").is_file()
    assert (EXAMPLES_DIR / "beir_demo.yaml").is_file()


def test_ui_dist_present_when_built():
    ui_index = PACKAGE_DIR / "dashboard" / "ui" / "dist" / "index.html"
    if not ui_index.is_file():
        pytest.skip("dashboard UI not built (run make dashboard-build before release)")
    assert ui_index.stat().st_size > 0
