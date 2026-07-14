from __future__ import annotations

import asyncio
import json
import os
import uuid

import pytest

from retrieval_observatory.store.base import BaseStore
from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2
from retrieval_observatory.types import Query


@pytest.fixture(params=["sqlite", "postgres"])
async def contract_store(request, tmp_path):
    if request.param == "sqlite":
        from retrieval_observatory.store.sqlite import SQLiteStore

        store = SQLiteStore(str(tmp_path / "contract.db"))
    else:
        dsn = os.getenv("RETOBS_POSTGRES_DSN")
        if not dsn:
            pytest.skip("RETOBS_POSTGRES_DSN not set")
        from retrieval_observatory.store.postgres import PostgresStore

        store = PostgresStore(dsn)
    await store.init_db()
    assert isinstance(store, BaseStore)
    yield store
    close = getattr(store, "close", None)
    if close:
        await close()


def _trace(run_id: str, query_id: str, index: int) -> RetrievalTraceV2:
    candidate = Candidate(
        doc_id=f"文档-{index}",
        score=1.0,
        rank=1,
        origin_op_ids=["source"],
        metadata={"payload": "x" * 4096},
    )
    return RetrievalTraceV2(
        trace_id=f"{run_id}-trace-{index}",
        run_id=run_id,
        query_id=query_id,
        query_text="unicode query café",
        pipeline_id="pipeline",
        spans=[OperatorSpan(
            op_id="source",
            op_type="SOURCE",
            op_name="source",
            parent_ids=[],
            status="ERROR" if index == 2 else "FIRED",
            deterministic=True,
            replay_policy="EXACT",
            latency_ms=1.0,
            outputs=[candidate],
            error="boom" if index == 2 else None,
        )],
        total_latency_ms=1.0,
        status="ERROR" if index == 2 else "OK",
        final_op_id="source",
    )


@pytest.mark.asyncio
async def test_store_contract_run_trace_query_summary_and_pagination(contract_store) -> None:
    store = contract_store
    run_id = f"contract-{uuid.uuid4().hex}"
    await store.save_run(run_id, "contract", "{}")
    await store.save_run_manifest(run_id, {"schema_version": 3, "unicode": "café"})
    await store.save_run_queries(run_id, [Query(text="unicode query café", query_id="query")], "custom")
    await store.save_qrels(run_id, {"query": {"文档-0": 2}})
    await asyncio.gather(*[store.save_trace_v2(_trace(run_id, "query", index)) for index in range(3)])
    await store.save_query_diagnostics([{
        "run_id": run_id,
        "query_id": "query",
        "pipeline_id": "pipeline",
        "difficulty_bucket": "hard",
        "failure_labels": ["candidate_miss"],
        "missing_relevant_ids": ["文档-0"],
        "stage_hits": {"0": []},
        "diagnostic_evidence": [{
            "label": "candidate_miss",
            "evidence_class": "measured",
            "method": "contract",
            "reason": "contract",
            "doc_ids": [],
            "threshold": None,
        }],
    }])
    dataset_id = f"dataset-{uuid.uuid4().hex}"
    await store.save_forge_dataset(dataset_id, json.dumps({"n_queries": 3, "n_scenarios": 1}), "", "")
    await store.save_forge_queries(dataset_id, json.dumps([{
        "query_id": "forge-query",
        "text": "generated",
        "scenario_id": "scenario",
        "query_type": "comparison",
        "difficulty_label": "medium",
        "validated": False,
        "positive_doc_ids": ["文档-0"],
        "metadata": {"generation_method": "rule_template_v1", "label_method": "extractive_source_document"},
    }]))

    first_page = await store.get_traces_v2(run_id, query_id="query", limit=2, offset=0)
    second_page = await store.get_traces_v2(run_id, query_id="query", limit=2, offset=2)

    assert len(first_page) == 2
    assert len(second_page) == 1
    assert second_page[0].status == "ERROR"
    assert second_page[0].spans[0].error == "boom"
    assert (await store.get_run_manifest(run_id))["unicode"] == "café"
    assert (await store.get_qrels(run_id))["query"]["文档-0"] == 2
    assert (await store.get_run_queries(run_id))[0]["query_text"] == "unicode query café"
    diagnostics = await store.get_query_diagnostics(run_id, query_id="query")
    assert diagnostics[0]["diagnostic_evidence"][0]["method"] == "contract"
    summaries = await store.get_forge_datasets()
    summary = next(item["summary"] for item in summaries if item["dataset_id"] == dataset_id)
    assert summary["schema_version"] == 1
    assert summary["total_queries"] == 3
    forge_queries = await store.get_forge_queries(dataset_id)
    assert forge_queries[0]["provenance"]["generation_method"] == "rule_template_v1"
    assert forge_queries[0]["provenance"]["label_method"] == "extractive_source_document"
