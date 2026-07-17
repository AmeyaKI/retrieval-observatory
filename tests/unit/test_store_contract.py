from retrieval_observatory.store.base import BaseStore, TraceQuery


def test_store_protocol_has_one_trace_surface() -> None:
    names = set(BaseStore.__dict__)
    assert {"save_trace", "save_traces", "get_trace", "list_traces", "list_services", "purge_traces"} <= names
    suffix = "_v2"
    assert {f"save_trace{suffix}", f"get_trace{suffix}", f"get_traces{suffix}", "save_traces_batch"}.isdisjoint(names)


def test_trace_query_supports_production_and_evaluation_scope() -> None:
    query = TraceQuery(service_id="svc", run_id=None, pipeline_id="pipe", limit=50, offset=0)
    assert query.service_id == "svc" and query.run_id is None
