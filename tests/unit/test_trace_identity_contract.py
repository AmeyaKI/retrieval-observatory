from datetime import datetime, timezone

import pytest

from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace


def test_production_and_evaluation_share_one_trace_contract() -> None:
    span = OperatorSpan.source("bm25", "BM25", [Candidate("d1", 1.0, 1)])
    production = RetrievalTrace(
        trace_id="t1",
        service_id="search",
        run_id=None,
        query_id="q1",
        query_text="hello",
        pipeline_id="hybrid",
        spans=[span],
        final_op_ids=("bm25",),
        timestamp=datetime.now(timezone.utc),
    )
    evaluation = RetrievalTrace.from_dict({**production.to_dict(), "trace_id": "t2", "run_id": "run-1"})
    assert production.run_id is None
    assert evaluation.run_id == "run-1"
    assert RetrievalTrace.from_dict(production.to_dict()) == production


def test_trace_rejects_unknown_parent() -> None:
    with pytest.raises(ValueError, match="unknown parent missing"):
        RetrievalTrace(
            trace_id="t",
            service_id="svc",
            run_id="run",
            query_id="q",
            query_text="q",
            pipeline_id="pipe",
            spans=[OperatorSpan.source("dense", "Dense", [], parent_ids=("missing",))],
            final_op_ids=("dense",),
            timestamp=datetime.now(timezone.utc),
        )
