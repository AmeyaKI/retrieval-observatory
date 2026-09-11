from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMQueryGenerator(Protocol):
    """Protocol for LLM-based query generation."""

    async def generate(self, prompt: str) -> str:
        """Generate text from a prompt and return the raw response."""
        ...
