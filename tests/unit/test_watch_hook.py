"""The in-process watcher records which project functions handled documents, and nothing else."""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from retrieval_observatory.integrations import _watch_hook


def h(*ids: str) -> list[str]:
    """What the record holds for each id: a short sha256 digest, never the raw id."""
    return [hashlib.sha256(item.encode()).hexdigest()[:16] for item in ids]

PIPELINE = '''
from types import SimpleNamespace


def hit(doc_id, score=1.0):
    return SimpleNamespace(id=doc_id, score=score)


def lexical(query):
    return [hit("a"), hit("b"), hit("c")]


def screen(items):
    kept = [item for item in items if item.id != "b"]
    return kept, [item for item in items if item.id == "b"], [], not kept


def pick_route(query):
    return "hybrid"


def retrieve(query):
    pick_route(query)
    kept, _dropped, _errors, _empty = screen(lexical(query))
    return list(reversed(kept))


def stream(items):
    for item in items:
        yield item


class Exploding:
    @property
    def id(self):
        raise RuntimeError("property must not break the application")


def explode():
    return [Exploding()]


async def lane(query, ids):
    await asyncio.sleep(0)
    return [hit(doc_id) for doc_id in ids]


async def retrieve_async(query):
    a, b = await asyncio.gather(lane(query, ["a", "b"]), lane(query, ["b", "c"]))
    return a + [item for item in b if item.id != "b"]


def retrieve_threads(query):
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(lexical, query)
        second = pool.submit(lexical, query)
        return first.result() + second.result()
'''


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "proj"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "pipeline.py").write_text(
        "import asyncio\nfrom concurrent.futures import ThreadPoolExecutor\n" + textwrap.dedent(PIPELINE)
    )
    monkeypatch.syspath_prepend(str(root))
    sys.modules.pop("app.pipeline", None)
    sys.modules.pop("app", None)
    module = importlib.import_module("app.pipeline")
    yield root, module
    _watch_hook.stop()


def watched(root: Path, out: Path, fn, *, force_profile: bool = False) -> dict:
    _watch_hook.start(root, out, command="test", force_profile=force_profile)
    try:
        fn()
    finally:
        record = _watch_hook.stop()
    return record


def by_symbol(record: dict) -> dict[str, dict]:
    return {call["symbol"]: call for call in record["calls"]}


@pytest.mark.parametrize("force_profile", [False, True])
def test_records_candidate_handling_calls_with_ids_parents_and_order(project, tmp_path, force_profile) -> None:
    root, module = project
    record = watched(root, tmp_path / "out", lambda: module.retrieve("vitamin d"), force_profile=force_profile)
    calls = by_symbol(record)
    assert set(calls) == {"retrieve", "lexical", "screen"}
    assert calls["lexical"]["output"]["candidates"]["ids"] == h("a", "b", "c")
    # The question is kept only where the search starts (retrieve), not on every step below it.
    assert calls["retrieve"]["inputs"] == [{"param": "query", "text": "vitamin d"}]
    assert calls["lexical"]["inputs"] == []
    assert calls["lexical"]["parent"] == calls["retrieve"]["id"]
    assert calls["screen"]["output"] == {"bundle": [
        {"index": 0, "candidates": {"count": 2, "ids": h("a", "c"), "container": "list", "item_type": "SimpleNamespace", "ids_are_strings": False}},
        {"index": 1, "candidates": {"count": 1, "ids": h("b"), "container": "list", "item_type": "SimpleNamespace", "ids_are_strings": False}},
    ]}
    assert calls["retrieve"]["output"]["candidates"]["ids"] == h("c", "a")
    assert calls["retrieve"]["scalar_children"] == [{"symbol": "pick_route", "path": "app/pipeline.py", "line": calls["retrieve"]["scalar_children"][0]["line"], "value": "hybrid"}]
    assert calls["lexical"]["start"] < calls["lexical"]["end"] < calls["screen"]["start"]
    assert calls["retrieve"]["path"] == "app/pipeline.py"
    assert record["mechanism"] == ("profile" if force_profile or sys.version_info < (3, 12) else "monitoring")
    assert json.loads(next((tmp_path / "out").glob("*.json")).read_text()) == record


def test_no_document_text_or_other_argument_values_are_recorded(project, tmp_path) -> None:
    root, module = project
    record = watched(root, tmp_path / "out", lambda: module.retrieve("secret question"))
    text = json.dumps(record)
    assert "score" not in text
    # Only the query-named parameter where the search starts (retrieve); pick_route survives only as a
    # scalar child, without its arguments.
    assert text.count("secret question") == 1


def test_generators_are_never_consumed(project, tmp_path) -> None:
    root, module = project
    items = [module.hit("a"), module.hit("b")]
    seen: list[str] = []

    def run() -> None:
        generator = module.stream(items)
        seen.extend(item.id for item in generator)

    watched(root, tmp_path / "out", run)
    assert seen == ["a", "b"]


def test_a_failing_id_lookup_never_reaches_the_application(project, tmp_path) -> None:
    root, module = project
    result: list = []
    record = watched(root, tmp_path / "out", lambda: result.extend(module.explode()))
    assert len(result) == 1
    assert "explode" not in by_symbol(record)


@pytest.mark.parametrize("force_profile", [False, True])
def test_async_lanes_are_recorded_with_their_final_return(project, tmp_path, force_profile) -> None:
    root, module = project
    record = watched(root, tmp_path / "out", lambda: asyncio.run(module.retrieve_async("q")), force_profile=force_profile)
    lanes = [call for call in record["calls"] if call["symbol"] == "lane"]
    assert sorted(tuple(call["output"]["candidates"]["ids"]) for call in lanes) == sorted([tuple(h("a", "b")), tuple(h("b", "c"))])
    assert all(call["callable"] == "async" for call in lanes)
    entry = by_symbol(record)["retrieve_async"]
    assert entry["output"]["candidates"]["ids"] == h("a", "b", "c")


def test_thread_pool_work_is_recorded(project, tmp_path) -> None:
    root, module = project
    record = watched(root, tmp_path / "out", lambda: module.retrieve_threads("q"))
    lexical = [call for call in record["calls"] if call["symbol"] == "lexical"]
    assert len(lexical) == 2
    assert {call["thread"] for call in lexical} != {"MainThread"}


def test_code_outside_the_project_or_in_environment_dirs_is_ignored(tmp_path) -> None:
    root = tmp_path / "proj"
    venv = root / ".venv" / "lib" / "site-packages" / "vendor"
    venv.mkdir(parents=True)
    (venv / "__init__.py").write_text("def search(q):\n    return [{'id': 'x'}]\n")
    sys.path.insert(0, str(venv.parent))
    try:
        vendor = importlib.import_module("vendor")
        record = watched(root, tmp_path / "out", lambda: vendor.search("q"))
    finally:
        sys.path.remove(str(venv.parent))
        sys.modules.pop("vendor", None)
    assert record["calls"] == []


def test_stop_is_idempotent_and_start_twice_is_harmless(project, tmp_path) -> None:
    root, module = project
    _watch_hook.start(root, tmp_path / "out")
    _watch_hook.start(root, tmp_path / "out")
    module.lexical("q")
    assert _watch_hook.stop() is not None
    assert _watch_hook.stop() is None


# --- Beyond the plan's tests: generator lifecycles, privacy edges, hook errors, mechanism checks ----------

EXTRA = '''
import asyncio
import sys
from types import SimpleNamespace

from app.pipeline import hit, lexical, pick_route, screen

READS = []
FRAMES = []


def guarded(items):
    try:
        for item in items:
            yield item
    finally:
        pass


def outer(query):
    generator = guarded(lexical(query))
    next(generator)
    generator.close()
    return lexical(query)[:1]


async def after_pause(query):
    await asyncio.sleep(0)
    return lexical(query)


def passages(query):
    return ["vitamin d helps bones", "sunlight makes vitamin d"]


def keep_passages(texts):
    return texts[:1]


def string_ids(query):
    return ["d1", "d2"]


def keyed(query):
    return {"documents": [hit("a")], "what helps vitamin uptake": [hit("b")]}


class Lazy:
    @property
    def documents(self):
        READS.append("documents")
        return [hit("a")]


def lazy_result(query):
    return Lazy()


def plain_result(query):
    return SimpleNamespace(documents=[hit("a"), hit("b")])


class Slotted:
    __slots__ = ("documents",)

    def __init__(self, documents):
        self.documents = documents


def slotted_result(query):
    return Slotted([hit("c")])


def tokenize(text):
    return text.lower().split()


def index_doc(text):
    tokenize(text)


def setup(count):
    for number in range(count):
        index_doc(f"Doc {number} says vitamin D helps bones")


def indexed_search(query):
    setup(3)
    return lexical(query)


def held(items):
    FRAMES.append(sys._getframe())
    for item in items:
        yield item


def search_after_setup(query):
    pick_route(query)
    setup(100)
    return screen(lexical(query))[0]
'''


@pytest.fixture()
def extra(project):
    root, _module = project
    (root / "app" / "extra.py").write_text(textwrap.dedent(EXTRA))
    sys.modules.pop("app.extra", None)
    yield importlib.import_module("app.extra")
    sys.modules.pop("app.extra", None)


@pytest.mark.parametrize("force_profile", [False, True])
def test_each_generator_call_is_its_own_record(project, tmp_path, force_profile) -> None:
    root, module = project
    items = [module.hit("a"), module.hit("b")]

    def run() -> None:
        for _ in range(20):
            list(module.stream(items))
        for _ in range(20):  # started, then dropped half-way: Python 3.12 closes these without any event
            generator = module.stream(items)
            next(generator)
            del generator

    record = watched(root, tmp_path / "out", run, force_profile=force_profile)
    streams = [call for call in record["calls"] if call["symbol"] == "stream"]
    assert len(streams) == 40
    assert all(call["callable"] == "generator" and call["output"] is None for call in streams)
    assert all(call["inputs"][0]["candidates"]["ids"] == h("a", "b") for call in streams)


@pytest.mark.parametrize("force_profile", [False, True])
def test_closing_a_generator_inside_a_call_keeps_that_calls_place(project, extra, tmp_path, force_profile) -> None:
    root, _module = project
    record = watched(root, tmp_path / "out", lambda: extra.outer("q"), force_profile=force_profile)
    calls = by_symbol(record)
    lexical = [call for call in record["calls"] if call["symbol"] == "lexical"]
    assert calls["outer"]["output"]["candidates"]["ids"] == h("a")
    assert [call["parent"] for call in lexical] == [calls["outer"]["id"], calls["outer"]["id"]]
    assert calls["guarded"]["parent"] == calls["outer"]["id"]
    assert calls["guarded"]["end"] < max(call["start"] for call in lexical)


@pytest.mark.parametrize("force_profile", [False, True])
def test_a_resumed_coroutine_is_the_parent_of_what_it_calls_next(project, extra, tmp_path, force_profile) -> None:
    root, _module = project
    record = watched(root, tmp_path / "out", lambda: asyncio.run(extra.after_pause("q")), force_profile=force_profile)
    calls = by_symbol(record)
    assert calls["lexical"]["parent"] == calls["after_pause"]["id"]
    assert calls["after_pause"]["output"]["candidates"]["ids"] == h("a", "b", "c")


def test_passages_never_reach_the_record_and_string_ids_do(project, extra, tmp_path) -> None:
    root, _module = project

    def run() -> None:
        extra.keep_passages(extra.passages("q"))
        extra.string_ids("q")
        extra.keyed("q")

    record = watched(root, tmp_path / "out", run)
    assert "vitamin" not in json.dumps(record) and "sunlight" not in json.dumps(record)
    assert set(by_symbol(record)) == {"string_ids", "keyed"}
    assert by_symbol(record)["string_ids"]["output"]["candidates"] == {
        "count": 2, "ids": h("d1", "d2"), "container": "list", "item_type": "str", "ids_are_strings": True,
    }
    assert [element["key"] for element in by_symbol(record)["keyed"]["output"]["bundle"]] == ["documents"]


def test_a_documents_attribute_is_read_without_running_application_code(project, extra, tmp_path) -> None:
    root, _module = project

    def run() -> None:
        extra.lazy_result("q")
        extra.plain_result("q")
        extra.slotted_result("q")

    record = watched(root, tmp_path / "out", run)
    assert extra.READS == []
    assert set(by_symbol(record)) == {"plain_result", "slotted_result", "Slotted.__init__"}
    assert by_symbol(record)["plain_result"]["output"]["bundle"][0]["attr"] == "documents"
    assert by_symbol(record)["plain_result"]["output"]["bundle"][0]["candidates"]["ids"] == h("a", "b")
    assert by_symbol(record)["slotted_result"]["output"]["bundle"][0]["attr"] == "documents"
    assert by_symbol(record)["slotted_result"]["output"]["bundle"][0]["candidates"]["ids"] == h("c")


@pytest.mark.parametrize("force_profile", [False, True])
def test_a_watcher_error_is_noted_and_never_reaches_the_application(project, tmp_path, monkeypatch, force_profile) -> None:
    root, module = project

    def broken(path: Path) -> bool:
        raise OSError("disk went away")

    monkeypatch.setattr(_watch_hook, "is_excluded_dir", broken)
    result: list = []
    record = watched(root, tmp_path / "out", lambda: result.append(module.retrieve("q")), force_profile=force_profile)
    assert [item.id for item in result[0]] == ["c", "a"]
    assert record["calls"] == []
    assert any("disk went away" in note for note in record["notes"])
    assert len(record["notes"]) <= _watch_hook.MAX_NOTES


def test_the_profile_mechanism_watches_threads_started_after_it(project, tmp_path) -> None:
    root, module = project
    record = watched(root, tmp_path / "out", lambda: module.retrieve_threads("q"), force_profile=True)
    lexical = [call for call in record["calls"] if call["symbol"] == "lexical"]
    assert len(lexical) == 2
    assert "MainThread" not in {call["thread"] for call in lexical}


@pytest.mark.skipif(sys.version_info < (3, 12), reason="sys.monitoring is Python 3.12+")
def test_monitoring_callbacks_run_directly_above_the_monitored_frame(project, extra) -> None:
    # The watcher reads the monitored frame as sys._getframe(1) inside each callback.
    _root, module = project
    monitoring = sys.monitoring
    events = monitoring.events
    kinds = (events.PY_START, events.PY_RESUME, events.PY_RETURN, events.PY_YIELD, events.PY_UNWIND, events.PY_THROW)
    files = {module.__file__, extra.__file__}
    seen: list[bool] = []

    def check(code, *_args):
        if code.co_filename in files:
            seen.append(sys._getframe(1).f_code is code)

    tool = next(tool for tool in (3, 4, 5) if monitoring.get_tool(tool) is None)
    monitoring.use_tool_id(tool, "retobs-watch-test")
    try:
        for kind in kinds:
            monitoring.register_callback(tool, kind, check)
        monitoring.set_events(tool, sum(kinds))
        module.retrieve("q")
        list(module.stream([module.hit("a")]))
        asyncio.run(module.retrieve_async("q"))
        extra.outer("q")
        with pytest.raises(RuntimeError):
            module.explode()[0].id  # the property raises, unwinding a monitored frame
    finally:
        monitoring.set_events(tool, 0)
        for kind in kinds:
            monitoring.register_callback(tool, kind, None)
        monitoring.free_tool_id(tool)
    assert len(seen) > 20 and all(seen)


# --- Round two: hashed ids, the question only where the search starts, long setups, a stdlib-only hook ---


def test_only_the_question_where_the_search_starts_is_kept(project, extra, tmp_path) -> None:
    root, _module = project
    record = watched(root, tmp_path / "out", lambda: extra.indexed_search("secret question"))
    text = json.dumps(record)
    assert text.count("secret question") == 1
    assert "vitamin" not in text and "helps" not in text and "Doc" not in text
    calls = by_symbol(record)
    assert calls["indexed_search"]["inputs"] == [{"param": "query", "text": "secret question"}]
    tokens = [call for call in record["calls"] if call["symbol"] == "tokenize"]
    assert len(tokens) == 3 and all(call["inputs"] == [] for call in tokens)
    assert tokens[0]["output"]["candidates"]["ids"] == h("doc", "0", "says", "vitamin", "d", "helps", "bones")


def test_a_long_setup_before_the_search_does_not_crowd_it_out(project, extra, tmp_path, monkeypatch) -> None:
    root, _module = project
    monkeypatch.setattr(_watch_hook, "MAX_RECORDED_CALLS", 60)
    monkeypatch.setattr(_watch_hook, "MAX_STEP_CALLS", 10)
    record = watched(root, tmp_path / "out", lambda: extra.search_after_setup("q"))
    calls = by_symbol(record)
    search = calls["search_after_setup"]
    assert record["truncated"] is False
    assert search["output"]["candidates"]["ids"] == h("a", "c")
    assert calls["lexical"]["parent"] == search["id"] and calls["screen"]["parent"] == search["id"]
    assert [child["symbol"] for child in search["scalar_children"]] == ["pick_route"]
    assert len([call for call in record["calls"] if call["symbol"] == "tokenize"]) == 7
    assert "kept the last 10 document-handling calls; 93 earlier ones were dropped" in record["notes"]


def test_with_too_many_document_handling_calls_the_latest_are_kept(project, tmp_path, monkeypatch) -> None:
    root, module = project
    monkeypatch.setattr(_watch_hook, "MAX_STEP_CALLS", 3)

    def run() -> None:
        for _ in range(5):
            module.lexical("q")
        module.retrieve("q")

    record = watched(root, tmp_path / "out", run)
    assert [call["symbol"] for call in record["calls"]] == ["lexical", "screen", "retrieve"]
    assert record["calls"][0]["parent"] == record["calls"][2]["id"]
    assert record["truncated"] is False
    assert "kept the last 3 document-handling calls; 5 earlier ones were dropped" in record["notes"]


def test_the_hook_loads_by_file_path_without_importing_the_package(project, tmp_path) -> None:
    root, _module = project
    script = textwrap.dedent(f"""
        import importlib.util, json, sys
        spec = importlib.util.spec_from_file_location("retobs_watch_hook", {_watch_hook.__file__!r})
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        hook.start({str(root)!r}, {str(tmp_path / "out")!r}, command="by path")
        sys.path.insert(0, {str(root)!r})
        from app.pipeline import retrieve
        retrieve("q")
        record = hook.stop()
        print(json.dumps({{
            "symbols": sorted(call["symbol"] for call in record["calls"]),
            "package": sorted(name for name in sys.modules if name.split(".")[0] == "retrieval_observatory"),
        }}))
    """)
    completed = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert json.loads(completed.stdout) == {"symbols": ["lexical", "retrieve", "screen"], "package": []}


def test_the_hooks_copied_rules_match_the_package(tmp_path) -> None:
    from retrieval_observatory.integrations import detect
    from retrieval_observatory.tracing import candidates

    observe = importlib.import_module("retrieval_observatory.sdk.observe")  # the package re-exports a function by this name
    assert _watch_hook._QUERY_PARAMETERS == observe._QUERY_PARAMETERS
    assert _watch_hook._SKIP_DIRS == detect._SKIP_DIRS and _watch_hook._PACKAGE_DIRS == detect._PACKAGE_DIRS

    def outcome(rule, item):
        try:
            return rule(item)
        except Exception as exc:
            return type(exc)

    node = SimpleNamespace(node_id="n1")
    samples = [
        {"doc_id": "d"}, {"id": 0}, {"id": ""}, {"doc_id": None, "id": "x"}, {"doc_id": "", "node_id": "n"}, {"id_": "i"},
        {"node": node}, {"node": {"id": "nd"}}, {"node": {}}, {"metadata": {"id": "m"}}, {"metadata": None},
        {"metadata": "not a mapping", "id": "x"}, {}, {"text": "t"}, SimpleNamespace(doc_id="a"), SimpleNamespace(id=5),
        SimpleNamespace(node=node, score=1.0), SimpleNamespace(metadata={"id": "m2"}), SimpleNamespace(), object(), "plain",
    ]
    for sample in samples:
        assert outcome(_watch_hook.observed_id, sample) == outcome(candidates.observed_id, sample), sample
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "pyvenv.cfg").write_text("")
    names = [".git", ".hidden", "venv", ".venv", "node_modules", "__pycache__", "tests", "test", "build", "dist", "retobs",
             "site-packages", "dist-packages", "src", "app", "harness", "env"]
    for name in names:
        assert _watch_hook.is_excluded_dir(tmp_path / name) == detect.is_excluded_dir(tmp_path / name), name


@pytest.mark.skipif(sys.version_info < (3, 12), reason="sys.monitoring is Python 3.12+")
def test_with_no_free_monitoring_tool_id_the_watcher_falls_back_to_profile(project, tmp_path) -> None:
    root, module = project
    monitoring = sys.monitoring
    taken = [tool for tool in (monitoring.PROFILER_ID, 3, 4) if monitoring.get_tool(tool) is None]
    for tool in taken:
        monitoring.use_tool_id(tool, "busy")
    try:
        record = watched(root, tmp_path / "out", lambda: module.retrieve("q"))
    finally:
        for tool in taken:
            monitoring.free_tool_id(tool)
    assert record["mechanism"] == "profile"
    assert set(by_symbol(record)) == {"retrieve", "lexical", "screen"}
    assert any("tool ids" in note for note in record["notes"])


def test_a_record_that_cannot_be_written_leaves_an_error_file(project, tmp_path) -> None:
    root, module = project
    out = tmp_path / "out"
    (out / f"{os.getpid()}.json").mkdir(parents=True)  # a directory where the record should go
    _watch_hook.start(root, out)
    module.retrieve("q")
    assert _watch_hook.stop() is not None
    assert (out / f"{os.getpid()}.error").read_text().startswith("the watch record could not be written: ")


def test_a_stopped_watcher_ignores_threads_that_still_call_it(project, tmp_path) -> None:
    root, module = project
    go = threading.Event()

    def later() -> None:
        go.wait()
        module.lexical("q")

    _watch_hook.start(root, tmp_path / "out", force_profile=True)
    worker = threading.Thread(target=later)  # started while watching, so it carries the profile function
    worker.start()
    watcher = _watch_hook._active
    _watch_hook.stop()
    recorded = len(watcher.records)
    go.set()
    worker.join()
    assert len(watcher.records) == recorded


def test_a_project_reached_through_a_symlink_is_watched(tmp_path, monkeypatch) -> None:
    real = tmp_path / "real"
    (real / "app").mkdir(parents=True)
    (real / "app" / "__init__.py").write_text("")
    (real / "app" / "pipeline.py").write_text(
        "import asyncio\nfrom concurrent.futures import ThreadPoolExecutor\n" + textwrap.dedent(PIPELINE)
    )
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.syspath_prepend(str(link))
    sys.modules.pop("app.pipeline", None)
    sys.modules.pop("app", None)
    try:
        module = importlib.import_module("app.pipeline")
        assert module.__file__.startswith(str(link))
        record = watched(real, tmp_path / "out", lambda: module.retrieve("q"))
    finally:
        sys.modules.pop("app.pipeline", None)
        sys.modules.pop("app", None)
    assert set(by_symbol(record)) == {"retrieve", "lexical", "screen"}
    assert {call["path"] for call in record["calls"]} == {"app/pipeline.py"}


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs os.fork")
def test_a_forked_child_reports_only_its_own_calls(project, tmp_path) -> None:
    root, module = project
    out = tmp_path / "out"
    _watch_hook.start(root, out)
    module.lexical("parent")
    child = os.fork()
    if child == 0:  # the child: run one search, write its own record, and never return into pytest
        status = 1
        try:
            module.retrieve("child")
            _watch_hook.stop()
            status = 0
        finally:
            os._exit(status)
    _pid, status = os.waitpid(child, 0)
    _watch_hook.stop()
    assert status == 0
    record = json.loads((out / f"{child}.json").read_text())
    assert sorted(call["symbol"] for call in record["calls"]) == ["lexical", "retrieve", "screen"]



def test_finished_generators_can_be_dropped_on_the_profile_path(project, extra, tmp_path, monkeypatch) -> None:
    # The profile mechanism must tell a generator's last return from a yield; otherwise every generator
    # stays "in progress", nothing can be dropped, and the cap cuts the search off. The generators keep
    # their own frames alive, so no frame address is reused to hide the difference.
    root, module = project
    monkeypatch.setattr(_watch_hook, "MAX_RECORDED_CALLS", 60)
    monkeypatch.setattr(_watch_hook, "MAX_STEP_CALLS", 10)
    items = [module.hit("a"), module.hit("b")]

    def run() -> None:
        for _ in range(100):
            list(extra.held(items))
        module.retrieve("q")

    record = watched(root, tmp_path / "out", run, force_profile=True)
    assert record["truncated"] is False
    assert {"retrieve", "lexical", "screen"} <= set(by_symbol(record))
