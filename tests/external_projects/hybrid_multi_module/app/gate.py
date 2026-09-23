from __future__ import annotations


class IntentRouter:
    """Chooses the lane set: a query that mentions "lexical" skips the dense lane."""

    def route(self, query: str) -> str:
        return "lexical_only" if "lexical" in query else "hybrid"
