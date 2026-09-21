"""Golden investigation fixture: an executable hybrid pipeline plus a hand-authored journey table.

``run_fixture()`` really executes a small hybrid retrieval pipeline (plain functions over an
in-memory corpus) for three queries and records every operator's ACTUAL arguments and ACTUAL
return value as ``RetrievalTrace`` spans through ``build_candidate_transition``. The
``EXPECTED_*`` tables below were written by hand from the scenario, never computed from any
journey or lineage code, so later journey projections can be tested against them.

Identity convention (the trace model has no namespace field yet):
    candidate_id     = f"{namespace}:{chunk_id}"        e.g. "kb:doc-policy/chunk-1"
    logical_chunk_id = chunk_id                         e.g. "doc-policy/chunk-1"
    doc_id           = chunk_id
    document_id      = document id                      e.g. "doc-policy"
    metadata         = {"namespace": ..., "year": ..., "title": ...}
Two chunks with the same local ids in different namespaces are therefore distinct candidates
(``kb:doc-1/chunk-1`` vs ``tickets:doc-1/chunk-1``).

Deliberate capture defect: for q-outage the recorder keeps only the first output of
``rerank@lexical`` (``CAPTURE_LIMITS``). The application still consumes the operator's real
two-element return value, so ``fuse``'s recorded input group differs from ``rerank@lexical``'s
recorded outputs, and the recorder does not invent a drop reason for the unobserved exit.

q-refund is the flagship query: ``doc-policy/chunk-1`` is found by both sources, dropped on the
lexical branch (``min_score``) and delivered via the dense branch; ``doc-faq/chunk-1`` survives both
branches and is deduplicated at ``fuse`` (RRF k=60: faq 1/62+1/61, policy/chunk-1 1/61,
policy/chunk-2 1/62, guide 1/63 and legal 1/63 tied, resolved by dense-first input order);
``doc-policy/chunk-2`` reaches ``select`` and is dropped as ``duplicate_document``; ``doc-legal``
is delivered at rank 4, below k=3.

Expected-table conventions:
    * ``loss_boundary`` for an excluded document is the op_id of the recorded removal that
      took it off the path to ``select``; ``"select"`` when it reached the final output but
      ranked below k; ``"not_observed"`` when no trace contains it; ``"unknown"`` when the
      exit is not recorded; ``None`` when included.
    * ``capture_state`` is per document: ``"partial"`` when any of its chunks crosses a
      boundary whose capture was truncated in that query.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Literal, Mapping, Sequence

from retrieval_observatory.tracing.candidates import build_candidate_transition, to_candidates
from retrieval_observatory.tracing.model import Candidate, CaptureMetadata, OperatorSpan, RetrievalTrace
from retrieval_observatory.types import Query

EVALUATION_SPEC = {
    "unit": "document",
    "k": 3,
    "relevance_threshold": 1,
    "boundary": "final_retrieval",
    "document_aggregation": "any_chunk",
}

RRF_K = 60
FUSE_KEEP = 5
RERANK_MODEL = "golden-crossencoder-v1"
RERANK_KEEP = 4
RECENCY_RULE = {"min_year": 2023, "min_score": 0.30}
SELECT_BUDGET = 5
# (query_id, op_id) -> number of output candidates the recorder keeps for that invocation.
CAPTURE_LIMITS: dict[tuple[str, str], int] = {("q-outage", "rerank@lexical"): 1}


def _doc(namespace: str, document_id: str, year: int, title: str, chunks: int) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (namespace, f"{document_id}/chunk-{index}"): {
            "document_id": document_id,
            "year": year,
            "title": title,
            "namespace": namespace,
        }
        for index in range(1, chunks + 1)
    }


CORPUS: dict[tuple[str, str], dict[str, Any]] = {
    **_doc("kb", "doc-policy", 2024, "Refund policy", 3),
    **_doc("kb", "doc-faq", 2024, "Billing FAQ", 1),
    **_doc("kb", "doc-legal", 2023, "Terms of service", 1),
    **_doc("kb", "doc-news", 2021, "Outage post-mortem 2021", 1),
    **_doc("kb", "doc-guide", 2025, "Customer guide", 2),
    **_doc("kb", "doc-archive", 2020, "Archived invoicing notes", 1),
    **_doc("kb", "doc-1", 2024, "Order 42 knowledge article", 1),
    **_doc("tickets", "doc-1", 2024, "Ticket: invoice for order 42", 1),
}

# ---------------------------------------------------------------------------
# Per-query score tables (inspectable; chosen to realise the scenario orderings)
# ---------------------------------------------------------------------------

DENSE_HITS: dict[str, list[tuple[str, str, float]]] = {
    "q-refund": [
        ("kb", "doc-policy/chunk-1", 0.91),
        ("kb", "doc-guide/chunk-1", 0.85),
        ("kb", "doc-faq/chunk-1", 0.80),
    ],
    "q-outage": [("kb", "doc-faq/chunk-1", 0.88), ("kb", "doc-news/chunk-1", 0.79)],
    "q-invoice": [
        ("kb", "doc-guide/chunk-1", 0.86),
        ("kb", "doc-1/chunk-1", 0.81),
        ("tickets", "doc-1/chunk-1", 0.77),
    ],
}

# Lexical lists are given in the scenario's order, not sorted by score: the first q-refund hit
# scores below the recency filter's minimum, the first q-invoice hit likewise.
LEXICAL_HITS: dict[str, list[tuple[str, str, float]]] = {
    "q-refund": [
        ("kb", "doc-policy/chunk-1", 0.25),  # min_score
        ("kb", "doc-news/chunk-1", 0.90),  # stale_year (2021)
        ("kb", "doc-faq/chunk-1", 0.70),
        ("kb", "doc-legal/chunk-1", 0.60),
        ("kb", "doc-policy/chunk-2", 0.50),
    ],
    "q-outage": [
        ("kb", "doc-guide/chunk-1", 0.80),
        ("kb", "doc-faq/chunk-1", 0.65),
        ("kb", "doc-news/chunk-1", 0.55),  # stale_year (2021)
    ],
    "q-invoice": [
        ("kb", "doc-guide/chunk-2", 0.20),  # min_score
        ("tickets", "doc-1/chunk-1", 0.75),
    ],
}

RERANK_SCORES: dict[str, dict[str, float]] = {
    "q-refund": {
        "kb:doc-policy/chunk-1": 0.95,
        "kb:doc-faq/chunk-1": 0.80,
        "kb:doc-policy/chunk-2": 0.70,
        "kb:doc-legal/chunk-1": 0.55,
        "kb:doc-guide/chunk-1": 0.40,
    },
    "q-outage": {
        "kb:doc-guide/chunk-1": 0.90,
        "kb:doc-faq/chunk-1": 0.85,
        "kb:doc-news/chunk-1": 0.30,
    },
    "q-invoice": {
        "tickets:doc-1/chunk-1": 0.92,
        "kb:doc-guide/chunk-1": 0.75,
        "kb:doc-1/chunk-1": 0.50,
    },
}

_QUERIES = [
    ("q-refund", "how do I get a refund", {"expand": False, "segment": "billing"}),
    ("q-outage", "why is the site down", {"expand": False, "segment": "support"}),
    ("q-invoice", "invoice for order 42", {"expand": True, "segment": "billing"}),
]

_JUDGMENTS = [
    # (query_id, namespace, entity_id, unit, grade)
    ("q-refund", "kb", "doc-policy", "document", 2),
    ("q-refund", "kb", "doc-faq", "document", 1),
    ("q-refund", "kb", "doc-legal", "document", 0),
    ("q-outage", "kb", "doc-guide", "document", 1),
    ("q-outage", "kb", "doc-faq", "document", 0),
    ("q-invoice", "kb", "doc-guide", "document", 1),
    ("q-invoice", "kb", "doc-archive", "document", 1),
    ("q-invoice", "tickets", "doc-1", "document", 2),
    ("q-invoice", "kb", "doc-1", "document", 0),
    ("q-invoice", "kb", "doc-guide/chunk-2", "chunk", 1),
]


def queries() -> list[Query]:
    return [Query(text=text, k=SELECT_BUDGET, query_id=query_id, metadata=dict(metadata)) for query_id, text, metadata in _QUERIES]


def judgment_records() -> list[dict[str, Any]]:
    return [
        {
            "query_id": query_id,
            "namespace": namespace,
            "entity_id": entity_id,
            "unit": unit,
            "grade": grade,
            "source_kind": "gold",
            "source_version": "golden-1",
        }
        for query_id, namespace, entity_id, unit, grade in _JUDGMENTS
    ]


def chunk_map() -> list[tuple[str, str, str]]:
    return [(chunk_id, entry["document_id"], namespace) for (namespace, chunk_id), entry in CORPUS.items()]


# ---------------------------------------------------------------------------
# Operators (plain functions; each returns (output items, decision reasons for dropped inputs))
# ---------------------------------------------------------------------------

Items = list[dict[str, Any]]
Reasons = dict[str, str]


def _identity(namespace: str, chunk_id: str) -> dict[str, Any]:
    entry = CORPUS[(namespace, chunk_id)]
    return {
        "doc_id": chunk_id,
        "candidate_id": f"{namespace}:{chunk_id}",
        "logical_chunk_id": chunk_id,
        "document_id": entry["document_id"],
        "metadata": {"namespace": namespace, "year": entry["year"], "title": entry["title"]},
    }


def _item(candidate: Candidate, score: float, rank: int, **extra: Any) -> dict[str, Any]:
    return {**_identity(candidate.metadata["namespace"], candidate.logical_chunk_id), "score": score, "rank": rank, **extra}


def dense(query: Query) -> Items:
    return [
        {**_identity(namespace, chunk_id), "score": score, "rank": rank, "score_type": "cosine"}
        for rank, (namespace, chunk_id, score) in enumerate(DENSE_HITS[query.query_id], start=1)
    ]


def lexical(query: Query) -> Items:
    return [
        {**_identity(namespace, chunk_id), "score": score, "rank": rank, "score_type": "bm25"}
        for rank, (namespace, chunk_id, score) in enumerate(LEXICAL_HITS[query.query_id], start=1)
    ]


def recency_filter(inputs: Sequence[Candidate]) -> tuple[Items, Reasons]:
    kept: Items = []
    reasons: Reasons = {}
    for candidate in inputs:
        if candidate.metadata["year"] < RECENCY_RULE["min_year"]:
            reasons[candidate.candidate_id] = "stale_year"
        elif candidate.score < RECENCY_RULE["min_score"]:
            reasons[candidate.candidate_id] = "min_score"
        else:
            kept.append(_item(candidate, candidate.score, len(kept) + 1))
    return kept, reasons


def rerank(query: Query, inputs: Sequence[Candidate]) -> tuple[Items, Reasons]:
    table = RERANK_SCORES[query.query_id]
    ordered = sorted(inputs, key=lambda candidate: -table[candidate.candidate_id])
    items = [
        _item(candidate, table[candidate.candidate_id], rank, score_type="crossencoder", score_model=RERANK_MODEL)
        for rank, candidate in enumerate(ordered[:RERANK_KEEP], start=1)
    ]
    return items, {candidate.candidate_id: "rerank_cutoff" for candidate in ordered[RERANK_KEEP:]}


def fuse(groups: Mapping[str, Sequence[Candidate]]) -> tuple[Items, Reasons]:
    fused: dict[str, dict[str, Any]] = {}
    for parent_id, candidates in groups.items():
        for candidate in candidates:
            entry = fused.setdefault(candidate.candidate_id, {"candidate": candidate, "score": 0.0, "fused_from": []})
            entry["score"] += 1.0 / (RRF_K + candidate.rank)
            entry["fused_from"].append(parent_id)
    ordered = sorted(fused.values(), key=lambda entry: -entry["score"])  # stable: ties keep input order
    items: Items = []
    for rank, entry in enumerate(ordered[:FUSE_KEEP], start=1):
        item = _item(entry["candidate"], entry["score"], rank, add_reason="fused", score_type="rrf")
        item["metadata"]["fused_from"] = list(entry["fused_from"])
        items.append(item)
    return items, {entry["candidate"].candidate_id: "fusion_cutoff" for entry in ordered[FUSE_KEEP:]}


def passthrough(inputs: Sequence[Candidate]) -> tuple[Items, Reasons]:
    return [_item(candidate, candidate.score, candidate.rank) for candidate in inputs], {}


def expand(inputs: Sequence[Candidate]) -> tuple[Items, Reasons]:
    items, _ = passthrough(inputs)
    present = {candidate.candidate_id for candidate in inputs}
    for candidate in inputs[:2]:
        namespace = candidate.metadata["namespace"]
        stem, _, index = candidate.logical_chunk_id.rpartition("chunk-")
        sibling = f"{stem}chunk-{int(index) + 1}"
        if (namespace, sibling) in CORPUS and f"{namespace}:{sibling}" not in present:
            present.add(f"{namespace}:{sibling}")
            items.append(
                {
                    **_identity(namespace, sibling),
                    "score": candidate.score * 0.9,
                    "rank": len(items) + 1,
                    "parent_candidate_ids": (candidate.candidate_id,),
                    "add_reason": "expanded",
                }
            )
    return items, {}


def select(inputs: Sequence[Candidate]) -> tuple[Items, Reasons]:
    kept: Items = []
    reasons: Reasons = {}
    seen: set[tuple[str, str]] = set()
    for candidate in inputs:
        key = (candidate.metadata["namespace"], candidate.document_id)
        if key in seen:
            reasons[candidate.candidate_id] = "duplicate_document"
        elif len(kept) >= SELECT_BUDGET:
            reasons[candidate.candidate_id] = "context_budget"
        else:
            seen.add(key)
            kept.append(_item(candidate, candidate.score, len(kept) + 1))
    return kept, reasons


# ---------------------------------------------------------------------------
# Recorder: snapshots the actual arguments, runs the operator, records the actual result
# ---------------------------------------------------------------------------

CallLog = dict[str, dict[str, tuple[str, ...]]]  # op_id -> parent_op_id -> candidate_ids passed


def _unobserved(candidate: Candidate) -> Candidate:
    """An input whose exit was not captured: no drop is recorded and no reason is inferred."""
    return replace(candidate, output_rank=None, drop_reason=None, decision_reason=None, decision_evidence="unavailable")


class _Recorder:
    def __init__(self, query: Query) -> None:
        self.query = query
        self.spans: list[OperatorSpan] = []
        self.calls: CallLog = {}
        self.truncated = False

    def _links(self, op_id: str, parent_ids: tuple[str, ...]) -> dict[str, Any]:
        """Deterministic invocation identity: the recorder knows exactly which invocation fed which."""
        return {
            "invocation_id": f"{self.query.query_id}:{op_id}",
            "parent_invocation_ids": tuple(f"{self.query.query_id}:{parent}" for parent in parent_ids),
            "parent_linkage": "recorded",
        }

    def source(self, op_id: str, items: Items) -> list[Candidate]:
        span = OperatorSpan(op_id, "SOURCE", op_id, (), "FIRED", 0.0, outputs=to_candidates(items, op_id), branch_id=op_id, **self._links(op_id, ()))
        self.spans.append(span)
        return list(span.outputs)

    def skipped(self, op_id: str, op_type: str, parent_ids: tuple[str, ...], gate_values: Mapping[str, Any]) -> None:
        self.spans.append(OperatorSpan(
            op_id, op_type, op_id, parent_ids, "SKIPPED_BY_GATE", 0.0, gate_values=dict(gate_values),
            input_capture="not_applicable", output_capture="unavailable", **self._links(op_id, parent_ids),
        ))

    def record(
        self,
        op_id: str,
        op_type: str,
        *,
        parent_ids: tuple[str, ...],
        input_groups: Mapping[str, Sequence[Candidate]],
        operator: Callable[[], tuple[Items, Reasons]],
        op_name: str | None = None,
        operator_id: str | None = None,
        branch_id: str | None = None,
        params: Mapping[str, Any] | None = None,
        gate_values: Mapping[str, Any] | None = None,
    ) -> list[Candidate]:
        self.calls[op_id] = {parent: tuple(c.candidate_id for c in candidates) for parent, candidates in input_groups.items()}
        items, reasons = operator()
        params = dict(params or {})

        def transition(output_items: Items):
            return build_candidate_transition(
                input_groups=input_groups, output_items=output_items, op_id=op_id, op_type=op_type, decision_reasons=reasons
            )

        full = transition(items)
        recorded_groups, recorded_outputs = full.input_groups, full.outputs
        limit = CAPTURE_LIMITS.get((self.query.query_id, op_id))
        if limit is not None and limit < len(items):
            self.truncated = True
            params["capture"] = {"outputs": "truncated", "recorded": limit, "returned": len(items)}
            clipped = transition(items[:limit])
            recorded_outputs = clipped.outputs
            recorded_groups = {
                parent: tuple(_unobserved(c) if c.output_rank is None else c for c in candidates)
                for parent, candidates in clipped.input_groups.items()
            }
        self.spans.append(
            OperatorSpan(
                op_id,
                op_type,
                op_name or op_id,
                parent_ids,
                "FIRED",
                0.0,
                input_groups=recorded_groups,
                outputs=recorded_outputs,
                deterministic=True,
                params=params,
                gate_values=dict(gate_values or {}),
                branch_id=branch_id,
                operator_id=operator_id,
                **self._links(op_id, parent_ids),
            )
        )
        # The application consumes the operator's real return value, whatever the recorder kept.
        return list(full.outputs)


def _run(query: Query) -> tuple[list[Candidate], RetrievalTrace, CallLog]:
    rec = _Recorder(query)
    dense_out = rec.source("dense", dense(query))
    lexical_out = rec.source("lexical", lexical(query))
    filtered = rec.record(
        "recency_filter", "FILTER", parent_ids=("lexical",), branch_id="lexical", params=RECENCY_RULE,
        input_groups={"lexical": lexical_out}, operator=lambda: recency_filter(lexical_out),
    )
    rerank_params = {"operator": "rerank", "model": RERANK_MODEL, "keep": RERANK_KEEP}
    reranked_dense = rec.record(
        "rerank@dense", "RERANK", op_name="rerank", operator_id="rerank", parent_ids=("dense",), branch_id="dense", params=rerank_params,
        input_groups={"dense": dense_out}, operator=lambda: rerank(query, dense_out),
    )
    reranked_lexical = rec.record(
        "rerank@lexical", "RERANK", op_name="rerank", operator_id="rerank", parent_ids=("recency_filter",), branch_id="lexical",
        params=rerank_params, input_groups={"recency_filter": filtered}, operator=lambda: rerank(query, filtered),
    )
    fuse_groups = {"rerank@dense": reranked_dense, "rerank@lexical": reranked_lexical}
    fused = rec.record(
        "fuse", "FUSE", parent_ids=("rerank@dense", "rerank@lexical"), params={"method": "rrf", "k": RRF_K, "keep": FUSE_KEEP},
        input_groups=fuse_groups, operator=lambda: fuse(fuse_groups),
    )
    expand_on = bool(query.metadata["expand"])
    gated = rec.record(
        "expand_gate", "GATE", parent_ids=("fuse",), gate_values={"expand": expand_on},
        input_groups={"fuse": fused}, operator=lambda: passthrough(fused),
    )
    if expand_on:
        select_parent, select_inputs = "expand", rec.record(
            "expand", "EXPAND", parent_ids=("expand_gate",), gate_values={"expand": True},
            input_groups={"expand_gate": gated}, operator=lambda: expand(gated),
        )
    else:
        rec.skipped("expand", "EXPAND", ("expand_gate",), {"expand": False})
        select_parent, select_inputs = "expand_gate", gated
    selected = rec.record(
        "select", "TRANSFORM", parent_ids=(select_parent,), params={"budget": SELECT_BUDGET, "one_chunk_per_document": True},
        input_groups={select_parent: select_inputs}, operator=lambda: select(select_inputs),
    )
    trace = RetrievalTrace(
        trace_id=f"trace-{query.query_id}",
        service_id="golden",
        run_id="golden-run",
        query_id=query.query_id,
        query_text=query.text,
        pipeline_id="golden-hybrid",
        spans=tuple(rec.spans),
        final_op_ids=("select",),
        dataset_id="golden",
        corpus_version="kb@1",
        capture=CaptureMetadata(candidates_truncated=rec.truncated, lineage_evidence="partial" if rec.truncated else "recorded"),
        metadata={"segment": query.metadata["segment"]},
    )
    return selected, trace, rec.calls


def run_pipeline(query: Query) -> tuple[list[Candidate], RetrievalTrace]:
    selected, trace, _ = _run(query)
    return selected, trace


@dataclass(frozen=True)
class FixtureRun:
    queries: list[Query]
    traces: list[RetrievalTrace]
    judgments: list[dict[str, Any]]
    chunk_map: list[tuple[str, str, str]]
    spec: dict[str, Any]
    calls: dict[str, CallLog]  # query_id -> raw argument snapshots per op_id


def run_fixture() -> FixtureRun:
    run_queries = queries()
    traces: list[RetrievalTrace] = []
    calls: dict[str, CallLog] = {}
    for query in run_queries:
        _, trace, call_log = _run(query)
        traces.append(trace)
        calls[query.query_id] = call_log
    return FixtureRun(run_queries, traces, judgment_records(), chunk_map(), dict(EVALUATION_SPEC), calls)


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
