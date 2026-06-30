from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Optional, Set

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

    async def gold_reachable_via_edge(
        self,
        retrieved_doc_ids: List[str],
        gold_doc_id: str,
        edge_type: Optional[EdgeType] = None,
        max_hops: int = 1,
    ) -> bool:
        reachable = await self.reachable(retrieved_doc_ids, max_hops=max_hops, edge_type=edge_type)
        return gold_doc_id in reachable
