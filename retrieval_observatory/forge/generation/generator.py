from __future__ import annotations

import asyncio
import hashlib
import os
from typing import Dict, List, Optional

from retrieval_observatory.forge.generation.prompts import (
    format_adversarial,
    format_paraphrase,
    format_temporal,
)
from retrieval_observatory.forge.types import CorpusScenario, SyntheticQuery


def _query_id(scenario_id: str, query_type: str, text: str) -> str:
    """Content-derived query id (not random): identical scenario/type/text produces the
    same id. LLM-generated text is not itself deterministic across separate calls, but
    tying the id to the actual generated text (rather than a random uuid) means two
    genuinely identical queries -- e.g. a low-temperature or cached regeneration -- are
    recognized as the same query instead of silently aliased under different ids."""
    digest = hashlib.sha256(f"{scenario_id}|{query_type}|{text}".encode("utf-8")).hexdigest()[:12]
    return f"forge_{digest}"


# ---------------------------------------------------------------------------
# Provider wrappers — same pattern as datasets/llm_judge.py
# ---------------------------------------------------------------------------

class GeminiGenerator:
    """Query generator using Google Gemini Flash (free tier by default)."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash"):
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not self._api_key:
            raise ValueError(
                "GeminiGenerator requires a Google API key. "
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
                    "GeminiGenerator requires google-generativeai. "
                    "Install with: pip install retrieval-observatory[llm-judge]"
                ) from e
            genai.configure(api_key=self._api_key)
            self._client = genai.GenerativeModel(self.model)
        return self._client

    async def generate(self, prompt: str) -> str:
        client = self._get_client()
        response = await asyncio.to_thread(client.generate_content, prompt)
        return response.text.strip()


class OpenAIGenerator:
    """Query generator using OpenAI API."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model

    async def generate(self, prompt: str) -> str:
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "OpenAIGenerator requires openai. "
                "Install with: pip install retrieval-observatory[llm-judge]"
            ) from e
        client = AsyncOpenAI(api_key=self._api_key)
        response = await client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()


class AnthropicGenerator:
    """Query generator using Anthropic API."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-haiku-4-5-20251001"):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model

    async def generate(self, prompt: str) -> str:
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "AnthropicGenerator requires anthropic. "
                "Install with: pip install retrieval-observatory[llm-judge]"
            ) from e
        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        response = await client.messages.create(
            model=self.model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()


def _make_generator(provider: str, api_key: Optional[str], model: Optional[str]):
    if provider == "gemini":
        try:
            import google.generativeai  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "GeminiGenerator requires google-generativeai. "
                "Install with: pip install retrieval-observatory[llm-judge]"
            ) from exc
        return GeminiGenerator(api_key=api_key, model=model or "gemini-2.0-flash")
    if provider == "openai":
        try:
            import openai  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "OpenAIGenerator requires openai. "
                "Install with: pip install retrieval-observatory[llm-judge]"
            ) from exc
        return OpenAIGenerator(api_key=api_key, model=model or "gpt-4o-mini")
    if provider == "anthropic":
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "AnthropicGenerator requires anthropic. "
                "Install with: pip install retrieval-observatory[llm-judge]"
            ) from exc
        return AnthropicGenerator(api_key=api_key, model=model or "claude-haiku-4-5-20251001")
    raise ValueError(f"Unknown provider {provider!r}. Choose from: gemini, openai, anthropic")


def _parse_lines(raw: str, n: int) -> List[str]:
    """Parse LLM output into a list of at most n non-empty lines."""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    # Strip common prefixes: "1. ", "- ", "* "
    cleaned = []
    for ln in lines:
        ln = ln.lstrip("0123456789.-*) ").strip()
        if ln and len(ln) > 5:
            cleaned.append(ln)
    return cleaned[:n]


# ---------------------------------------------------------------------------
# Main ForgeGenerator orchestrator
# ---------------------------------------------------------------------------

class ForgeGenerator:
    """Generates synthetic retrieval queries from corpus scenarios using an LLM.

    Wraps a provider-specific generator and applies budget tracking to avoid
    runaway API costs.
    """

    def __init__(self, generator, budget: int = 500):
        self._gen = generator
        self.budget = budget
        self._call_count = 0

    @classmethod
    def from_provider(
        cls,
        provider: str = "gemini",
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        budget: int = 500,
    ) -> "ForgeGenerator":
        gen = _make_generator(provider, api_key, model)
        return cls(gen, budget=budget)

    @property
    def calls_used(self) -> int:
        return self._call_count

    @property
    def budget_remaining(self) -> int:
        return max(0, self.budget - self._call_count)

    def _check_budget(self) -> None:
        if self._call_count >= self.budget:
            raise RuntimeError(
                f"Test Sets generation budget exhausted ({self.budget} LLM calls). "
                "Increase --budget or reduce --n-queries."
            )

    async def _generate_queries(self, prompt: str, n: int) -> List[str]:
        self._check_budget()
        self._call_count += 1
        raw = await self._gen.generate(prompt)
        return _parse_lines(raw, n)

    async def generate_from_scenario(
        self,
        scenario: CorpusScenario,
        corpus: Dict[str, Dict],
        query_types: List[str],
        n_per_type: int = 3,
    ) -> List[SyntheticQuery]:
        """Generate queries for a single scenario across requested query types."""
        queries: List[SyntheticQuery] = []

        anchor_ids = scenario.anchor_doc_ids
        if not anchor_ids:
            return queries

        # Use first anchor doc as primary source for paraphrase/adversarial
        primary_id = anchor_ids[0]
        primary_doc = corpus.get(primary_id, {})
        primary_text = primary_doc.get("text", "")

        for query_type in query_types:
            if self.budget_remaining == 0:
                break

            try:
                if query_type == "paraphrase":
                    prompt = format_paraphrase(primary_text, n=n_per_type)
                    raw_queries = await self._generate_queries(prompt, n_per_type)
                    for text in raw_queries:
                        queries.append(SyntheticQuery(
                            query_id=_query_id(scenario.scenario_id, "paraphrase", text),
                            text=text,
                            scenario_id=scenario.scenario_id,
                            query_type="paraphrase",
                            positive_doc_ids=[primary_id],
                            metadata={"generation_method": "llm", "generation_model": getattr(self._gen, "model", None), "label_method": "extractive_source_document"},
                        ))

                elif query_type == "temporal" and scenario.scenario_type == "temporal" and len(anchor_ids) >= 2:
                    id_a, id_b = anchor_ids[0], anchor_ids[1]
                    doc_a = corpus.get(id_a, {})
                    doc_b = corpus.get(id_b, {})
                    year_a = scenario.metadata.get("year_a", 2020)
                    year_b = scenario.metadata.get("year_b", 2023)
                    prompt = format_temporal(
                        doc_a.get("text", ""), doc_b.get("text", ""),
                        year_a, year_b, n=n_per_type,
                    )
                    raw_queries = await self._generate_queries(prompt, n_per_type)
                    for text in raw_queries:
                        queries.append(SyntheticQuery(
                            query_id=_query_id(scenario.scenario_id, "temporal", text),
                            text=text,
                            scenario_id=scenario.scenario_id,
                            query_type="temporal",
                            positive_doc_ids=[id_b],  # later doc is the "correct" answer
                            failure_category="temporal_confusion",
                            metadata={"generation_method": "llm", "generation_model": getattr(self._gen, "model", None), "label_method": "extractive_source_document"},
                        ))

                elif query_type == "adversarial":
                    prompt = format_adversarial(primary_text, n=n_per_type)
                    raw_queries = await self._generate_queries(prompt, n_per_type)
                    for text in raw_queries:
                        queries.append(SyntheticQuery(
                            query_id=_query_id(scenario.scenario_id, "adversarial", text),
                            text=text,
                            scenario_id=scenario.scenario_id,
                            query_type="adversarial",
                            positive_doc_ids=[primary_id],
                            failure_category="adversarial",
                            metadata={"generation_method": "llm", "generation_model": getattr(self._gen, "model", None), "label_method": "extractive_source_document"},
                        ))

            except Exception:
                # Don't let one failed generation abort the whole run
                continue

        return queries

    async def generate_dataset(
        self,
        scenarios: List[CorpusScenario],
        corpus: Dict[str, Dict],
        query_types: List[str] = ("paraphrase",),
        n_per_type: int = 3,
    ) -> List[SyntheticQuery]:
        """Generate queries for a list of scenarios."""
        all_queries: List[SyntheticQuery] = []
        for scenario in scenarios:
            if self.budget_remaining == 0:
                break
            new_queries = await self.generate_from_scenario(
                scenario, corpus, query_types, n_per_type
            )
            all_queries.extend(new_queries)
        return all_queries
