from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional, Set, Union

EdgeType = Literal["thread_sibling", "entity_link", "reference", "action_item", "deadline", "custom"]


@dataclass
class DocEdge:
    src_doc_id: str
    dst_doc_id: str
    edge_type: EdgeType
    weight: float = 1.0


class EdgeStore:
    def __init__(self, store) -> None:
        self._store = store

    async def add_edge(self, src_doc_id: str, dst_doc_id: str, edge_type: EdgeType, weight: float = 1.0) -> None:
        await self._store.save_doc_edge(src_doc_id, dst_doc_id, edge_type, weight)

    async def neighbors(self, doc_id: str, edge_type: Optional[EdgeType] = None) -> List[DocEdge]:
        rows = await self._store.get_doc_neighbors(doc_id, edge_type=edge_type)
        return [
            DocEdge(
                src_doc_id=row["src_doc_id"],
                dst_doc_id=row["dst_doc_id"],
                edge_type=row["edge_type"],
                weight=float(row["weight"]),
            )
            for row in rows
        ]

    async def reachable(self, start_doc_ids: List[str], max_hops: int = 1, edge_type: Optional[EdgeType] = None) -> Set[str]:
        frontier: Set[str] = set(start_doc_ids)
        visited: Set[str] = set(start_doc_ids)
        for _ in range(max_hops):
            next_frontier: Set[str] = set()
            for doc_id in frontier:
                for edge in await self.neighbors(doc_id, edge_type=edge_type):
                    if edge.dst_doc_id not in visited:
                        visited.add(edge.dst_doc_id)
                        next_frontier.add(edge.dst_doc_id)
            frontier = next_frontier
            if not frontier:
                break
        return visited

    async def add_edges_from_records(self, records: List[dict]) -> int:
        """Bulk-add edges from dicts with ``src``, ``dst``, ``type``, and optional ``weight``."""
        count = 0
        for rec in records:
            await self.add_edge(
                src_doc_id=str(rec["src"]),
                dst_doc_id=str(rec["dst"]),
                edge_type=rec.get("type", "custom"),
                weight=float(rec.get("weight", 1.0)),
            )
            count += 1
        return count

    async def gold_reachable_via_edge(
        self,
        retrieved_doc_ids: List[str],
        gold_doc_id: str,
        edge_type: Optional[EdgeType] = None,
        max_hops: int = 1,
    ) -> bool:
        reachable = await self.reachable(retrieved_doc_ids, max_hops=max_hops, edge_type=edge_type)
        return gold_doc_id in reachable


async def load_graph_corpus(path: Union[str, Path], edge_store: EdgeStore) -> int:
    """Load edges from a JSONL file into an :class:`EdgeStore`.

    Each line must be a JSON object with keys ``src``, ``dst``, ``type``, and
    optional ``weight`` (defaults to 1.0).  Returns the number of edges loaded.
    """
    records: List[dict] = []
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return await edge_store.add_edges_from_records(records)
