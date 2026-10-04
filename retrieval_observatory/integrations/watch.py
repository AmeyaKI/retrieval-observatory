"""Run the agent's search commands under retobs's watcher and merge what each Python process saw.

``retobs integrate --phase plan --watch "<command>"`` runs each command from the project root with
a ``sitecustomize.py`` prepended to ``PYTHONPATH``; every Python process the command starts loads
it, watches the project's own functions (``_watch_hook``), and writes ``<pid>.json`` on exit. The
merged result is ``retobs/watch.json``. Nothing is sent anywhere.
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

WATCH_FILE = Path("retobs") / "watch.json"
#: After a timeout, how long the command's processes get to write what they watched before they are killed.
_GRACE_S = 5

SITECUSTOMIZE = '''\
import os as _os
import sys as _sys

_out = _os.environ.get("RETOBS_WATCH_OUT")
if _out:
    try:
        # Loaded by file path: the watched process never imports the retrieval_observatory package
        # (no import-order or startup side effects, and retobs need not be installed there).
        import importlib.util as _util
        _spec = _util.spec_from_file_location("retobs_watch_hook", _os.environ["RETOBS_WATCH_HOOK"])
        _hook = _util.module_from_spec(_spec)
        _sys.modules["retobs_watch_hook"] = _hook
        _spec.loader.exec_module(_hook)
        _hook.start(_os.environ.get("RETOBS_WATCH_ROOT", "."), _out, command=_os.environ.get("RETOBS_WATCH_COMMAND", ""))
    except Exception as _exc:  # never break the command being watched
        try:
            with open(_os.path.join(_out, f"{_os.getpid()}.error"), "w", encoding="utf-8") as _fh:
                _fh.write(f"{type(_exc).__name__}: {_exc}")
        except OSError:
            pass

# Run the project's own sitecustomize too, if one exists further along sys.path.
_here = _os.path.realpath(_os.path.dirname(_os.path.abspath(__file__)))
_mine = _sys.modules.pop("sitecustomize", None)
_saved = list(_sys.path)
_sys.path[:] = [_p for _p in _sys.path if _os.path.realpath(_p or ".") != _here]
try:
    import sitecustomize  # noqa: F401
except ImportError as _exc:
    if _exc.name != "sitecustomize":
        raise
finally:
    _sys.path[:] = _saved
    if "sitecustomize" not in _sys.modules and _mine is not None:
        _sys.modules["sitecustomize"] = _mine
'''


@dataclass(frozen=True)
class WatchedCommand:
    command: str
    exit_code: int | None
    failure: str | None
    processes: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class WatchResult:
    commands: tuple[WatchedCommand, ...]
    path: Path

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "commands": [
                {"command": item.command, "exit_code": item.exit_code, "failure": item.failure, "processes": list(item.processes)}
                for item in self.commands
            ],
        }


def _tail(stream: str | bytes | None, lines: int = 20, limit: int = 2000) -> str:
    if stream is None:
        return ""
    text = stream.decode("utf-8", "replace") if isinstance(stream, bytes) else stream
    return "\n".join(text.strip().splitlines()[-lines:])[-limit:]


def _signal(process: subprocess.Popen[bytes], signum: int) -> None:
    """Signal the command's whole process group: the shell and every process it started."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signum)


def _run(root: Path, command: str, timeout_s: float) -> WatchedCommand:
    with tempfile.TemporaryDirectory(prefix="retobs-watch-") as tmp:
        hook_dir, out_dir = Path(tmp) / "hook", Path(tmp) / "out"
        hook_dir.mkdir()
        out_dir.mkdir()
        (hook_dir / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(hook_dir), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])])
        env.update(
            RETOBS_WATCH_OUT=str(out_dir), RETOBS_WATCH_ROOT=str(root), RETOBS_WATCH_COMMAND=command,
            RETOBS_WATCH_HOOK=str(Path(__file__).with_name("_watch_hook.py")),
        )
        failure: str | None = None
        exit_code: int | None = None
        timed_out = False
        # stdin and stdout never touch retobs's own streams (the MCP server speaks over them).
        process = subprocess.Popen(
            command, shell=True, cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, start_new_session=True,
        )
        try:
            try:
                _, stderr = process.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                # Interrupt rather than kill, so each Python process still writes what it watched.
                timed_out = True
                _signal(process, signal.SIGINT)
                try:
                    _, stderr = process.communicate(timeout=_GRACE_S)
                except subprocess.TimeoutExpired:
                    _signal(process, signal.SIGKILL)
                    _, stderr = process.communicate()
                failure = f"timed out after {timeout_s:g}s: {_tail(stderr)}"
            else:
                exit_code = process.returncode
                if exit_code != 0:
                    failure = f"exit code {exit_code}: {_tail(stderr)}"
        finally:
            if process.poll() is None:  # retobs itself was interrupted: leave nothing running
                _signal(process, signal.SIGKILL)
                process.wait()
        processes: list[Mapping[str, Any]] = []
        errors = [path.read_text(encoding="utf-8") for path in sorted(out_dir.glob("*.error"))]
        for path in sorted(out_dir.glob("*.json")):
            try:
                processes.append(json.loads(path.read_text(encoding="utf-8")))
            except ValueError:  # cut short when a process was killed mid-write
                errors.append(f"the watch record {path.name} is incomplete")
        reasons = [f"retobs's watcher failed in the command's Python: {error}" for error in errors]
        if not processes and not errors and not timed_out:
            reasons.append(
                "retobs's watcher never started: the command must run Python without -I, -S or -E and must not replace "
                "PYTHONPATH (retobs adds its watcher there)"
            )
        failure = "; ".join([*([failure] if failure else []), *reasons]) or None
        return WatchedCommand(command, exit_code, failure, tuple(processes))


def watch_commands(project_root: Path, commands: Sequence[str], *, timeout_s: float = 600) -> WatchResult:
    """Run each command from the project root under the watcher; write and return ``retobs/watch.json``."""
    root = project_root.resolve()
    result = WatchResult(tuple(_run(root, command, timeout_s) for command in commands), root / WATCH_FILE)
    result.path.parent.mkdir(parents=True, exist_ok=True)
    result.path.write_text(json.dumps(result.to_payload(), indent=2) + "\n", encoding="utf-8")
    return result
