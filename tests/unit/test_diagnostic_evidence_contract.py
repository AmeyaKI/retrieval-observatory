from __future__ import annotations

from retrieval_observatory.metrics.diagnostics import build_query_diagnostics
from retrieval_observatory.types import Document, PipelineResult, StageSnapshot


def _result(doc_ids: list[str]) -> PipelineResult:
    return PipelineResult(
        query_id="q",
        pipeline_id="bm25",
        status="OK",
        total_latency_ms=1.0,
        snapshots=[
            StageSnapshot(
                stage_index=0,
                stage_id="bm25",
                latency_ms=1.0,
                documents=[
                    Document(id=doc_id, text="", score=1.0, rank=rank)
                    for rank, doc_id in enumerate(doc_ids, start=1)
                ],
            )
        ],
    )


def test_valid_missed_qrel_is_not_labeled_as_identity_mismatch() -> None:
    row = build_query_diagnostics(
        "run",
        [_result(["other"])],
        {"q": {"gold": 1}},
        corpus_doc_ids={"gold", "other"},
    )[0]

    assert "qrel_not_in_corpus" not in row["failure_labels"]
    assert "not_retrieved_by_any_pipeline" in row["failure_labels"]
    evidence = next(item for item in row["diagnostic_evidence"] if item["label"] == "not_retrieved_by_any_pipeline")
    assert evidence["evidence_class"] == "measured"


def test_absent_qrel_id_is_measured_against_corpus() -> None:
    row = build_query_diagnostics(
        "run",
        [_result(["other"])],
        {"q": {"missing-gold": 1}},
        corpus_doc_ids={"other"},
    )[0]

    assert "qrel_not_in_corpus" in row["failure_labels"]
    assert "candidate_miss" not in row["failure_labels"]
    evidence = next(item for item in row["diagnostic_evidence"] if item["label"] == "qrel_not_in_corpus")
    assert evidence["doc_ids"] == ["missing-gold"]
    assert evidence["method"] == "qrel_corpus_membership_v1"


def test_unknown_corpus_identity_is_explicitly_unavailable() -> None:
    row = build_query_diagnostics("run", [_result(["other"])], {"q": {"gold": 1}})[0]

    assert "corpus_identity_unknown" in row["failure_labels"]
    evidence = next(item for item in row["diagnostic_evidence"] if item["label"] == "corpus_identity_unknown")
    assert evidence["evidence_class"] == "unavailable"
    assert evidence["threshold"] is None
