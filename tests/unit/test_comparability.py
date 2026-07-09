from __future__ import annotations

from retrieval_observatory.dashboard.api import _comparability_report


def _manifest(content_hash=None, seed=None, git_commit=None, packages=None):
    return {
        "dataset": {"content_hash": content_hash} if content_hash else {},
        "seed": seed,
        "git_commit": git_commit,
        "packages": packages or {},
    }


def test_identical_runs_are_comparable():
    m = _manifest(content_hash="abc", seed=1, git_commit="c1", packages={"numpy": "1.0"})
    report = _comparability_report([m, dict(m)])
    assert report["comparable"] is True
    assert report["differences"] == []


def test_different_dataset_content_blocks_comparability():
    report = _comparability_report([_manifest(content_hash="abc"), _manifest(content_hash="xyz")])
    assert report["comparable"] is False
    axes = {d["axis"] for d in report["differences"]}
    assert "dataset_content" in axes
    assert any(d["severity"] == "high" for d in report["differences"])


def test_different_seed_warns_without_blocking():
    report = _comparability_report([
        _manifest(content_hash="abc", seed=1),
        _manifest(content_hash="abc", seed=2),
    ])
    assert report["comparable"] is True
    assert any(d["axis"] == "seed" for d in report["differences"])


def test_git_and_package_differences_flagged():
    report = _comparability_report([
        _manifest(content_hash="abc", git_commit="c1", packages={"numpy": "1.0"}),
        _manifest(content_hash="abc", git_commit="c2", packages={"numpy": "2.0"}),
    ])
    axes = {d["axis"] for d in report["differences"]}
    assert {"git_commit", "package_versions"} <= axes
