from __future__ import annotations

import asyncio
from typing import Dict, Optional, Set, Union

from retrieval_observatory.pipeline.multi import MultiStagePipeline
from retrieval_observatory.pipeline.single import SingleStagePipeline
from retrieval_observatory.types import Query

Pipeline = Union[SingleStagePipeline, MultiStagePipeline]


async def validate_id_consistency(
    pipeline: Pipeline,
    queries: list,
    corpus: Dict[str, str],
    n_smoke: int = 5,
) -> None:
    """Run smoke queries and assert retrieved IDs appear in the corpus.

    Raises ValueError with a diagnostic if zero retrieved IDs match corpus IDs.
    This catches the silent zero-recall failure mode (highest-risk hazard).
    """
    smoke_queries = queries[:n_smoke]
    corpus_ids = set(corpus.keys())

    for query in smoke_queries:
        result = await pipeline.run(query)
        if result.status != "OK" or not result.snapshots:
            continue
        retrieved_ids = {d.id for d in result.snapshots[0].documents}
        overlap = retrieved_ids & corpus_ids
        if overlap:
            return  # At least one match found — pipeline is consistent

    # No overlap found across all smoke queries
    sample_retrieved: list = []
    for query in smoke_queries[:2]:
        result = await pipeline.run(query)
        if result.status == "OK" and result.snapshots:
            sample_retrieved.extend(d.id for d in result.snapshots[0].documents[:3])

    sample_corpus = list(corpus_ids)[:5]
    raise ValueError(
        f"ID consistency check failed for pipeline '{pipeline.pipeline_id}'.\n"
        f"None of the retrieved document IDs appear in the corpus.\n"
        f"Sample retrieved IDs: {sample_retrieved[:5]}\n"
        f"Sample corpus IDs:    {sample_corpus}\n"
        "Check that your retriever returns the same document IDs as your corpus."
    )
