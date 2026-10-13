"""``retobs evaluate`` exit codes, evidence output, and stream hygiene."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

from retrieval_observatory.cli import app

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
from integration_projects import CORPUS_JSONL, QRELS_LIST_JSONL, QUERIES_JSONL  # noqa: E402


def _data(tmp_path: Path) -> list[str]:
    (tmp_path / "queries.jsonl").write_text(QUERIES_JSONL, encoding="utf-8")
    (tmp_path / "corpus.jsonl").write_text(CORPUS_JSONL, encoding="utf-8")
    (tmp_path / "qrels.jsonl").write_text(QRELS_LIST_JSONL, encoding="utf-8")
    return [
        "--queries", str(tmp_path / "queries.jsonl"), "--corpus", str(tmp_path / "corpus.jsonl"),
        "--qrels", str(tmp_path / "qrels.jsonl"), "--db", str(tmp_path / "results.db"),
    ]


def _broken(tmp_path: Path) -> Path:
    target = tmp_path / "broken.py"
    target.write_text("def retrieve(q):\n    raise RuntimeError('index offline: boom')\n", encoding="utf-8")
    return target


def test_zero_completed_exits_one_and_keeps_json_parseable(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["evaluate", f"{_broken(tmp_path)}:retrieve", "--format", "json", *_data(tmp_path)])
    assert result.exit_code == 1
    report = json.loads(result.stdout)
    assert report["evidence_health"] == "failed"
    assert any("0/4" in reason for reason in report["evidence_reasons"])
    assert "Benchmarking" not in result.stdout
    assert "## Evidence" in result.stderr
    assert "index offline: boom" in result.stderr


def test_zero_completed_terminal_prints_traceback_tail(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["evaluate", f"{_broken(tmp_path)}:retrieve", *_data(tmp_path)])
    assert result.exit_code == 1
    assert "## Evidence" in result.stdout
    tail = result.stdout.split("```")[1].strip().splitlines()
    assert 1 <= len(tail) <= 5
    assert tail[-1].endswith("index offline: boom")


def test_healthy_run_exits_zero_with_progress_on_stderr(tmp_path: Path) -> None:
    target = tmp_path / "good.py"
    target.write_text("def retrieve(q):\n    return [{'id': 'd2', 'score': 1.0}, {'id': 'd3', 'score': 0.5}]\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["evaluate", f"{target}:retrieve", "--format", "json", *_data(tmp_path)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["evidence_health"] == "ready"
    assert "Benchmarking" not in result.stdout


def test_file_target_can_import_its_sibling_package(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    (project / "pkg").mkdir(parents=True)
    (project / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (project / "pkg" / "core.py").write_text("def inner(q):\n    return [{'id': 'd2', 'score': 1.0}]\n", encoding="utf-8")
    (project / "eval_target.py").write_text("from pkg.core import inner\ndef retrieve(q):\n    return inner(q)\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # cwd is not the project; the file's directory must still resolve ``pkg``
    monkeypatch.delitem(sys.modules, "pkg", raising=False)
    result = CliRunner().invoke(app, ["evaluate", f"{project / 'eval_target.py'}:retrieve", "--format", "json", *_data(tmp_path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["evidence_health"] == "ready"


_IN_FLIGHT = """\
import threading, time
_lock = threading.Lock()
_now = 0
def retrieve(q):
    global _now
    with _lock:
        _now += 1
        with open(OUT, "a") as handle:
            handle.write(f"{_now}\\n")
    time.sleep(0.05)
    with _lock:
        _now -= 1
    return [{'id': 'd2', 'score': 1.0}]
"""


def _most_at_once(tmp_path: Path, *extra: str) -> int:
    out = tmp_path / "in_flight.txt"
    target = tmp_path / "counting.py"
    target.write_text(f"OUT = {str(out)!r}\n" + _IN_FLIGHT, encoding="utf-8")
    result = CliRunner().invoke(app, ["evaluate", f"{target}:retrieve", "--format", "json", *extra, *_data(tmp_path)])
    assert result.exit_code == 0, result.output
    return max(int(line) for line in out.read_text(encoding="utf-8").split())


def test_search_is_called_one_question_at_a_time_by_default(tmp_path: Path) -> None:
    assert _most_at_once(tmp_path) == 1


def test_concurrency_option_runs_questions_together(tmp_path: Path) -> None:
    assert _most_at_once(tmp_path, "--concurrency", "4") > 1


def test_timeout_option_lets_a_slow_question_finish(tmp_path: Path) -> None:
    target = tmp_path / "slow.py"
    target.write_text("import time\ndef retrieve(q):\n    time.sleep(0.3)\n    return [{'id': 'd2', 'score': 1.0}]\n", encoding="utf-8")

    too_short = CliRunner().invoke(app, ["evaluate", f"{target}:retrieve", "--format", "json", "--timeout", "0.1", *_data(tmp_path)])
    assert too_short.exit_code == 1
    (tmp_path / "again").mkdir()
    enough = CliRunner().invoke(app, ["evaluate", f"{target}:retrieve", "--format", "json", "--timeout", "5", *_data(tmp_path / "again")])
    assert enough.exit_code == 0, enough.output
    assert json.loads(enough.stdout)["evidence_health"] == "ready"
