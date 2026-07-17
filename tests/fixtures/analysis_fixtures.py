from retrieval_observatory.analysis.contracts import AnalysisScope, EvidenceDescriptor
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming


def candidate(doc_id="d1", rank=1, score=1.0, origins=()):
    return Candidate(doc_id, score, rank, origin_op_ids=origins)


def source_span(op_id="source", outputs=None):
    return OperatorSpan.source(op_id, op_id, outputs or [candidate(origins=(op_id,))])


def make_trace(trace_id="t1", query_id="q1", spans=(), timing=True):
    spans = tuple(spans)
    return RetrievalTrace(
        trace_id,
        "search",
        "r1",
        query_id,
        "query",
        "pipe",
        spans,
        (spans[-1].op_id,) if spans else (),
        timing=TraceTiming.from_spans(spans) if timing and spans else None,
    )


def analysis_scope(**values):
    return AnalysisScope("main", **values)


def evidence_descriptor(**values):
    return EvidenceDescriptor(
        values.pop("evidence_class", "measured"),
        values.pop("method_id", "test"),
        "1",
        values.pop("sample_size", 1),
        values.pop("population_size", 1),
        values.pop("coverage", 1),
        **values,
    )
