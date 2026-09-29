from __future__ import annotations

from typing import Any

from ticket_rag import fusion
from ticket_rag.lanes.keyword import keyword_search
from ticket_rag.lanes.vector import vector_search


def retrieve(query: str) -> list[dict[str, Any]]:
    return fusion.fuse_results(keyword_search(query), vector_search(query))
