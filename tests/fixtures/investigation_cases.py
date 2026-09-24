"""Hand-authored expected journey tables for the golden investigation fixture.

The executable pipeline, judgments, and chunk map live in
``retrieval_observatory.examples.golden_fixture`` (it also backs ``retobs demo``) and are
re-exported here. The ``EXPECTED_*`` tables below were written by hand from the scenario, never
computed from any journey or lineage code, so later journey projections can be tested against them.

Expected-table conventions:
    * ``loss_boundary`` for an excluded document is the op_id of the recorded removal that
      took it off the path to ``select``; ``"select"`` when it reached the final output but
      ranked below k; ``"not_observed"`` when no trace contains it; ``"unknown"`` when the
      exit is not recorded; ``None`` when included.
    * ``capture_state`` is per document: ``"partial"`` when any of its chunks crosses a
      boundary whose capture was truncated in that query.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from retrieval_observatory.examples.golden_fixture import (  # noqa: F401 (re-exported builders)
    CORPUS,
    EVALUATION_SPEC,
    FixtureRun,
    chunk_map,
    judgment_records,
    queries,
    run_fixture,
    run_pipeline,
)

# ---------------------------------------------------------------------------
# Hand-authored expected journey table
# ---------------------------------------------------------------------------

EventKind = Literal["introduced", "retained", "removed", "demoted", "promoted", "recovered", "transformed", "unknown"]
ReasonEvidence = Literal["recorded", "inferred", "unavailable"]


@dataclass(frozen=True)
class ExpectedEvent:
    op_id: str
    operator: str
    kind: EventKind
    branch: str | None
    reason: str | None
    reason_evidence: ReasonEvidence
    boundary_complete: bool
    input_rank: int | None
    output_rank: int | None


@dataclass(frozen=True)
class ExpectedChunkJourney:
    query_id: str
    namespace: str
    chunk_id: str
    document_id: str
    events: tuple[ExpectedEvent, ...]
    in_final_output: bool
    final_rank: int | None


@dataclass(frozen=True)
class ExpectedDocumentOutcome:
    query_id: str
    namespace: str
    document_id: str
    judgment: Literal["relevant", "nonrelevant", "unjudged"]
    grade: int | None
    final_membership: Literal["included", "excluded"]
    in_final_output: bool
    final_rank: int | None
    confusion: Literal["TP", "FP", "FN", "TN", "unknown"]
    capture_state: Literal["complete", "partial"]
    loss_boundary: str | None


_BRANCH = {"dense": "dense", "rerank@dense": "dense", "lexical": "lexical", "recency_filter": "lexical", "rerank@lexical": "lexical"}


def _ev(
    op_id: str,
    kind: EventKind,
    input_rank: int | None = None,
    output_rank: int | None = None,
    *,
    reason: str | None = None,
    evidence: ReasonEvidence = "recorded",
    complete: bool = True,
) -> ExpectedEvent:
    operator = "rerank" if op_id.startswith("rerank@") else op_id
    return ExpectedEvent(op_id, operator, kind, _BRANCH.get(op_id), reason, evidence, complete, input_rank, output_rank)


def _journey(query_id: str, namespace: str, chunk_id: str, events: Sequence[ExpectedEvent], final_rank: int | None) -> ExpectedChunkJourney:
    document_id = CORPUS[(namespace, chunk_id)]["document_id"]
    return ExpectedChunkJourney(query_id, namespace, chunk_id, document_id, tuple(events), final_rank is not None, final_rank)


EXPECTED_CHUNK_JOURNEYS: tuple[ExpectedChunkJourney, ...] = (
    # ---- q-refund: expand skipped; select reads from expand_gate -------------------------
    _journey("q-refund", "kb", "doc-policy/chunk-1", (
        _ev("dense", "introduced", None, 1, reason="retrieved"),
        _ev("lexical", "introduced", None, 1, reason="retrieved"),
        _ev("recency_filter", "removed", 1, None, reason="min_score"),
        _ev("rerank@dense", "retained", 1, 1),
        _ev("fuse", "demoted", 1, 2),
        _ev("expand_gate", "retained", 2, 2),
        _ev("select", "retained", 2, 2),
    ), 2),
    _journey("q-refund", "kb", "doc-policy/chunk-2", (
        _ev("lexical", "introduced", None, 5, reason="retrieved"),
        _ev("recency_filter", "promoted", 5, 3),
        _ev("rerank@lexical", "promoted", 3, 2),
        _ev("fuse", "demoted", 2, 3),
        _ev("expand_gate", "retained", 3, 3),
        _ev("select", "removed", 3, None, reason="duplicate_document"),
    ), None),
    _journey("q-refund", "kb", "doc-faq/chunk-1", (
        _ev("dense", "introduced", None, 3, reason="retrieved"),
        _ev("lexical", "introduced", None, 3, reason="retrieved"),
        _ev("recency_filter", "promoted", 3, 1),
        _ev("rerank@dense", "promoted", 3, 2),
        _ev("rerank@lexical", "retained", 1, 1),
        _ev("fuse", "retained", 1, 1, reason="deduplicated"),
        _ev("expand_gate", "retained", 1, 1),
        _ev("select", "retained", 1, 1),
    ), 1),
    _journey("q-refund", "kb", "doc-guide/chunk-1", (
        _ev("dense", "introduced", None, 2, reason="retrieved"),
        _ev("rerank@dense", "demoted", 2, 3),
        _ev("fuse", "demoted", 3, 4),
        _ev("expand_gate", "retained", 4, 4),
        _ev("select", "promoted", 4, 3),
    ), 3),
    _journey("q-refund", "kb", "doc-legal/chunk-1", (
        _ev("lexical", "introduced", None, 4, reason="retrieved"),
        _ev("recency_filter", "promoted", 4, 2),
        _ev("rerank@lexical", "demoted", 2, 3),
        _ev("fuse", "demoted", 3, 5),
        _ev("expand_gate", "retained", 5, 5),
        _ev("select", "promoted", 5, 4),
    ), 4),
    _journey("q-refund", "kb", "doc-news/chunk-1", (
        _ev("lexical", "introduced", None, 2, reason="retrieved"),
        _ev("recency_filter", "removed", 2, None, reason="stale_year"),
    ), None),
    # ---- q-outage: rerank@lexical output capture truncated to 1 --------------------------
    _journey("q-outage", "kb", "doc-faq/chunk-1", (
        _ev("dense", "introduced", None, 1, reason="retrieved"),
        _ev("lexical", "introduced", None, 2, reason="retrieved"),
        _ev("recency_filter", "retained", 2, 2),
        _ev("rerank@dense", "retained", 1, 1),
        _ev("rerank@lexical", "unknown", 2, None, evidence="unavailable", complete=False),
        _ev("fuse", "retained", 1, 1, reason="deduplicated"),
        _ev("expand_gate", "retained", 1, 1),
        _ev("select", "retained", 1, 1),
    ), 1),
    _journey("q-outage", "kb", "doc-news/chunk-1", (
        _ev("dense", "introduced", None, 2, reason="retrieved"),
        _ev("lexical", "introduced", None, 3, reason="retrieved"),
        _ev("recency_filter", "removed", 3, None, reason="stale_year"),
        _ev("rerank@dense", "retained", 2, 2),
        _ev("fuse", "demoted", 2, 3),
        _ev("expand_gate", "retained", 3, 3),
        _ev("select", "retained", 3, 3),
    ), 3),
    _journey("q-outage", "kb", "doc-guide/chunk-1", (
        _ev("lexical", "introduced", None, 1, reason="retrieved"),
        _ev("recency_filter", "retained", 1, 1),
        _ev("rerank@lexical", "retained", 1, 1, complete=False),
        _ev("fuse", "demoted", 1, 2),
        _ev("expand_gate", "retained", 2, 2),
        _ev("select", "retained", 2, 2),
    ), 2),
    # ---- q-invoice: expand fires; select reads from expand -------------------------------
    _journey("q-invoice", "tickets", "doc-1/chunk-1", (
        _ev("dense", "introduced", None, 3, reason="retrieved"),
        _ev("lexical", "introduced", None, 2, reason="retrieved"),
        _ev("recency_filter", "promoted", 2, 1),
        _ev("rerank@dense", "promoted", 3, 1),
        _ev("rerank@lexical", "retained", 1, 1),
        _ev("fuse", "retained", 1, 1, reason="deduplicated"),
        _ev("expand_gate", "retained", 1, 1),
        _ev("expand", "retained", 1, 1),
        _ev("select", "retained", 1, 1),
    ), 1),
    _journey("q-invoice", "kb", "doc-guide/chunk-1", (
        _ev("dense", "introduced", None, 1, reason="retrieved"),
        _ev("rerank@dense", "demoted", 1, 2),
        _ev("fuse", "retained", 2, 2),
        _ev("expand_gate", "retained", 2, 2),
        _ev("expand", "retained", 2, 2),
        _ev("select", "retained", 2, 2),
    ), 2),
    _journey("q-invoice", "kb", "doc-1/chunk-1", (
        _ev("dense", "introduced", None, 2, reason="retrieved"),
        _ev("rerank@dense", "demoted", 2, 3),
        _ev("fuse", "retained", 3, 3),
        _ev("expand_gate", "retained", 3, 3),
        _ev("expand", "retained", 3, 3),
        _ev("select", "retained", 3, 3),
    ), 3),
    _journey("q-invoice", "kb", "doc-guide/chunk-2", (
        _ev("lexical", "introduced", None, 1, reason="retrieved"),
        _ev("recency_filter", "removed", 1, None, reason="min_score"),
        _ev("expand", "recovered", None, 4, reason="expanded"),
        _ev("select", "removed", 4, None, reason="duplicate_document"),
    ), None),
)


def _outcome(
    query_id: str,
    namespace: str,
    document_id: str,
    judgment: Literal["relevant", "nonrelevant", "unjudged"],
    grade: int | None,
    final_rank: int | None,
    confusion: Literal["TP", "FP", "FN", "TN", "unknown"],
    *,
    capture_state: Literal["complete", "partial"] = "complete",
    loss_boundary: str | None = None,
) -> ExpectedDocumentOutcome:
    included = final_rank is not None and final_rank <= EVALUATION_SPEC["k"]
    return ExpectedDocumentOutcome(
        query_id, namespace, document_id, judgment, grade,
        "included" if included else "excluded", final_rank is not None, final_rank, confusion, capture_state, loss_boundary,
    )


EXPECTED_DOCUMENT_OUTCOMES: tuple[ExpectedDocumentOutcome, ...] = (
    _outcome("q-refund", "kb", "doc-faq", "relevant", 1, 1, "TP"),
    _outcome("q-refund", "kb", "doc-policy", "relevant", 2, 2, "TP"),
    _outcome("q-refund", "kb", "doc-guide", "unjudged", None, 3, "unknown"),
    _outcome("q-refund", "kb", "doc-legal", "nonrelevant", 0, 4, "TN", loss_boundary="select"),
    _outcome("q-outage", "kb", "doc-faq", "nonrelevant", 0, 1, "FP", capture_state="partial"),
    _outcome("q-outage", "kb", "doc-guide", "relevant", 1, 2, "TP", capture_state="partial"),
    _outcome("q-outage", "kb", "doc-news", "unjudged", None, 3, "unknown"),
    _outcome("q-invoice", "tickets", "doc-1", "relevant", 2, 1, "TP"),
    _outcome("q-invoice", "kb", "doc-guide", "relevant", 1, 2, "TP"),
    _outcome("q-invoice", "kb", "doc-1", "nonrelevant", 0, 3, "FP"),
    _outcome("q-invoice", "kb", "doc-archive", "relevant", 1, None, "FN", loss_boundary="not_observed"),
)


def _counts(served: int, skipped: int, received: int, removals: int, introduced: int, partial: int) -> dict[str, int]:
    return {
        "queries_served": served,
        "queries_skipped": skipped,
        "candidates_received": received,
        "removal_events": removals,
        "introduced": introduced,
        "partial_boundaries": partial,
    }


# Counted by hand over the three queries (received = q-refund + q-outage + q-invoice).
EXPECTED_STAGE_COUNTS: dict[str, dict[str, int]] = {
    "dense": _counts(3, 0, 0, 0, 3 + 2 + 3, 0),
    "lexical": _counts(3, 0, 0, 0, 5 + 3 + 2, 0),
    "recency_filter": _counts(3, 0, 5 + 3 + 2, 2 + 1 + 1, 0, 0),
    "rerank@dense": _counts(3, 0, 3 + 2 + 3, 0, 0, 0),
    "rerank@lexical": _counts(3, 0, 3 + 2 + 1, 0, 0, 1),
    "fuse": _counts(3, 0, (3 + 3) + (2 + 2) + (3 + 1), 0, 0, 0),
    "expand_gate": _counts(3, 0, 5 + 3 + 3, 0, 0, 0),
    "expand": _counts(1, 2, 3, 0, 1, 0),
    "select": _counts(3, 0, 5 + 3 + 4, 1 + 0 + 1, 0, 0),
}

SCENARIO_COVERAGE: dict[str, tuple[tuple[str, str, str], ...]] = {
    "branch_loss_with_survival": (("q-refund", "kb", "doc-policy/chunk-1"), ("q-outage", "kb", "doc-news/chunk-1")),
    "repeated_invocation": (("q-refund", "kb", "doc-faq/chunk-1"), ("q-invoice", "tickets", "doc-1/chunk-1")),
    "deduplication": (("q-refund", "kb", "doc-faq/chunk-1"), ("q-outage", "kb", "doc-faq/chunk-1"), ("q-invoice", "tickets", "doc-1/chunk-1")),
    "recovery": (("q-invoice", "kb", "doc-guide/chunk-2"),),
    "unknown_capture": (("q-outage", "kb", "doc-faq/chunk-1"),),
    "explicit_nonrelevant_inclusion": (("q-outage", "kb", "doc-faq"), ("q-invoice", "kb", "doc-1")),
    "unjudged_inclusion": (("q-refund", "kb", "doc-guide"), ("q-outage", "kb", "doc-news")),
    "never_retrieved": (("q-invoice", "kb", "doc-archive"),),
    "namespace_collision": (("q-invoice", "kb", "doc-1/chunk-1"), ("q-invoice", "tickets", "doc-1/chunk-1")),
    "retained_below_cutoff": (("q-refund", "kb", "doc-legal"), ("q-refund", "kb", "doc-legal/chunk-1")),
    "demotion": (("q-refund", "kb", "doc-guide/chunk-1"),),
    "query_scoped_relevance": (("q-refund", "kb", "doc-faq"), ("q-outage", "kb", "doc-faq")),
    "chunk_excluded_document_included": (("q-refund", "kb", "doc-policy/chunk-2"), ("q-invoice", "kb", "doc-guide/chunk-2")),
}
