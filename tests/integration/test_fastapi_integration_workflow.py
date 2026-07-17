import importlib.util

from retrieval_observatory.integrations.apply import apply_integration_plan
from retrieval_observatory.integrations.manifest import load_manifest
from retrieval_observatory.integrations.planner import build_integration_plan
from retrieval_observatory.integrations.verify import verify_observed_traces
from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace


def test_fastapi_hybrid_plan_apply_verify_preserves_output(tmp_path):
    app_path = tmp_path / "app.py"
    app_path.write_text(
        "from fastapi import FastAPI\n"
        "app=FastAPI()\n"
        "def bm25_retrieve(q): return [{'id':'a','score':1.0}]\n"
        "def dense_retrieve(q): return [{'id':'b','score':0.9}]\n"
        "def reciprocal_rank_fuse(groups): return groups[0]+groups[1]\n"
        "def temporal_filter(items): return items\n"
        "def cross_encoder_rerank(items): return items\n"
        "@app.post('/retrieve')\n"
        "def retrieve(q): return cross_encoder_rerank(temporal_filter(reciprocal_rank_fuse([bm25_retrieve(q),dense_retrieve(q)])))\n",
        encoding="utf-8",
    )
    plan = build_integration_plan(tmp_path)
    before = [{"id": "a", "score": 1.0}, {"id": "b", "score": 0.9}]
    apply_integration_plan(plan)
    spec = importlib.util.spec_from_file_location("external_fastapi_app", app_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    start_trace(ObserveContext(None, "q1", "query", plan.pipeline_id, plan.service_id))
    assert module.retrieve("query") == before
    trace = finish_trace()
    result = verify_observed_traces(load_manifest(tmp_path), [trace])
    assert result.status == "ready"
    assert set(result.observed_operator_ids) == {operator.op_id for operator in plan.operators}
