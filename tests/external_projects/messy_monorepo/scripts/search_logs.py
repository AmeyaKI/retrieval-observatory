"""Operator utility: grep the service logs for a phrase."""
from __future__ import annotations

import sys
from pathlib import Path


def search(query: str) -> list[str]:
    log = Path("service.log")
    lines = log.read_text(encoding="utf-8").splitlines() if log.is_file() else []
    return [line for line in lines if query in line]


def search_errors(query: str) -> list[str]:
    return [line for line in search(query) if "ERROR" in line]


if __name__ == "__main__":
    print("\n".join(search(" ".join(sys.argv[1:]))))
