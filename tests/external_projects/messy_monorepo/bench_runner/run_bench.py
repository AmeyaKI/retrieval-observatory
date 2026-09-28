"""Benchmark driver: runs the pipeline over the bench queries."""
from __future__ import annotations

import sys

sys.path.insert(0, "services/search")

from retrieval_app.pipeline import retrieve  # noqa: E402


def search(query: str) -> list[dict[str, object]]:
    return retrieve(query)


def search_all(queries: list[str]) -> list[list[dict[str, object]]]:
    return [search(query) for query in queries]
