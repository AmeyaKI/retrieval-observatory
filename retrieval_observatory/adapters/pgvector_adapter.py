from __future__ import annotations

import time

from retrieval_observatory.types import Document, Query, RetrievalResult


class PgvectorAdapter:
    """Queries a pgvector table directly via asyncpg.

    Supports ``Query.filters['doc_ids']`` as a SQL ``IN`` clause on the id column.
    """

    supports_filters: bool = True

    def __init__(
        self,
        connection_string: str,
        table: str,
        embedding_column: str,
        id_column: str = "id",
        text_column: str = "text",
        retriever_id: str = "pgvector",
        embedding_fn=None,
    ):
        self.retriever_id = retriever_id
        self._conn_str = connection_string
        self._table = table
        self._embedding_col = embedding_column
        self._id_col = id_column
        self._text_col = text_column
        self._embed = embedding_fn  # callable: str → List[float]

    async def retrieve(self, query: Query) -> RetrievalResult:
        try:
            import asyncpg
        except ImportError as e:
            raise ImportError(
                "pgvector adapter requires asyncpg. Install with: pip install retrieval-observatory[pgvector]"
            ) from e

        if self._embed is None:
            raise RuntimeError("PgvectorAdapter requires an embedding_fn to vectorize queries.")

        query_vec = self._embed(query.text)
        vec_str = "[" + ",".join(str(v) for v in query_vec) + "]"

        where_clauses: list[str] = []
        params: list = [vec_str, query.k]

        if query.filters:
            doc_ids = query.filters.get("doc_ids")
            if doc_ids:
                params.append(list(doc_ids))
                where_clauses.append(f"{self._id_col} = ANY(${len(params)}::text[])")

            for key, value in query.filters.items():
                if key == "doc_ids":
                    continue
                params.append(str(value))
                where_clauses.append(f"metadata->>'{key}' = ${len(params)}")

        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        sql = f"""
            SELECT {self._id_col}, {self._text_col},
                   1 - ({self._embedding_col} <=> $1::vector) AS score
            FROM {self._table}
            {where_sql}
            ORDER BY {self._embedding_col} <=> $1::vector
            LIMIT $2
        """

        start = time.perf_counter()
        conn = await asyncpg.connect(self._conn_str)
        try:
            rows = await conn.fetch(sql, *params)
        finally:
            await conn.close()
        latency_ms = (time.perf_counter() - start) * 1000

        documents = [
            Document(
                id=str(row[self._id_col]),
                text=row[self._text_col],
                score=float(row["score"]),
                rank=rank,
            )
            for rank, row in enumerate(rows, start=1)
        ]

        return RetrievalResult(
            documents=documents,
            latency_ms=latency_ms,
            retriever_id=self.retriever_id,
            profiling={"network_ms": latency_ms, "compute_ms": 0.0, "retries": 0.0},
        )
