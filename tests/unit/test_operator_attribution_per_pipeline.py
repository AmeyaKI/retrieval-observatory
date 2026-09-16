"""/operator-attribution computes per pipeline (never pooling ops that share an id across
pipelines), tags rows with pipeline_id, and turns one failing operator into an error row."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard import api as dashboard_api
from retrieval_observatory.dashboard.api import create_app
from retrieval_observatory.dashboard.registry import DbRegistry
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace, TraceTiming

RUN = "run1"


def _cands(*doc_ids: str) -> tuple:
    return tuple(Candidate(doc_id=d, score=1.0 / (i + 1), rank=i + 1) for i, d in enumerate(doc_ids))


def _trace(pipeline_id: str, query_id: str, *, with_filter: bool) -> RetrievalTrace:
    source = OperatorSpan(
        "retriever", "SOURCE", "retriever", (), "FIRED", 2.0,
        outputs=_cands("d1", "d2"), replay_policy="EXACT", deterministic=True,
    )
    spans = [source]
    if with_filter:
        spans.append(
            OperatorSpan(
                "filter_cap", "FILTER", "cap", ("retriever",), "FIRED", 1.0,
                inputs=source.outputs, outputs=_cands("d2"), replay_policy="EXACT", deterministic=True,
            )
        )
    return RetrievalTrace(
        trace_id=f"{pipeline_id}-{query_id}", service_id="bench", run_id=RUN, query_id=query_id, query_text="q",
        pipeline_id=pipeline_id, spans=spans, final_op_ids=(spans[-1].op_id,),
        timing=TraceTiming(wall_clock_ms=3.0, critical_path_ms=3.0, operator_sum_ms=3.0),
    )


@pytest.fixture
async def seeded(tmp_path: Path) -> DbRegistry:
    db_path = tmp_path / "attr.db"
    store = SQLiteStore(str(db_path))
    await store.init_db()
    await store.save_run(RUN, "attr", json.dumps({"dataset": {"name": "custom"}}))
    await store.save_qrels(RUN, {f"q{i}": {"d1": 1} for i in range(20)})
    traces = []
    for i in range(20):
        traces.append(_trace("pipeA", f"q{i}", with_filter=False))
        traces.append(_trace("pipeB", f"q{i}", with_filter=True))
    await store.save_traces(traces)
    return DbRegistry([str(db_path)])


@pytest.mark.asyncio
async def test_rows_are_per_pipeline_with_pipeline_id(seeded: DbRegistry) -> None:
    client = TestClient(create_app(registry=seeded, enable_uploads=False))
    rows = client.get(f"/dbs/{seeded.default_db_id}/runs/{RUN}/operator-attribution?metric=recall&k=10").json()
    assert rows and all("pipeline_id" in row for row in rows)
    retriever = {row["pipeline_id"]: row for row in rows if row["op_id"] == "retriever"}
    assert set(retriever) == {"pipeA", "pipeB"}, "shared op_id must be attributed per pipeline"
    filter_rows = [row for row in rows if row["op_id"] == "filter_cap"]
    assert {row["pipeline_id"] for row in filter_rows} == {"pipeB"}
    assert filter_rows[0]["n_pairs"] == 20
    # FILTER drops the only relevant doc in every pipeB trace: with-op recall 0, without 1.
    assert filter_rows[0]["delta"] == pytest.approx(-1.0)
    for row in rows:
        if row.get("p_value") is not None:
            assert row["q_value"] is not None and row["q_value"] >= row["p_value"] - 1e-12


@pytest.mark.asyncio
async def test_one_failing_operator_yields_an_error_row_not_a_500(seeded: DbRegistry, monkeypatch) -> None:
    real = dashboard_api.operator_marginal_contribution

    def flaky(traces, *, op_id, **kwargs):
        if op_id == "filter_cap":
            raise RuntimeError("replay exploded")
        return real(traces, op_id=op_id, **kwargs)

    monkeypatch.setattr(dashboard_api, "operator_marginal_contribution", flaky)
    client = TestClient(create_app(registry=seeded, enable_uploads=False))
    response = client.get(f"/dbs/{seeded.default_db_id}/runs/{RUN}/operator-attribution?metric=recall&k=10")
    assert response.status_code == 200
    rows = response.json()
    failed = [row for row in rows if row["op_id"] == "filter_cap"]
    assert len(failed) == 1
    assert failed[0]["result_status"] == "error"
    assert failed[0]["pipeline_id"] == "pipeB"
    assert "RuntimeError: replay exploded" in failed[0]["reason"]
    assert any(row["op_id"] == "retriever" and row["result_status"] != "error" for row in rows)


@pytest.mark.asyncio
async def test_unsupported_metric_is_a_422(seeded: DbRegistry) -> None:
    client = TestClient(create_app(registry=seeded, enable_uploads=False))
    response = client.get(f"/dbs/{seeded.default_db_id}/runs/{RUN}/operator-attribution?metric=bogus&k=10")
    assert response.status_code == 422
