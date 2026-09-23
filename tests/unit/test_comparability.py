from __future__ import annotations

from retrieval_observatory.dashboard.api import _comparability_report
from retrieval_observatory.release.assessment import assess_evidence


def _manifest(content_hash=None, seed=None, git_commit=None, packages=None):
    return {
        "dataset": {
            "query_hash": content_hash,
            "corpus_hash": content_hash,
            "qrel_hash": content_hash,
        } if content_hash else {},
        "execution": {"seed": seed, "cache_results": False, "timeout_ms": 5000},
        "labeling": {"method": "gold", "judge": None, "model": None, "version": None},
        "git_commit": git_commit,
        "git_dirty": False,
        "models": [{"model": "bm25"}],
        "packages": packages or {},
    }


def test_identical_runs_are_comparable():
    m = _manifest(content_hash="abc", seed=1, git_commit="c1", packages={"numpy": "1.0"})
    report = _comparability_report([m, dict(m)])
    assert report["comparable"] is True
    assert report["outcome"] == "valid"
    assert report["differences"] == []


def test_different_dataset_content_blocks_comparability():
    report = _comparability_report([_manifest(content_hash="abc"), _manifest(content_hash="xyz")])
    assert report["comparable"] is False
    axes = {d["axis"] for d in report["differences"]}
    assert {"query_hash", "corpus_hash", "qrel_hash"} <= axes
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


def test_missing_required_metadata_is_invalid_not_equal():
    report = _comparability_report([{}, {}])
    assert report["outcome"] == "invalid"
    assert report["decision_allowed"] is False
    assert any(d["status"] == "unknown" for d in report["differences"])


def test_query_input_hash_participates_in_release_assessment():
    """``query_input_hash`` is a release-assessment invariant when both manifests carry it: a
    query text or metadata change under the same ids differs there while ``query_hash`` may
    not. The dashboard's ``_comparability_report`` delegates to ``comparison_validity``, whose
    required axes are unchanged, so the behaviour is asserted at the assessment level."""
    baseline = {**_manifest(content_hash="abc"), "evaluation": {"unit": "document", "k": 10}}
    baseline["dataset"]["query_input_hash"] = "inputs-a"
    candidate = {**_manifest(content_hash="abc"), "evaluation": {"unit": "document", "k": 10}}
    candidate["dataset"]["query_input_hash"] = "inputs-b"

    assessment = assess_evidence(None, baseline, candidate)

    aggregate = assessment.readiness["aggregate_or_slice_evaluation"]
    assert aggregate.status == "BLOCK"
    assert [finding.code for finding in aggregate.findings] == ["query_input_mismatch"]
    assert aggregate.findings[0].observed == ["inputs-a", "inputs-b"]
    comparison = next(item for item in assessment.provenance.invariants if item.field == "dataset.query_input_hash")
    assert (comparison.baseline, comparison.candidate, comparison.equal) == ("inputs-a", "inputs-b", False)
    assert comparison.classification == "evidence_invalid"
