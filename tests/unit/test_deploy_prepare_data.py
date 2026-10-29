"""The hosted-demo bake makes build paths relative and refuses a database that still leaks one."""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "prepare_data", Path(__file__).resolve().parents[2] / "deploy" / "prepare_data.py"
)
prepare_data = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(prepare_data)


def _db(path: Path, *values: str) -> Path:
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE analysis_records (record_id TEXT, payload_json TEXT, version INTEGER)")
        con.executemany("INSERT INTO analysis_records VALUES (?, ?, 1)", [(str(i), v) for i, v in enumerate(values)])
    return path


def test_paths_under_a_build_directory_become_relative(tmp_path: Path) -> None:
    build = tmp_path / "build" / "project"
    db = _db(
        tmp_path / "x.db",
        f'{{"project_root": "{build}", "db_path": "{build}/.retobs/results.db"}}',
        '{"scope": "4 judged ids from ' + f'{build}/data/qrels.jsonl"' + "}",
    )

    assert prepare_data.relativize(db, [build]) == 3

    with sqlite3.connect(db) as con:
        payloads = [row[0] for row in con.execute("SELECT payload_json FROM analysis_records ORDER BY record_id")]
    assert payloads == [
        '{"project_root": ".", "db_path": ".retobs/results.db"}',
        '{"scope": "4 judged ids from data/qrels.jsonl"}',
    ]
    assert prepare_data.leaks(db) == []


def test_a_left_over_absolute_path_or_email_is_reported(tmp_path: Path) -> None:
    db = _db(tmp_path / "y.db", '{"cache": "/home/someone/.cache/x"}', '{"owner": "someone@example.com"}', '{"note": "a/b and 1/2"}')

    found = prepare_data.leaks(db)

    assert len(found) == 2
    assert any("/home/someone/.cache/x" in item for item in found)
    assert any("someone@example.com" in item for item in found)
