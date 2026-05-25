import os
import tempfile

import pytest

from retrieval_observatory.datasets.llm_judge import LLMJudgeDataset, _GradeCache, _parse_grade
from retrieval_observatory.types import Document, PipelineResult, Query, StageSnapshot


class AlwaysRelevantJudge:
    async def judge(self, query: str, document: str) -> int:
        return 2  # always highly relevant


class NeverRelevantJudge:
    async def judge(self, query: str, document: str) -> int:
        return 0


def _make_result(query_id: str, pipeline_id: str, doc_ids: list) -> PipelineResult:
    docs = [Document(id=did, text=f"text of {did}", score=1.0, rank=i + 1) for i, did in enumerate(doc_ids)]
    snap = StageSnapshot(stage_index=0, stage_id="r1", documents=docs, latency_ms=1.0)
    return PipelineResult(
        query_id=query_id,
        pipeline_id=pipeline_id,
        snapshots=[snap],
        total_latency_ms=1.0,
        status="OK",
    )


def test_parse_grade():
    assert _parse_grade("2") == 2
    assert _parse_grade("  1  ") == 1
    assert _parse_grade("Grade: 0") == 0
    assert _parse_grade("nonsense") == 0


def test_grade_cache_roundtrip(tmp_path):
    cache = _GradeCache(str(tmp_path / "test_cache.db"))
    assert cache.get("q1", "d1") is None
    cache.set("q1", "d1", 2)
    assert cache.get("q1", "d1") == 2
    cache.set("q1", "d1", 0)
    assert cache.get("q1", "d1") == 0  # update in place


@pytest.mark.asyncio
async def test_judge_results_all_relevant(tmp_path):
    queries = [Query(text="test query", k=5, query_id="q1")]
    dataset = LLMJudgeDataset(
        queries=queries,
        judge=AlwaysRelevantJudge(),
        cache_path=str(tmp_path / "cache.db"),
    )
    results = [_make_result("q1", "p1", ["d1", "d2", "d3"])]
    qrels = await dataset.judge_results(results)

    assert "q1" in qrels
    assert qrels["q1"] == {"d1", "d2", "d3"}


@pytest.mark.asyncio
async def test_judge_results_none_relevant(tmp_path):
    queries = [Query(text="test query", k=5, query_id="q1")]
    dataset = LLMJudgeDataset(
        queries=queries,
        judge=NeverRelevantJudge(),
        cache_path=str(tmp_path / "cache.db"),
    )
    results = [_make_result("q1", "p1", ["d1", "d2"])]
    qrels = await dataset.judge_results(results)

    assert "q1" not in qrels  # no relevant docs


@pytest.mark.asyncio
async def test_judge_cache_hit_skips_judge_calls(tmp_path):
    call_count = 0

    class CountingJudge:
        async def judge(self, query: str, document: str) -> int:
            nonlocal call_count
            call_count += 1
            return 2

    queries = [Query(text="test", k=5, query_id="q1")]
    cache_path = str(tmp_path / "cache.db")
    dataset = LLMJudgeDataset(queries=queries, judge=CountingJudge(), cache_path=cache_path)

    results = [_make_result("q1", "p1", ["d1", "d2"])]

    # First call: 2 judge calls
    await dataset.judge_results(results)
    assert call_count == 2

    # Second call: cache hits → 0 new judge calls
    dataset2 = LLMJudgeDataset(queries=queries, judge=CountingJudge(), cache_path=cache_path)
    call_count = 0
    await dataset2.judge_results(results)
    assert call_count == 0


def test_estimate_budget():
    queries = [Query(text="q", k=10, query_id=f"q{i}") for i in range(10)]
    dataset = LLMJudgeDataset(queries=queries, judge=AlwaysRelevantJudge())
    budget = dataset.estimate_budget(avg_docs_per_query=20)
    assert budget["estimated_calls"] == 200
    assert budget["queries"] == 10
