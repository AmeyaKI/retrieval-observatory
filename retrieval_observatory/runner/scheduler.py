from __future__ import annotations

import random
from typing import List, Tuple


def interleave_tasks(
    pipeline_ids: List[str],
    query_ids: List[str],
    seed: int | None = None,
) -> List[Tuple[str, str]]:
    """Return shuffled (pipeline_id, query_id) pairs.

    Randomizing order distributes warmup effects evenly across pipelines
    instead of running all queries for pipeline A before pipeline B.
    """
    tasks = [(pid, qid) for pid in pipeline_ids for qid in query_ids]
    rng = random.Random(seed)
    rng.shuffle(tasks)
    return tasks
