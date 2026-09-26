from dataclasses import fields

from retrieval_observatory.store.base import BaseStore, InvestigationFilter, TraceQuery
from retrieval_observatory.store.postgres import PostgresStore
from retrieval_observatory.store.sqlite import SQLiteStore

INVESTIGATION_METHODS = {
    "replace_investigation_projection", "get_investigation_projection", "list_investigation_projections",
    "list_investigation_pairs", "get_investigation_pair", "list_investigation_summaries",
    "get_investigation_summary", "delete_investigation_projection",
}


def test_store_protocol_has_one_trace_surface() -> None:
    names = set(BaseStore.__dict__)
    assert {"save_trace", "save_traces", "get_trace", "list_traces", "list_services", "purge_traces"} <= names
    suffix = "_v2"
    assert {f"save_trace{suffix}", f"get_trace{suffix}", f"get_traces{suffix}", "save_traces_batch"}.isdisjoint(names)


def test_trace_query_supports_production_and_evaluation_scope() -> None:
    query = TraceQuery(service_id="svc", run_id=None, pipeline_id="pipe", limit=50, offset=0)
    assert query.service_id == "svc" and query.run_id is None


def test_both_backends_implement_every_protocol_method_including_investigation() -> None:
    names = {name for name in BaseStore.__dict__ if not name.startswith("_")}
    assert INVESTIGATION_METHODS <= names
    for backend in (SQLiteStore, PostgresStore):
        missing = sorted(name for name in names if not callable(getattr(backend, name, None)))
        assert not missing, f"{backend.__name__} lacks {missing}"


def test_investigation_filter_fields_are_all_optional_columns() -> None:
    assert {f.name for f in fields(InvestigationFilter)} == {
        "query_id", "trace_id", "namespace", "entity_id", "unit", "outcome", "judgment",
        "final_membership", "capture_state", "loss_boundary", "confusion",
    }
    assert all(getattr(InvestigationFilter(), f.name) is None for f in fields(InvestigationFilter))
