import json

from retrieval_observatory.store.postgres import _trace_from_json
from retrieval_observatory.tracing.model import OperatorSpan, RetrievalTrace


def test_trace_json_accepts_postgres_jsonb_string_and_mapping() -> None:
    trace = RetrievalTrace(trace_id="trace", service_id="service", pipeline_id="pipeline", query_id="query", run_id=None, query_text="query", spans=(OperatorSpan.source("source", "Source", ()),))
    payload = trace.to_dict()
    assert _trace_from_json(json.dumps(payload)) == _trace_from_json(payload)
