"""In-process watcher behind ``retobs integrate --phase plan --watch``.

Started by the ``sitecustomize.py`` that ``integrations.watch`` puts on ``PYTHONPATH``. It records
which of the project's own functions handled lists of documents during one command: who called
whom, in what order, which ids went in and out. It is observe-only. It never mutates an argument,
never iterates a generator or iterator, and never raises into the application. It records no
document text: ids are short sha256 digests, and the only argument values kept are short
identifier-like scalars and the search's question. watch.json can hold that question text (a
query-named string, up to 200 characters) only where the search starts, and for at most 20 calls
per function: a search runs a handful of times per command, a per-document function once per document.

Standard library only, so the watched process never imports the ``retrieval_observatory`` package:
the launcher loads this file by path. The id rule, the excluded-directory rule and the query
parameter names are copies of ``tracing.candidates.observed_id``, ``integrations.detect.is_excluded_dir``
and ``sdk.observe._QUERY_PARAMETERS``; a unit test keeps them identical.
"""
from __future__ import annotations

import atexit
import collections
import collections.abc
import dis
import functools
import hashlib
import inspect
import itertools
import json
import os
import platform
import re
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_IDS = 1000
MAX_STEP_CALLS = 5000
MAX_RECORDED_CALLS = 200_000
MAX_SCALAR_CHILDREN = 20
MAX_BUNDLE_ELEMENTS = 50
MAX_NOTES = 20
MAX_QUESTION_CALLS = 20
_SCALAR = re.compile(r"[A-Za-z0-9_.-]{1,32}")
#: A string in a strings-only list counts as an id only when it looks like one: passages never do.
_ID_LIKE = re.compile(r"\S{1,200}")
_SUSPENDABLE = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ITERABLE_COROUTINE | inspect.CO_ASYNC_GENERATOR
_GENERATOR = inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR
_RESUME = dis.opmap.get("RESUME")  # Python 3.11+
_YIELD_VALUE = dis.opmap["YIELD_VALUE"]
_YIELD_FROM = dis.opmap.get("YIELD_FROM")  # Python 3.10
_PACKAGE_DIR = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + os.sep

# -- copies of package rules (kept identical by tests/unit/test_watch_hook.py) -------------------
_QUERY_PARAMETERS = ("query", "q", "question", "text")
_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".retobs", "retobs", ".mypy_cache", ".pytest_cache",
    "dist", "build", "tests", "test",
}
_PACKAGE_DIRS = {"site-packages", "dist-packages"}


def is_excluded_dir(path: Path) -> bool:
    """A dot-directory, a named skip dir, an installed-package dir, or a virtualenv of any name."""
    name = path.name
    return name.startswith(".") or name in _SKIP_DIRS or name in _PACKAGE_DIRS or (path / "pyvenv.cfg").is_file()


def _item_getter(item: Any) -> Any:
    if isinstance(item, collections.abc.Mapping):
        return item.get
    return lambda key, default=None: getattr(item, key, default)


def _has_id(value: Any) -> bool:
    return value is not None and value != ""


def observed_id(item: Any) -> Any:
    """The id one returned item carries under the candidate id rule, or ``None``."""
    get = _item_getter(item)
    metadata = dict(get("metadata", {}) or {})
    for key in ("doc_id", "id", "node_id", "id_"):
        value = get(key)
        if _has_id(value):
            return value
    node = get("node")
    if node is not None:
        node_get = _item_getter(node)
        for key in ("node_id", "id_", "id"):
            value = node_get(key)
            if _has_id(value):
                return value
    value = metadata.get("id")
    return value if _has_id(value) else None


# -- value summaries ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=1 << 16)
def _digest(raw: str) -> str:
    """What the record holds for an id: equal ids give equal digests, and no raw id is written."""
    return hashlib.sha256(raw.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _candidate_list(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, (list, tuple)):
        return None
    container = type(value).__name__ if type(value) in (list, tuple) else "list"
    if not value:
        return {"count": 0, "ids": [], "container": container, "item_type": None, "ids_are_strings": False}
    if all(isinstance(item, str) for item in value):
        if not all(_ID_LIKE.fullmatch(item) for item in value):
            return None
        return {"count": len(value), "ids": [_digest(item) for item in value[:MAX_IDS]], "container": container,
                "item_type": "str", "ids_are_strings": True}
    ids: list[str] = []
    for item in value:
        if item is None or isinstance(item, (bytes, int, float, bool, list, tuple, set)):
            return None
        try:
            found = observed_id(item)
        except Exception:  # an id property that raises: not a candidate, never the application's problem
            return None
        if found is None:
            return None
        if len(ids) < MAX_IDS:
            ids.append(_digest(str(found)))
    return {"count": len(value), "ids": ids, "container": container, "item_type": type(value[0]).__name__, "ids_are_strings": False}


def _instance_attribute(value: Any, name: str) -> Any:
    """``value.<name>`` read from the instance ``__dict__`` or a slot only, so no property, ``__getattr__`` or lazy load runs."""
    try:
        found = object.__getattribute__(value, "__dict__").get(name)
    except Exception:
        found = None
    if found is not None:
        return found
    try:
        slot = next((vars(klass)[name] for klass in type(value).__mro__ if name in vars(klass)), None)
        return slot.__get__(value, type(value)) if isinstance(slot, types.MemberDescriptorType) else None
    except Exception:
        return None


def _bundle(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, dict):
        # Only identifier-like keys are names; any other key is application data and is never recorded.
        elements = [("key", key, item) for key, item in itertools.islice(value.items(), MAX_BUNDLE_ELEMENTS)
                    if isinstance(key, str) and _SCALAR.fullmatch(key)]
    elif isinstance(value, (list, tuple)):
        elements = [("index", index, item) for index, item in enumerate(value[:MAX_BUNDLE_ELEMENTS])]
    else:
        elements = [("attr", "documents", _instance_attribute(value, "documents"))]
    found = []
    for name, slot, element in elements:
        candidates = _candidate_list(element)
        if candidates is not None and candidates["count"]:
            found.append({name: slot, "candidates": candidates})
    return found or None


def summarize(value: Any) -> dict[str, Any] | None:
    candidates = _candidate_list(value)
    if candidates is not None:
        return {"candidates": candidates}
    bundle = _bundle(value)
    return {"bundle": bundle} if bundle else None


def _output(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        return {"scalar": value} if _SCALAR.fullmatch(value) else None
    return summarize(value)


def _bears(record: dict[str, Any]) -> bool:
    summaries = [*record["inputs"], record["output"] or {}]
    return any("candidates" in item or "bundle" in item for item in summaries)


def _returns_objects(record: dict[str, Any]) -> bool:
    """Whether a call returned documents that carry their own ids (not a list of strings)."""
    output = record["output"] or {}
    lists = [output["candidates"]] if "candidates" in output else [item["candidates"] for item in output.get("bundle") or ()]
    return any(not item["ids_are_strings"] for item in lists)


def _starting(frame: Any) -> bool:
    """Profile path: whether a generator or coroutine frame is starting, not resuming or being thrown into.

    A starting frame sits on ``RESUME`` with location 0 (3.11+), or before its first instruction (3.10).
    """
    lasti = frame.f_lasti
    if lasti < 0 or _RESUME is None:
        return lasti < 0
    raw = frame.f_code.co_code
    return raw[lasti] == _RESUME and raw[lasti + 1] & 3 == 0


def _suspending(frame: Any) -> bool:
    """Profile path: whether a generator or coroutine's ``return`` event is a suspension, not its end."""
    raw = frame.f_code.co_code
    lasti = frame.f_lasti
    return raw[lasti] == _YIELD_VALUE or (_YIELD_FROM is not None and raw[lasti + 2:lasti + 3] == bytes([_YIELD_FROM]))


class _Watcher:
    def __init__(self, root: Path, out_dir: Path, command: str, force_profile: bool) -> None:
        self.root = os.path.realpath(root) + os.sep
        self.root_path = Path(self.root)
        self.out_dir = out_dir
        self.command = command
        self.mechanism = "profile" if force_profile or sys.version_info < (3, 12) else "monitoring"
        self.ids = itertools.count(1)
        self.seq = itertools.count(1)
        self.include: dict[Any, str] = {}
        self.tool: int | None = None
        self.stopped = False
        self.forget()

    def forget(self) -> None:
        """Start empty; in a forked child, drop what the parent recorded so the child reports only its own calls."""
        self.local = threading.local()
        self.mutex = threading.Lock()
        self.records: list[dict[str, Any]] = []
        self.open: dict[int, dict[str, Any]] = {}
        self.notes: list[str] = []
        self.truncated = False
        self.dropped = 0

    # -- filtering -------------------------------------------------------------------------
    def wanted(self, code: Any) -> str:
        """The project-relative path of code the watcher records, else ``""``."""
        path = self.include.get(code)
        if path is None:
            path = ""
            filename = code.co_filename
            # Comprehensions, generator expressions and lambdas are inline code of their caller.
            inline = code.co_name.startswith("<") and code.co_name != "<module>"
            if not inline and os.path.isabs(filename):
                real = os.path.realpath(filename)
                if real.startswith(self.root) and not real.startswith(_PACKAGE_DIR):
                    parts = Path(real[len(self.root):]).parts
                    if not any(is_excluded_dir(self.root_path.joinpath(*parts[: index + 1])) for index in range(len(parts) - 1)):
                        path = Path(*parts).as_posix()
            self.include[code] = path
        return path

    def note(self, message: str) -> None:
        if len(self.notes) < MAX_NOTES:
            self.notes.append(message)

    # -- per-thread stack ------------------------------------------------------------------
    def stack(self) -> list[dict[str, Any]]:
        stack = getattr(self.local, "stack", None)
        if stack is None:
            stack = self.local.stack = []
        return stack

    def pop(self, code: Any) -> dict[str, Any] | None:
        """Take this code's innermost record off the stack, with anything left above it; ``None`` if absent."""
        stack = self.stack()
        for index in range(len(stack) - 1, -1, -1):
            if stack[index]["_code"] is code:
                record = stack[index]
                del stack[index:]
                return record
        return None

    # -- events ------------------------------------------------------------------------------
    def enter(self, frame: Any, code: Any, starting: bool) -> None:
        stack = self.stack()
        if not starting:  # a generator or coroutine resuming: its record goes back on the stack
            resumed = self.open.get(id(frame))
            if resumed is not None and resumed["_code"] is code:
                stack.append(resumed)
            return
        if self.truncated:
            return
        symbol = getattr(code, "co_qualname", None) or _qualname(frame, code)
        record = {
            "id": next(self.ids), "parent": stack[-1]["id"] if stack else None,
            "thread": threading.current_thread().name, "symbol": symbol,
            "path": self.include[code], "line": code.co_firstlineno,
            "callable": _callable(code, symbol), "start": next(self.seq), "end": None,
            "inputs": _inputs(frame, code), "output": None, "error": None, "ms": None,
            "scalar_children": [], "_code": code, "_t": time.perf_counter(),
        }
        with self.mutex:
            if len(self.records) >= MAX_RECORDED_CALLS:
                self.records = self.select(running=True)
                if len(self.records) >= MAX_RECORDED_CALLS:
                    self.truncated = True
                    return
            self.records.append(record)
        if code.co_flags & _SUSPENDABLE:
            self.open[id(frame)] = record
        stack.append(record)

    def leave(self, frame: Any, code: Any, value: Any, *, error: str | None = None) -> None:
        record = self.pop(code)
        if record is None:
            return
        if not code.co_flags & _GENERATOR:  # a generator's values are the application's to consume
            record["output"] = _output(value) if error is None else None
        record["error"] = error
        self.ended(record)
        self.open.pop(id(frame), None)

    def suspend(self, code: Any) -> None:
        record = self.pop(code)
        if record is not None:
            self.ended(record)  # a generator dropped half-way may never report again

    def ended(self, record: dict[str, Any]) -> None:
        record["end"] = next(self.seq)
        record["ms"] = round((time.perf_counter() - record["_t"]) * 1000, 3)

    # -- sys.monitoring (3.12+) ------------------------------------------------------------
    def handle(self, frame: Any, code: Any, event: str, value: Any) -> Any:
        if self.stopped:
            return None
        try:
            if not self.wanted(code):
                return sys.monitoring.DISABLE
            if event == "start":
                self.enter(frame, code, True)
            elif event == "resume":
                self.enter(frame, code, False)
            elif event == "yield":
                self.suspend(code)
            elif event == "return":
                self.leave(frame, code, value)
            else:
                self.leave(frame, code, None, error=type(value).__name__)
        except Exception as exc:  # never break the application
            self.note(f"watch error on {event}: {type(exc).__name__}: {exc}")
        return None

    def m_start(self, code: Any, offset: int) -> Any:
        return self.handle(sys._getframe(1), code, "start", None)

    def m_resume(self, code: Any, offset: int) -> Any:
        return self.handle(sys._getframe(1), code, "resume", None)

    def m_throw(self, code: Any, offset: int, exception: BaseException) -> Any:
        self.handle(sys._getframe(1), code, "resume", None)
        return None  # PY_THROW cannot be disabled

    def m_return(self, code: Any, offset: int, value: Any) -> Any:
        return self.handle(sys._getframe(1), code, "return", value)

    def m_yield(self, code: Any, offset: int, value: Any) -> Any:
        return self.handle(sys._getframe(1), code, "yield", None)

    def m_unwind(self, code: Any, offset: int, exception: BaseException) -> Any:
        self.handle(sys._getframe(1), code, "unwind", exception)
        return None  # PY_UNWIND cannot be disabled

    # -- sys.setprofile (3.10/3.11, or forced) ---------------------------------------------
    def profile(self, frame: Any, event: str, arg: Any) -> None:
        if self.stopped or (event != "call" and event != "return"):
            return
        code = frame.f_code
        try:
            if not self.wanted(code):
                return
            suspendable = code.co_flags & _SUSPENDABLE
            if event == "call":
                self.enter(frame, code, not suspendable or _starting(frame))
            elif suspendable and _suspending(frame):
                self.suspend(code)
            else:
                self.leave(frame, code, arg)
        except Exception as exc:  # never break the application
            self.note(f"watch error on {event}: {type(exc).__name__}: {exc}")

    # -- lifecycle -------------------------------------------------------------------------
    def _events(self) -> dict[int, Any]:
        events = sys.monitoring.events
        return {
            events.PY_START: self.m_start, events.PY_RESUME: self.m_resume, events.PY_THROW: self.m_throw,
            events.PY_RETURN: self.m_return, events.PY_YIELD: self.m_yield, events.PY_UNWIND: self.m_unwind,
        }

    def install(self) -> None:
        if self.mechanism == "monitoring":
            monitoring = sys.monitoring
            self.tool = next((tool for tool in (monitoring.PROFILER_ID, 3, 4) if monitoring.get_tool(tool) is None), None)
            if self.tool is not None:
                monitoring.use_tool_id(self.tool, "retobs-watch")
                for event, callback in self._events().items():
                    monitoring.register_callback(self.tool, event, callback)
                monitoring.set_events(self.tool, sum(self._events()))
                return
            self.mechanism = "profile"
            self.notes.append("sys.monitoring tool ids 2-4 were all in use; watched with sys.setprofile instead")
        sys.setprofile(self.profile)
        threading.setprofile(self.profile)

    def uninstall(self) -> None:
        if self.tool is not None:
            sys.monitoring.set_events(self.tool, 0)
            for event in self._events():
                sys.monitoring.register_callback(self.tool, event, None)
            sys.monitoring.free_tool_id(self.tool)
            self.tool = None
        else:
            sys.setprofile(None)
            threading.setprofile(None)

    def select(self, *, running: bool) -> list[dict[str, Any]]:
        """The records worth keeping: the latest ``MAX_STEP_CALLS`` calls that handled documents, every
        call still in progress (while ``running``), and their callers. Setup comes first and the search
        last, so the earliest document-handling calls are the ones dropped. A dropped call that returned
        a scalar becomes a scalar child of its kept caller."""
        records = list(self.records)
        live = {id(record) for record in list(self.open.values())} if running else set()
        active = [record for record in records if record["end"] is None or id(record) in live]
        done = sorted(
            (record for record in records if record["end"] is not None and id(record) not in live and _bears(record)),
            key=lambda record: record["end"],
        )
        if len(done) > MAX_STEP_CALLS:
            self.dropped += len(done) - MAX_STEP_CALLS
            done = done[len(done) - MAX_STEP_CALLS:]
        by_id = {record["id"]: record for record in records}
        keep: set[int] = set()
        for record in [*done, *(active if running else ())]:
            while record is not None and record["id"] not in keep:
                keep.add(record["id"])
                record = by_id.get(record["parent"])
        for record in records:
            output = record["output"]
            if record["id"] in keep or not output or "scalar" not in output:
                continue
            parent = by_id.get(record["parent"])
            if parent is not None and parent["id"] in keep and len(parent["scalar_children"]) < MAX_SCALAR_CHILDREN:
                parent["scalar_children"].append(
                    {"symbol": record["symbol"], "path": record["path"], "line": record["line"], "value": output["scalar"]}
                )
        return [record for record in records if record["id"] in keep]

    def payload(self) -> dict[str, Any]:
        self.records = [record for record in self.records if record["end"] is not None]
        kept = self.select(running=False)
        if self.dropped:
            self.notes.append(f"kept the last {MAX_STEP_CALLS} document-handling calls; {self.dropped} earlier ones were dropped")
        by_id = {record["id"]: record for record in kept}
        # The question is kept only where the search starts: the outermost call that returned documents,
        # in a function that ran at most MAX_QUESTION_CALLS times that way. Every other query-named argument
        # (a tokenizer's or a per-document chunker's text, say) is dropped.
        starts = []
        for record in kept:
            parent = by_id.get(record["parent"])
            while parent is not None and not _returns_objects(parent):
                parent = by_id.get(parent["parent"])
            if parent is None and _returns_objects(record) and any("text" in item for item in record["inputs"]):
                starts.append(record)
        runs = collections.Counter((record["path"], record["symbol"]) for record in starts)
        asked = {id(record) for record in starts if runs[(record["path"], record["symbol"])] <= MAX_QUESTION_CALLS}
        for record in kept:
            if id(record) not in asked:
                record["inputs"] = [item for item in record["inputs"] if "text" not in item]
        calls = [
            {key: value for key, value in record.items() if not key.startswith("_")}
            for record in sorted(kept, key=lambda record: record["end"])
        ]
        return {
            "schema_version": SCHEMA_VERSION, "mechanism": self.mechanism, "python": platform.python_version(),
            "command": self.command, "calls": calls, "truncated": self.truncated, "notes": self.notes,
        }


def _qualname(frame: Any, code: Any) -> str:
    owner = frame.f_locals.get("self", frame.f_locals.get("cls")) if code.co_argcount else None
    if owner is not None:
        cls = owner if isinstance(owner, type) else type(owner)
        if code.co_name in vars(cls):
            return f"{cls.__name__}.{code.co_name}"
    return code.co_name


def _callable(code: Any, symbol: str) -> str:
    if "<locals>" in symbol or "<lambda>" in symbol:
        return "nested"
    if code.co_flags & (inspect.CO_COROUTINE | inspect.CO_ITERABLE_COROUTINE):
        return "async"
    if code.co_flags & (inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR):
        return "generator"
    return "method" if "." in symbol else "function"


def _inputs(frame: Any, code: Any) -> list[dict[str, Any]]:
    count = code.co_argcount + code.co_kwonlyargcount
    count += bool(code.co_flags & inspect.CO_VARARGS) + bool(code.co_flags & inspect.CO_VARKEYWORDS)
    local = frame.f_locals
    found: list[dict[str, Any]] = []
    for name in code.co_varnames[:count]:
        if name in ("self", "cls") or name not in local:
            continue
        value = local[name]
        if name in _QUERY_PARAMETERS and isinstance(value, str):
            found.append({"param": name, "text": value[:200]})
            continue
        summary = summarize(value)
        if summary is not None:
            found.append({"param": name, **summary})
    return found


_active: _Watcher | None = None
_lock = threading.Lock()


def _forked_child() -> None:
    global _lock
    _lock = threading.Lock()
    if _active is not None:
        _active.forget()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_forked_child)


def start(project_root: str | Path, out_dir: str | Path, *, command: str = "", force_profile: bool = False) -> None:
    """Start watching this process. A second call while one watcher runs does nothing."""
    global _active
    with _lock:
        if _active is not None:
            return
        watcher = _Watcher(Path(project_root), Path(out_dir), command, force_profile)
        watcher.install()
        _active = watcher
    atexit.register(stop)


def stop() -> dict[str, Any] | None:
    """Stop watching and write ``<out_dir>/<pid>.json``; returns the record, or ``None`` if not watching.

    If the record cannot be written, ``<out_dir>/<pid>.error`` says why (best effort)."""
    global _active
    with _lock:
        watcher, _active = _active, None
    if watcher is None:
        return None
    watcher.stopped = True
    try:
        watcher.uninstall()
    except Exception as exc:
        watcher.note(f"watch error on stop: {type(exc).__name__}: {exc}")
    record = None
    try:
        record = watcher.payload()
        watcher.out_dir.mkdir(parents=True, exist_ok=True)
        (watcher.out_dir / f"{os.getpid()}.json").write_text(json.dumps(record), encoding="utf-8")
    except Exception as exc:
        try:
            watcher.out_dir.mkdir(parents=True, exist_ok=True)
            (watcher.out_dir / f"{os.getpid()}.error").write_text(
                f"the watch record could not be written: {type(exc).__name__}: {exc}", encoding="utf-8"
            )
        except Exception:
            pass
    return record
