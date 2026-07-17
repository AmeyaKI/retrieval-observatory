from pathlib import Path

import retrieval_observatory
import pytest


def test_public_import_matches_the_supported_sdk() -> None:
    assert retrieval_observatory.compare is not None
    assert retrieval_observatory.evaluate is not None
    assert not hasattr(retrieval_observatory, "benchmark")
    assert not hasattr(retrieval_observatory, "run_from_config")


def test_bundled_examples_exist() -> None:
    package_dir = Path(retrieval_observatory.__file__).resolve().parent
    assert (package_dir / "examples" / "beir_demo.yaml").is_file()
    assert (package_dir / "examples" / "evaluate_scifact.yaml").is_file()


def test_ui_dist_present_when_built() -> None:
    package_dir = Path(retrieval_observatory.__file__).resolve().parent
    ui_index = package_dir / "dashboard" / "ui" / "dist" / "index.html"
    if not ui_index.is_file():
        pytest.skip("dashboard UI not built (run make dashboard-build before release)")
    assert ui_index.stat().st_size > 0
