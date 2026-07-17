from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_publish_workflow_does_not_rebuild() -> None:
    raw = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
    assert "python -m build" not in raw
    assert "actions/checkout" not in raw
    assert "release-dist" in raw
    assert "release-evidence" in raw
    assert raw.count("verify_release_artifact.py") >= 2


def test_publish_workflow_has_ordered_environments() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert jobs["publish-testpypi"]["environment"] == "testpypi"
    assert jobs["publish-pypi"]["environment"] == "pypi"
    assert jobs["publish-pypi"]["needs"] == "publish-testpypi"
