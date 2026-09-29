"""Release gates over evaluation results."""
from __future__ import annotations

from typing import Any


def evaluate_gates(results: list[dict[str, Any]]) -> dict[str, str]:
    return {"recall": "pass" if all(row.get("recall", 0) >= 0.5 for row in results) else "fail"}
