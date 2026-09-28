from __future__ import annotations

from typing import Any

ARCHIVED = {"d-archive"}


def anchor_filter(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [candidate for candidate in candidates if candidate["id"] not in ARCHIVED]
