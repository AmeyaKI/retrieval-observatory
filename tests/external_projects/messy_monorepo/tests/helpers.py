from __future__ import annotations


def fake_search(query: str) -> list[dict[str, str]]:
    return [{"id": "fake", "text": query}]
