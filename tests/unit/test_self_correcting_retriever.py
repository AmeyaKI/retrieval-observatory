from __future__ import annotations

import sys
from pathlib import Path

from retrieval_observatory.pipeline.factory import _build_import_adapter, build_pipeline_from_config
from retrieval_observatory.types import Query

_ROOT = Path(__file__).resolve().parents[2]
_DEMO_DIR = str(_ROOT / "examples" / "advanced" / "self_correcting_rag_demo")
if _DEMO_DIR not in sys.path:
    sys.path.insert(0, _DEMO_DIR)

_CORPUS = {
    "d1": "Automobile vehicle listings for local dealerships.",
    "d2": "Physician gp appointment scheduling system.",
    "d3": "Quick rapid delivery service for urgent packages.",
    "d4": "Affordable inexpensive furniture for small apartments.",
    "d5": "Soil pH testing helps gardening tips succeed for small yards.",
}

_PIPELINE_CONFIG = {
    "id": "retrieve_critique_retry",
    "stages": [
        {
            "type": "adapter.import",
            "retriever_id": "first_pass",
            "config": {"factory": "critique_retry:build_first_pass_retriever", "k": 5},
        },
        {
            "type": "adapter.import",
            "retriever_id": "critique_retry",
            "config": {
                "factory": "critique_retry:build_critique_retry_reranker",
                "k": 5,
                "confidence_threshold": 0.15,
            },
        },
    ],
}


async def test_first_pass_alone_misses_paraphrased_query():
    stage_cfg = _PIPELINE_CONFIG["stages"][0]
    adapter, _ = _build_import_adapter(stage_cfg, _CORPUS)
    result = adapter.retrieve(Query(text="Where can I buy a cheap car", k=5, query_id="q1"))
    assert result.documents == []


async def test_critique_retry_recovers_relevant_docs_via_query_expansion():
    pipeline = build_pipeline_from_config(_PIPELINE_CONFIG, corpus=_CORPUS)
    result = await pipeline.run(Query(text="Where can I buy a cheap car", k=5, query_id="q1"))
    final = result.snapshots[-1]
    assert {doc.id for doc in final.documents} == {"d1", "d4"}
    assert final.profiling["critique_retried"] == 1.0


async def test_critique_retry_recovers_docs_for_a_different_expansion_path():
    pipeline = build_pipeline_from_config(_PIPELINE_CONFIG, corpus=_CORPUS)
    result = await pipeline.run(Query(text="I need to see a doctor fast", k=5, query_id="q2"))
    final = result.snapshots[-1]
    assert {doc.id for doc in final.documents} == {"d2", "d3"}
    assert final.profiling["critique_retried"] == 1.0


async def test_no_retry_when_first_pass_is_already_confident():
    pipeline = build_pipeline_from_config(_PIPELINE_CONFIG, corpus=_CORPUS)
    result = await pipeline.run(
        Query(text="What soil pH and gardening tips should I use", k=5, query_id="q3")
    )
    final = result.snapshots[-1]
    assert final.profiling["critique_retried"] == 0.0
    assert final.documents[0].id == "d5"
