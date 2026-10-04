"""Commands run under the watcher; every Python process they start reports what it saw."""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from retrieval_observatory.integrations.watch import WATCH_FILE, watch_commands

APP = '''
def lexical(query):
    return [{"id": "a"}, {"id": "b"}]


def screen(items):
    return [item for item in items if item["id"] != "b"]


def retrieve(query):
    return screen(lexical(query))
'''

PY = shlex.quote(sys.executable)


def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "pipeline.py").write_text(APP)
    return root


def symbols(process: dict) -> set[str]:
    return {call["symbol"] for call in process["calls"]}


def test_one_command_is_watched_and_written_to_the_project(tmp_path: Path) -> None:
    root = project(tmp_path)
    command = f"{PY} -c \"from app.pipeline import retrieve; retrieve('q')\""
    result = watch_commands(root, [command])
    payload = json.loads((root / WATCH_FILE).read_text())
    assert payload == result.to_payload()
    entry = payload["commands"][0]
    assert entry["command"] == command and entry["exit_code"] == 0 and entry["failure"] is None
    assert symbols(entry["processes"][0]) == {"retrieve", "lexical", "screen"}


def test_a_child_python_process_is_watched_too(tmp_path: Path) -> None:
    root = project(tmp_path)
    inner = [sys.executable, "-c", "from app.pipeline import retrieve; retrieve('q')"]
    command = f"{PY} -c {shlex.quote(f'import subprocess; subprocess.run({inner!r}, check=True)')}"
    entry = watch_commands(root, [command]).to_payload()["commands"][0]
    assert entry["exit_code"] == 0, entry["failure"]
    processes = entry["processes"]
    assert any(symbols(process) == {"retrieve", "lexical", "screen"} for process in processes)


def test_a_failing_command_reports_exit_code_and_stderr_and_keeps_what_was_recorded(tmp_path: Path) -> None:
    root = project(tmp_path)
    command = f"{PY} -c \"from app.pipeline import retrieve; retrieve('q'); raise SystemExit('boom')\""
    entry = watch_commands(root, [command]).to_payload()["commands"][0]
    assert entry["exit_code"] == 1
    assert "boom" in entry["failure"]
    assert symbols(entry["processes"][0]) == {"retrieve", "lexical", "screen"}


def test_python_started_without_site_is_reported_plainly(tmp_path: Path) -> None:
    root = project(tmp_path)
    command = f"{PY} -S -c \"import sys; sys.path.insert(0, '.'); from app.pipeline import retrieve; retrieve('q')\""
    entry = watch_commands(root, [command]).to_payload()["commands"][0]
    assert entry["processes"] == []
    assert "watcher never started" in entry["failure"]


def test_a_project_sitecustomize_still_runs(tmp_path: Path, monkeypatch) -> None:
    root = project(tmp_path)
    (root / "site_extra").mkdir()
    (root / "site_extra" / "sitecustomize.py").write_text("import os\nos.environ['PROJECT_SITE_RAN'] = '1'\n")
    # The project's own PYTHONPATH stays; retobs only prepends its watcher directory.
    monkeypatch.setenv("PYTHONPATH", str(root / "site_extra"))
    command = (
        f"{PY} -c \"import os; from app.pipeline import retrieve; retrieve('q'); "
        "assert os.environ.get('PROJECT_SITE_RAN') == '1'\""
    )
    entry = watch_commands(root, [command]).to_payload()["commands"][0]
    assert entry["exit_code"] == 0, entry["failure"]
    assert symbols(entry["processes"][0]) == {"retrieve", "lexical", "screen"}


def test_a_timeout_is_reported(tmp_path: Path) -> None:
    root = project(tmp_path)
    entry = watch_commands(root, [f"{PY} -c \"import time; time.sleep(5)\""], timeout_s=0.5).to_payload()["commands"][0]
    assert entry["failure"].startswith("timed out after 0.5s")


def test_a_timed_out_command_still_reports_what_it_watched(tmp_path: Path) -> None:
    root = project(tmp_path)
    command = f"{PY} -c \"import time; from app.pipeline import retrieve; retrieve('q'); time.sleep(30)\""
    entry = watch_commands(root, [command], timeout_s=2).to_payload()["commands"][0]
    assert entry["failure"].startswith("timed out after 2s")
    assert "never started" not in entry["failure"]
    assert symbols(entry["processes"][0]) == {"retrieve", "lexical", "screen"}


def test_a_watcher_error_and_an_incomplete_record_are_reported_beside_the_records_that_were_written(tmp_path: Path) -> None:
    root = project(tmp_path)
    # Leave behind what a process whose watcher failed would: an error note and a half-written record.
    command = f"{PY} -c " + shlex.quote(
        "import os; from app.pipeline import retrieve; retrieve('q'); "
        "out = os.environ['RETOBS_WATCH_OUT']; "
        "open(os.path.join(out, '1.error'), 'w').write('the watch record could not be written: OSError: disk full'); "
        "open(os.path.join(out, '1.json'), 'w').write('{')"
    )
    entry = watch_commands(root, [command]).to_payload()["commands"][0]
    assert entry["exit_code"] == 0
    assert "the watch record could not be written: OSError: disk full" in entry["failure"]
    assert "1.json is incomplete" in entry["failure"]
    assert any(symbols(process) == {"retrieve", "lexical", "screen"} for process in entry["processes"])


SYSTEM_PYTHON = Path("/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11")


def test_a_python_that_cannot_import_retobs_is_still_watched(tmp_path: Path) -> None:
    """The watcher is loaded by file path, so retobs need not be installed where the command runs."""
    if not SYSTEM_PYTHON.is_file():
        pytest.skip(f"no Python without retobs to run the command with ({SYSTEM_PYTHON} is absent)")
    probe = subprocess.run([str(SYSTEM_PYTHON), "-c", "import retrieval_observatory"], cwd=tmp_path, capture_output=True)
    if probe.returncode == 0:
        pytest.skip(f"{SYSTEM_PYTHON} can import retobs")
    root = project(tmp_path)
    command = f"{shlex.quote(str(SYSTEM_PYTHON))} -c \"from app.pipeline import retrieve; retrieve('q')\""
    entry = watch_commands(root, [command]).to_payload()["commands"][0]
    assert entry["exit_code"] == 0 and entry["failure"] is None, entry["failure"]
    process = entry["processes"][0]
    assert process["python"].startswith("3.11.") and process["mechanism"] == "profile"
    assert symbols(process) == {"retrieve", "lexical", "screen"}
