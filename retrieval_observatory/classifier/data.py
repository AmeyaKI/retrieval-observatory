from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from retrieval_observatory.classifier.labels import to_training_class


@dataclass
class LabeledQuery:
    query_text: str
    query_id: str
    run_id: str
    bucket: str
    training_class: str


def normalize_query_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


async def load_labeled_queries(store: Any, dataset_name: str) -> List[LabeledQuery]:
    """Load deduplicated labeled queries for a dataset from past benchmark runs."""
    runs = await store.list_runs_for_dataset(dataset_name)
    if not runs:
        return []

    run_ids = [r["run_id"] for r in runs]
    labeled_rows = await store.get_labeled_query_rows(run_ids)

    # query_id -> list of (run_id, bucket)
    by_key: Dict[str, List[tuple]] = {}
    text_by_run_query: Dict[tuple, str] = {}

    for run_id in run_ids:
        for row in await store.get_run_queries(run_id):
            text_by_run_query[(row["run_id"], row["query_id"])] = row["query_text"]

    raw: List[LabeledQuery] = []
    for row in labeled_rows:
        key = (row["run_id"], row["query_id"])
        text = text_by_run_query.get(key)
        if not text:
            continue
        training_class = to_training_class(row["difficulty_bucket"])
        if training_class is None:
            continue
        raw.append(
            LabeledQuery(
                query_text=text,
                query_id=row["query_id"],
                run_id=row["run_id"],
                bucket=row["difficulty_bucket"],
                training_class=training_class,
            )
        )

    # Dedup by normalized text; mode of class across runs
    grouped: Dict[str, List[LabeledQuery]] = {}
    for item in raw:
        norm = normalize_query_text(item.query_text)
        grouped.setdefault(norm, []).append(item)

    deduped: List[LabeledQuery] = []
    for norm, items in grouped.items():
        class_counts = Counter(i.training_class for i in items)
        mode_class = class_counts.most_common(1)[0][0]
        representative = items[0]
        deduped.append(
            LabeledQuery(
                query_text=representative.query_text,
                query_id=representative.query_id,
                run_id=representative.run_id,
                bucket=representative.bucket,
                training_class=mode_class,
            )
        )
    return deduped


def class_distribution(samples: List[LabeledQuery]) -> Dict[str, int]:
    counts: Dict[str, int] = {"easy": 0, "medium": 0, "hard": 0}
    for s in samples:
        counts[s.training_class] = counts.get(s.training_class, 0) + 1
    return counts


def check_minimum_samples(
    samples: List[LabeledQuery],
    min_total: int = 30,
    min_per_class: int = 5,
) -> Optional[str]:
    if len(samples) < min_total:
        return f"Need at least {min_total} labeled queries, found {len(samples)}"
    dist = class_distribution(samples)
    present = {cls: count for cls, count in dist.items() if count > 0}
    if len(present) < 2:
        return f"Need labels in at least 2 difficulty classes, found {len(present)}"
    for cls, count in present.items():
        if count < min_per_class:
            return f"Class '{cls}' has {count} samples (minimum {min_per_class})"
    return None
