from __future__ import annotations

import asyncio
import os
import sqlite3
from typing import Dict, List, Optional, Protocol, Set, runtime_checkable

from retrieval_observatory.types import PipelineResult, Query

_JUDGE_PROMPT = """Rate the relevance of the following document to the query on a scale of 0 to 2.
0 = not relevant
1 = somewhat relevant
2 = highly relevant

Query: {query}
Document: {document}

Respond with a single digit (0, 1, or 2) and nothing else."""


@runtime_checkable
class LLMJudge(Protocol):
    async def judge(self, query: str, document: str) -> int:
        """Return relevance grade: 0=not relevant, 1=somewhat, 2=highly relevant."""
        ...


class GeminiJudge:
    """Default judge using Google AI Studio's free Gemini Flash tier."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.0-flash",
    ):
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not self._api_key:
            raise ValueError(
                "GeminiJudge requires a Google API key. "
                "Pass api_key= or set the GOOGLE_API_KEY environment variable."
            )
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import google.generativeai as genai
            except ImportError as e:
                raise ImportError(
                    "GeminiJudge requires google-generativeai. "
                    "Install with: pip install retrieval-observatory[llm-judge]"
                ) from e
            genai.configure(api_key=self._api_key)
            self._client = genai.GenerativeModel(self.model)
        return self._client

    async def judge(self, query: str, document: str) -> int:
        client = self._get_client()
        prompt = _JUDGE_PROMPT.format(query=query, document=document[:2000])
        response = await asyncio.to_thread(client.generate_content, prompt)
        return _parse_grade(response.text.strip())


class OpenAIJudge:
    """Judge using OpenAI's API (e.g. gpt-4o-mini)."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model

    async def judge(self, query: str, document: str) -> int:
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "OpenAIJudge requires openai. "
                "Install with: pip install retrieval-observatory[llm-judge]"
            ) from e
        client = AsyncOpenAI(api_key=self._api_key)
        response = await client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": _JUDGE_PROMPT.format(
                query=query, document=document[:2000]
            )}],
            max_tokens=1,
        )
        return _parse_grade(response.choices[0].message.content.strip())


class AnthropicJudge:
    """Judge using Anthropic's API (e.g. claude-haiku)."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-haiku-4-5-20251001"):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model

    async def judge(self, query: str, document: str) -> int:
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "AnthropicJudge requires anthropic. "
                "Install with: pip install retrieval-observatory[llm-judge]"
            ) from e
        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        response = await client.messages.create(
            model=self.model,
            max_tokens=1,
            messages=[{"role": "user", "content": _JUDGE_PROMPT.format(
                query=query, document=document[:2000]
            )}],
        )
        return _parse_grade(response.content[0].text.strip())


def _parse_grade(text: str) -> int:
    for char in text:
        if char in "012":
            return int(char)
    return 0  # default: not relevant if unparseable


class _GradeCache:
    """Lightweight SQLite cache for (query_id, doc_id) → grade."""

    def __init__(self, cache_path: str):
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(cache_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS llm_judge_cache "
            "(key TEXT PRIMARY KEY, grade INTEGER NOT NULL)"
        )
        self._conn.commit()

    def get(self, query_id: str, doc_id: str) -> Optional[int]:
        row = self._conn.execute(
            "SELECT grade FROM llm_judge_cache WHERE key = ?",
            (f"{query_id}::{doc_id}",),
        ).fetchone()
        return row[0] if row else None

    def set(self, query_id: str, doc_id: str, grade: int) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO llm_judge_cache (key, grade) VALUES (?, ?)",
            (f"{query_id}::{doc_id}", grade),
        )
        self._conn.commit()


class LLMJudgeDataset:
    """Generates synthetic qrels by asking an LLM to grade retrieved documents.

    Use when there is no ground-truth corpus. The judge grades each retrieved
    document 0–2; documents with grade > 0 become "relevant" for that query.
    All grades are cached — re-running is free after the first pass.
    """

    def __init__(
        self,
        queries: List[Query],
        judge: LLMJudge,
        cache_path: str = ".retobs/llm_judge_cache.db",
        batch_size: int = 10,
    ):
        self.queries = queries
        self._judge = judge
        self._cache = _GradeCache(cache_path)
        self.batch_size = batch_size

    def estimate_budget(self, avg_docs_per_query: int = 20) -> dict:
        """Print and return estimated API call count before judging."""
        n = len(self.queries)
        total_calls = n * avg_docs_per_query
        # Very rough estimate: ~200 tokens per call at $0 (Gemini free tier)
        return {
            "queries": n,
            "docs_per_query": avg_docs_per_query,
            "estimated_calls": total_calls,
            "note": "GeminiJudge uses the free Google AI Studio tier (no cost for standard usage)",
        }

    async def judge_results(
        self,
        results: List[PipelineResult],
        queries_by_id: Optional[Dict[str, Query]] = None,
    ) -> Dict[str, Set[str]]:
        """Grade retrieved documents and return synthetic qrels.

        Returns {query_id: {doc_id for docs with grade > 0}}
        """
        queries_map = {q.query_id: q for q in self.queries}
        if queries_by_id:
            queries_map.update(queries_by_id)

        qrels: Dict[str, Set[str]] = {}

        # Collect all (query_id, doc_id, text) pairs not yet cached
        tasks = []
        for result in results:
            if result.status != "OK" or not result.snapshots:
                continue
            query = queries_map.get(result.query_id)
            if query is None:
                continue
            for doc in result.snapshots[-1].documents:  # grade final-stage output
                cached = self._cache.get(result.query_id, doc.id)
                if cached is not None:
                    if cached > 0:
                        qrels.setdefault(result.query_id, set()).add(doc.id)
                else:
                    tasks.append((result.query_id, doc.id, query.text, doc.text))

        # Run uncached judgements in batches
        for i in range(0, len(tasks), self.batch_size):
            batch = tasks[i : i + self.batch_size]
            grades = await asyncio.gather(
                *[self._judge.judge(query_text, doc_text) for _, _, query_text, doc_text in batch]
            )
            for (query_id, doc_id, _, _), grade in zip(batch, grades):
                self._cache.set(query_id, doc_id, grade)
                if grade > 0:
                    qrels.setdefault(query_id, set()).add(doc_id)

        return qrels
