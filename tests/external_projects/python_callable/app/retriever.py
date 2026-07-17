from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def source(query: str) -> list[dict[str, Any]]:
    documents = [
        {
            "id": "d-callable-current",
            "score": 0.91,
            "rank": 1,
            "metadata": {"source": Path("data/corpus.jsonl"), "captured_at": datetime(2026, 7, 16, tzinfo=timezone.utc)},
        },
        {
            "id": "d-callable-history",
            "score": 0.72,
            "rank": 2,
            "metadata": {"source": Path("data/corpus.jsonl"), "captured_at": datetime(2026, 7, 16, tzinfo=timezone.utc)},
        },
    ]
    return documents if "history" not in query else list(reversed(documents))


def retrieve(query: str) -> list[dict[str, Any]]:
    return source(query)


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, (Path, datetime)):
        return str(value)
    return value


if __name__ == "__main__":
    output = [
        {"query_id": "q-callable-1", "documents": retrieve("current policy")},
        {"query_id": "q-callable-2", "documents": retrieve("current policy history")},
    ]
    print(json.dumps(_json_value(output), sort_keys=True))
