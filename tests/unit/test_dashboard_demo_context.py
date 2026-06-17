"""Unit tests for demo context discovery."""
from pathlib import Path

from retrieval_observatory.dashboard.demo_context import (
    find_demo_context_for_registry,
    find_demo_manifest_for_db,
)


def test_find_demo_manifest_for_db(tmp_path: Path) -> None:
    db = tmp_path / "results.db"
    db.touch()
    manifest = {
        "baseline_run_id": "b1",
        "candidate_run_id": "c1",
        "sample_query_id": "q1",
    }
    (tmp_path / "demo_manifest.json").write_text(
        __import__("json").dumps(manifest),
        encoding="utf-8",
    )
    loaded = find_demo_manifest_for_db(str(db))
    assert loaded is not None
    assert loaded["baseline_run_id"] == "b1"


def test_find_demo_context_for_registry(tmp_path: Path) -> None:
    db = tmp_path / "results.db"
    db.touch()
    (tmp_path / "demo_manifest.json").write_text(
        '{"baseline_run_id": "b1", "candidate_run_id": "c1"}',
        encoding="utf-8",
    )
    ctx = find_demo_context_for_registry([str(db)])
    assert ctx.get("baseline_run_id") == "b1"
    assert "db_path" in ctx
