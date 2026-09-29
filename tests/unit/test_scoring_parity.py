"""Scoring a plain-qrels run through ``_document_view`` (the ``judged_document`` rule shared with the
inspect views) leaves metrics unchanged where candidates carry no other document, and counts the
chunks of one judged document once."""

from __future__ import annotations

import asyncio

import pytest

from retrieval_observatory.datasets.judgments import EvaluationSpec, JudgmentSet
from retrieval_observatory.evidence.investigation import JourneyRow
from retrieval_observatory.evidence.journeys import project_trace_journeys
from retrieval_observatory.metrics.engine import MetricsEngine
from retrieval_observatory.runner.execute import _document_view
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace

QRELS = {"q1": {"doc-a": 2, "doc-b": 1, "doc-c": 0}, "q2": {"doc-d": 1}}


class _Capture:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def save_metrics_batch(self, rows: list[dict]) -> None:
        self.rows.extend(rows)


def _trace(query_id: str, *hits: Candidate) -> RetrievalTrace:
    source = OperatorSpan.source("search", "Search", hits)
    rerank = OperatorSpan(
        op_id="rerank", op_type="RERANK", op_name="rerank", parent_ids=["search"], status="FIRED",
        deterministic=True, replay_policy="EXACT", latency_ms=1.0,
        input_groups={"search": tuple(source.outputs)}, outputs=tuple(reversed(source.outputs)),
    )
    return RetrievalTrace(
        trace_id=f"t-{query_id}", service_id="svc", run_id="run", query_id=query_id, query_text=query_id,
        pipeline_id="pipe", spans=(source, rerank), final_op_ids=("rerank",),
    )


def _hit(doc_id: str, rank: int, document_id: str | None = None, **metadata: str) -> Candidate:
    return Candidate(doc_id, 1.0 / rank, rank, document_id=document_id, metadata=metadata)


def _metrics(traces: list[RetrievalTrace]) -> dict[tuple, float]:
    engine = MetricsEngine(recall_at_k_values=[1, 2, 3], precision_at_k_values=[2], ndcg_at_k_values=[3], compute_mrr=True, compute_map=True)
    store = _Capture()
    asyncio.run(engine.compute_from_traces(run_id="run", store=store, traces=traces, qrels=QRELS))
    return {(row["query_id"], row["stage_index"], row["metric_name"], row["k"]): row["value"] for row in store.rows}


def _viewed(traces: list[RetrievalTrace]) -> list[RetrievalTrace]:
    """The plain-qrels branch of ``execute_benchmark``."""
    return [_document_view(trace, None, JudgmentSet.from_qrels(QRELS), namespaced=False) for trace in traces]


def _final_ids(trace: RetrievalTrace) -> list[str]:
    return [candidate.doc_id for candidate in trace.spans[-1].outputs]


def test_plain_qrels_scores_do_not_move_when_candidates_name_no_other_document() -> None:
    traces = [
        _trace("q1", _hit("doc-a", 1), _hit("doc-x", 2, document_id="doc-x"), _hit("doc-b", 3), _hit("doc-c", 4, document_id="doc-c")),
        # A namespace in the metadata changes nothing when the candidate names no other document.
        _trace("q2", _hit("doc-y", 1, namespace="kb"), _hit("doc-d", 2, namespace="kb")),
    ]
    viewed = _viewed(traces)
    assert [_final_ids(trace) for trace in viewed] == [_final_ids(trace) for trace in traces]
    raw = _metrics(traces)
    assert raw and _metrics(viewed) == raw


def test_chunks_of_one_judged_document_count_once() -> None:
    """Intended change: three chunks of ``doc-a`` were three unjudged ids; scored as ``doc-a`` they are
    one relevant document, so ``doc-b`` moves from rank 4 to rank 2."""
    trace = _trace("q1", _hit("doc-b", 1), *(_hit(f"doc-a#{i}", 4 - i, document_id="doc-a") for i in (2, 1, 0)))
    assert _final_ids(trace) == ["doc-a#0", "doc-a#1", "doc-a#2", "doc-b"]  # the rerank reverses the source
    raw, viewed = _metrics([trace]), _metrics(_viewed([trace]))
    final = max(key[1] for key in raw)
    assert raw[("q1", final, "recall", 2)] == 0.0
    assert viewed[("q1", final, "recall", 2)] == pytest.approx(1.0)  # doc-a, doc-b: both relevant documents
    assert viewed[("q1", final, "recall", 1)] == pytest.approx(0.5)


def test_a_candidate_whose_own_id_is_judged_keeps_matching_by_it() -> None:
    """``doc-b`` is judged; the ``doc-parent`` it names is not, so it still scores as ``doc-b``."""
    trace = _trace("q1", _hit("doc-b", 1, document_id="doc-parent"), _hit("doc-z", 2, document_id="doc-parent"))
    (viewed,) = _viewed([trace])
    assert sorted(_final_ids(viewed)) == ["doc-b", "doc-parent"]
    raw = _metrics([trace])
    assert _metrics([viewed]) == raw and max(value for key, value in raw.items() if key[2] == "recall") > 0


def test_plain_qrels_match_a_namespaced_candidate_by_its_id() -> None:
    """Plain qrels carry no namespace: a ``kb`` candidate whose own id is judged still scores as it."""
    trace = _trace("q1", _hit("doc-b", 1, document_id="doc-parent", namespace="kb"), _hit("doc-z", 2))
    (viewed,) = _viewed([trace])
    assert sorted(_final_ids(viewed)) == ["doc-b", "doc-z"]
    assert _metrics([viewed]) == _metrics([trace])


def _rows(trace: RetrievalTrace, judgments: JudgmentSet) -> dict[tuple[str, str], JourneyRow]:
    spec = EvaluationSpec(unit="document", relevance_threshold=1, boundary="final_retrieval", k=5)
    return {(row.namespace, row.entity_id): row for row in project_trace_journeys(trace, judgments, spec)}


def test_plain_qrels_judge_a_namespaced_candidate_in_its_own_row() -> None:
    """Inspection agrees with scoring: ``kb:doc-d`` is the relevant row, with no separate ``default:doc-d``."""
    rows = _rows(_trace("q2", _hit("doc-y", 1, namespace="kb"), _hit("doc-d", 2, namespace="kb")), JudgmentSet.from_qrels(QRELS))
    assert set(rows) == {("kb", "doc-y"), ("kb", "doc-d")}
    assert (rows[("kb", "doc-d")].judgment, rows[("kb", "doc-d")].grade, rows[("kb", "doc-d")].judgment_source) == ("relevant", 1, "gold")


def test_namespaced_judgments_never_match_across_namespaces() -> None:
    judgments = JudgmentSet.from_records([*JudgmentSet.from_qrels({"q2": {"doc-d": 1}}, namespace="web").to_records()])
    trace = _trace("q2", _hit("doc-d", 1, namespace="kb"))
    rows = _rows(trace, judgments)
    assert rows[("kb", "doc-d")].judgment == "unjudged" and rows[("web", "doc-d")].outcome == "not_observed"
    (viewed,) = [_document_view(trace, None, judgments, namespaced=True)]
    assert _final_ids(viewed) == ["kb:doc-d"]
