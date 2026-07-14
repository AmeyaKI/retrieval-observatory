from __future__ import annotations

from pathlib import Path

DEFAULT_CONFIG = """db_path: .retobs/results.db
max_queries: 50
baseline_run_id: null
"""


def write_default_config(output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return path
