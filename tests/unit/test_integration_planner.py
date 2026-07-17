from retrieval_observatory.integrations.planner import build_integration_plan


def test_planner_discovers_concrete_symbols(tmp_path):
    (tmp_path/"app.py").write_text("from fastapi import FastAPI\napp=FastAPI()\n@app.post('/retrieve')\ndef retrieve(q): return cross_encoder_rerank(temporal_filter(reciprocal_rank_fuse([bm25_retrieve(q), dense_retrieve(q)])))\ndef bm25_retrieve(q): return []\ndef dense_retrieve(q): return []\ndef reciprocal_rank_fuse(x): return x\ndef temporal_filter(x): return x\ndef cross_encoder_rerank(x): return x\n")
    (tmp_path/"queries.jsonl").write_text('{"id":"q1","text":"query"}\n')
    plan=build_integration_plan(tmp_path)
    assert [op.op_type for op in plan.operators]==["SOURCE","SOURCE","SOURCE","FUSE","FILTER","RERANK"]
    assert all(op.symbol in (tmp_path/"app.py").read_text() for op in plan.operators)
    assert plan.framework == "fastapi"
    assert plan.discovery["http_routes"][0]["path"] == "/retrieve"
    assert plan.discovery["datasets"] == ["queries.jsonl"]
    assert len(plan.patches) == 1
    compile(plan.patches[0].replacement, "app.py", "exec")
    assert plan.patches[0].precondition_sha256


def test_planner_preserves_parentage_through_assigned_route(tmp_path):
    (tmp_path / "app.py").write_text(
        "def intent_gate(query): return 'hybrid'\n"
        "def bm25(query, route): return []\n"
        "def retrieve(query):\n"
        "    route = intent_gate(query)\n"
        "    return bm25(query, route)\n",
        encoding="utf-8",
    )

    plan = build_integration_plan(tmp_path)
    operators = {operator.symbol: operator for operator in plan.operators}

    assert operators["bm25"].parent_ids == ("intent_gate",)


def test_planner_discovers_named_source_operator(tmp_path):
    (tmp_path / "app.py").write_text(
        "def source(query): return []\n"
        "def retrieve(query): return source(query)\n",
        encoding="utf-8",
    )

    plan = build_integration_plan(tmp_path)

    assert {operator.symbol for operator in plan.operators} == {"source", "retrieve"}
