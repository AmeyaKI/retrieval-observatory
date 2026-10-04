"""Turn what ``retobs integrate --phase plan --watch`` recorded into a proposed map of search steps.

Pure functions over the payload ``integrations.watch`` writes to ``retobs/watch.json``: no I/O and
no project imports. A step is a project function that handed back a list of documents. Its kind
comes from what it did to the documents, and its parents from whose documents it received; its
name plays no part.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping, Sequence

WATCH_SCHEMA_VERSION = 1
#: An input list is linked to an earlier step's output when at least this share of its ids came from it.
LINK_OVERLAP = 0.5
_KIND_ORDER = ("SOURCE", "FUSE", "TRANSFORM", "RERANK", "FILTER")
#: Comprehension frames (Python 3.10 and 3.11) are inline code of the function that holds them.
_INLINE = frozenset({"<listcomp>", "<setcomp>", "<dictcomp>", "<genexpr>"})


@dataclass(frozen=True)
class WatchedStep:
    op_id: str
    symbol: str
    relative_path: str
    #: SOURCE | FUSE | FILTER | RERANK | TRANSFORM | GATE; ``None`` when the step changed nothing in
    #: every watched search, so its behaviour does not say what kind it is.
    op_type: str | None
    parent_ids: tuple[str, ...] = ()
    #: ``(parameter, parent op_id)`` for each input list linked to a parent.
    inputs_from: tuple[tuple[str, str], ...] = ()
    invocation: str = "sync"
    #: ``index:<i>`` / ``key:<name>`` / ``attr:<name>`` when the documents are one element of what it returned.
    output_bundle: str | None = None
    #: Indexes of the watched commands whose searches ran this step.
    commands: tuple[int, ...] = ()
    took: int = 0
    returned: int = 0
    #: Inner steps folded into this one because they worked on documents this function created itself.
    inside: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class WatchMap:
    commands: tuple[str, ...]
    #: ``{"file", "symbol", "kind"}``, the plan's ``discovery.entrypoint`` shape, or ``None``.
    entrypoint: Mapping[str, str] | None
    #: The entrypoint's query-named parameter (``"query"``), if it received one.
    query_parameter: str | None
    #: Per command: the query text the entrypoint received, if any.
    query_texts: tuple[str | None, ...]
    steps: tuple[WatchedStep, ...]
    conditional: tuple[str, ...] = ()
    #: ``{"symbol", "relative_path", "values": {"<command index>": route}}``.
    chooser: Mapping[str, Any] | None = None
    unmarkable: tuple[Mapping[str, str], ...] = ()
    searches_seen: int = 0
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(eq=False)
class _Call:
    command: int
    id: int
    parent: int | None
    symbol: str
    path: str
    callable: str
    start: int
    end: int
    inputs: list[tuple[str, tuple[str, ...]]]
    text: tuple[str, str] | None
    outputs: list[tuple[str | None, tuple[str, ...]]]
    #: Recorded list lengths (``ids`` stop at 1,000): per output slot, and summed over the inputs.
    sizes: dict[str | None, int]
    took: int
    scalars: list[Mapping[str, Any]]
    owner: "_Call | None" = None
    #: A step started on another thread (pool lane, gathered task), owned by the search it ran inside.
    crossed: bool = False
    folded: bool = False
    wrapper: bool = False
    inside: tuple[str, ...] = ()
    links: list[tuple[str, "_Call", str | None]] = field(default_factory=list)
    unlinked: list[str] = field(default_factory=list)
    used_slots: Counter = field(default_factory=Counter)

    @property
    def key(self) -> tuple[str, str]:
        return (self.path, self.symbol)

    @property
    def signature(self) -> tuple[str, str, str]:
        """How an entrypoint is told apart: the function and whether it is async."""
        return (self.path, self.symbol, self.callable)

    @property
    def is_step(self) -> bool:
        if self.symbol.rsplit(".", 1)[-1] in _INLINE:
            return False
        return any(ids for _slot, ids in self.outputs) or (bool(self.outputs) and bool(self.inputs))

    @property
    def slot(self) -> str | None:
        if self.used_slots:
            return self.used_slots.most_common(1)[0][0]
        return next((slot for slot, ids in self.outputs if ids), self.outputs[0][0] if self.outputs else None)

    @property
    def out(self) -> tuple[str, ...]:
        chosen = self.slot
        return next((ids for slot, ids in self.outputs if slot == chosen), ())

    @property
    def returned(self) -> int:
        return self.sizes.get(self.slot, 0)


def _overlap(ids: Sequence[str], other: set[str]) -> float:
    return sum(1 for item in ids if item in other) / len(ids) if ids else 0.0


def _lists(summary: Mapping[str, Any] | None, confirm: Callable[[Mapping[str, Any]], bool]) -> list[tuple[str | None, Mapping[str, Any]]]:
    """``(bundle slot or None, candidates summary)`` for each confirmed candidate list in ``summary``."""
    if not summary:
        return []
    if "candidates" in summary:
        return [(None, summary["candidates"])] if confirm(summary["candidates"]) else []
    found: list[tuple[str | None, Mapping[str, Any]]] = []
    for element in summary.get("bundle") or ():
        slot = next(f"{name}:{element[name]}" for name in ("index", "key", "attr") if name in element)
        if confirm(element["candidates"]):
            found.append((slot, element["candidates"]))
    return found


def _confirmer(payload: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], bool]:
    """String-only lists count as documents only when their ids are document ids: ids also seen in
    object candidates, or (with no object candidates at all) ids that flow between two calls."""
    object_ids: set[str] = set()
    seen_in: dict[str, set[tuple[int, int, int]]] = {}
    for command_index, entry in enumerate(payload.get("commands") or ()):
        for process_index, process in enumerate(entry.get("processes") or ()):
            for raw in process.get("calls") or ():
                summaries = [*(raw.get("inputs") or ()), raw.get("output")]
                for summary in summaries:
                    for _slot, candidates in _lists(summary, lambda _candidates: True):
                        if candidates.get("ids_are_strings"):
                            for item in candidates["ids"]:
                                seen_in.setdefault(item, set()).add((command_index, process_index, raw["id"]))
                        else:
                            object_ids.update(candidates["ids"])
    flowing = {item for item, calls in seen_in.items() if len(calls) >= 2}
    known = object_ids or flowing

    def confirm(candidates: Mapping[str, Any]) -> bool:
        if not candidates["count"] or not candidates.get("ids_are_strings"):
            return True
        return _overlap(candidates["ids"], known) >= LINK_OVERLAP

    return confirm


def _parse(command: int, raw: Mapping[str, Any], confirm: Callable[[Mapping[str, Any]], bool]) -> _Call:
    inputs: list[tuple[str, tuple[str, ...]]] = []
    took = 0
    text: tuple[str, str] | None = None
    for item in raw.get("inputs") or ():
        if "text" in item and text is None:
            text = (item["param"], item["text"])
        for slot, candidates in _lists(item, confirm):
            inputs.append((item["param"] if slot is None else f"{item['param']}[{slot}]", tuple(candidates["ids"])))
            took += candidates["count"]
    outputs = _lists(raw.get("output"), confirm)
    return _Call(
        command, raw["id"], raw.get("parent"), raw["symbol"], raw["path"], raw.get("callable", "function"),
        raw["start"], raw["end"], inputs, text, [(slot, tuple(candidates["ids"])) for slot, candidates in outputs],
        {slot: candidates["count"] for slot, candidates in outputs}, took, list(raw.get("scalar_children") or ()),
    )


def _within(call: _Call, ancestor: _Call) -> bool:
    owner = call.owner
    while owner is not None:
        if owner is ancestor:
            return True
        owner = owner.owner
    return False


def _spawned_within(item: _Call, call: _Call) -> bool:
    """``item`` ran inside ``call``: down its call stack, or in a pool lane or task started during its run."""
    current: _Call | None = item
    while current is not None and current is not call:
        if current.crossed:
            return call.start < current.start and current.end < call.end
        current = current.owner
    return current is call


def _root(call: _Call) -> _Call:
    while call.owner is not None:
        call = call.owner
    return call


def _assign_owners(calls: list[_Call]) -> list[_Call]:
    """Each step's owner is its nearest enclosing step on its thread's call stack. A step with none
    there (thread pools, gathered tasks) belongs to the outermost top-level step whose run it happened
    inside: a lane running at the same time on another thread may enclose it too, but is not its caller."""
    by_id = {call.id: call for call in calls}
    steps = [call for call in calls if call.is_step]
    for call in steps:
        parent = by_id.get(call.parent) if call.parent is not None else None
        while parent is not None and not parent.is_step:
            parent = by_id.get(parent.parent) if parent.parent is not None else None
        call.owner = parent
    tops = [call for call in steps if call.owner is None]
    for call in tops:
        enclosing = [top for top in tops if top is not call and top.start < call.start and call.end < top.end]
        if enclosing:
            call.owner = min(enclosing, key=lambda top: top.start)
            call.crossed = True
    return steps


def _linked(ids: Sequence[str], before: Sequence[_Call]) -> tuple[_Call, str | None] | None:
    """The latest earlier step whose output (any bundle slot) is exactly ``ids``, else the one with
    the largest overlap of at least ``LINK_OVERLAP`` (latest on a tie)."""
    exact = [(call, slot) for call in before for slot, out in call.outputs if out == tuple(ids)]
    if exact:
        return max(exact, key=lambda pair: pair[0].end)
    best: tuple[float, int, _Call, str | None] | None = None
    for call in before:
        for slot, out in call.outputs:
            share = _overlap(ids, set(out))
            if share >= LINK_OVERLAP and (best is None or (share, call.end) > best[:2]):
                best = (share, call.end, call, slot)
    return (best[2], best[3]) if best else None


def _resolve(call: _Call, members: Sequence[_Call]) -> _Call:
    """A wrapper hands on its last inner step's documents: link to that step instead."""
    while call.wrapper:
        inner = [item for item in members if item.owner is call and not item.folded]
        if not inner:
            break
        call = max(inner, key=lambda item: item.end)
    return call


def _kind(step: _Call) -> str | None:
    out = step.out
    lists = [ids for _param, ids in step.inputs]
    if not lists:
        return "SOURCE"
    union = set().union(*lists)
    if len(lists) >= 2:
        return "FUSE" if set(out) <= union else "TRANSFORM"
    only = lists[0]
    if not set(out) <= set(only):
        return "TRANSFORM"
    if tuple(out) == tuple(only):
        return None
    position = {item: index for index, item in enumerate(only)}
    ordered = all(position[a] < position[b] for a, b in zip(out, out[1:]))
    return "FILTER" if ordered else "RERANK"


def _analyse_search(entry: _Call, steps: Sequence[_Call], notes: list[str]) -> list[_Call]:
    members = sorted((step for step in steps if step is not entry and _root(step) is entry), key=lambda step: step.end)
    for call in members:  # children end before their owners: decide lanes and wrappers bottom-up
        inner = [item for item in members if item.owner is call and not item.folded]
        if not inner:
            continue
        own_inputs = set().union(*[set(ids) for _param, ids in call.inputs]) if call.inputs else set()

        def created_inside(step: _Call) -> bool:
            # Only documents made during this call, or handed to it, can reach a step inside it: a
            # sibling lane that found the same documents is not where they came from.
            before = [item for item in members if item is not step and item is not call and not item.folded
                      and item.end < step.start and not _within(item, step) and _spawned_within(item, call)]
            return any(
                _linked(ids, before) is None and _overlap(ids, own_inputs) < LINK_OVERLAP
                for _param, ids in step.inputs
            )

        if any(created_inside(step) for step in inner):
            for item in members:
                if _within(item, call):
                    item.folded = True
            call.inside = tuple(f"{step.symbol} took {step.took} returned {step.returned}" for step in inner)
        else:
            call.wrapper = True
            last = max(inner, key=lambda item: item.end)
            if (call.out, call.returned) != (last.out, last.returned):
                notes.append(
                    f"{call.symbol} ({call.path}) changed the documents itself after {last.symbol} "
                    f"({last.returned} → {call.returned}); mark it with a CaptureSpec if that change matters"
                )
    marked = [call for call in members if not call.folded and not call.wrapper]
    for step in sorted(marked, key=lambda item: item.start):
        before = [item for item in members if item is not step and not item.folded and item.end < step.start and not _within(item, step)]
        for param, ids in step.inputs:
            found = _linked(ids, before)
            if found is None:
                step.unlinked.append(param)
                continue
            parent, slot = found
            parent.used_slots[slot] += 1
            step.links.append((param, _resolve(parent, members), slot))
    last = max(marked, key=lambda item: item.end, default=None)
    if last is not None and entry.out and (entry.out, entry.returned) != (last.out, last.returned):
        notes.append(f"{entry.symbol} changed the documents itself after {last.symbol} ({last.returned} → {entry.returned})")
    return marked


def _snake(text: str) -> str:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text.replace(".", "_"))
    return re.sub(r"[^0-9A-Za-z]+", "_", spaced).strip("_").lower() or "step"


def _op_ids(keys: Sequence[tuple[str, str]]) -> dict[tuple[str, str], str]:
    base = {key: _snake(key[1]) for key in keys}
    counts = Counter(base.values())
    named = {key: base[key] if counts[base[key]] == 1 else f"{_snake(PurePosixPath(key[0]).stem)}_{base[key]}" for key in keys}
    counts = Counter(named.values())
    return {key: name if counts[name] == 1 else f"{_snake(key[0].rsplit('.', 1)[0])}_{base[key]}" for key, name in named.items()}


def _unmarkable(call: _Call) -> bool:
    return "<" in call.symbol or call.symbol.count(".") > 1 or call.callable == "nested"


def build_watch_map(payload: Mapping[str, Any]) -> WatchMap:
    entries_raw = list(payload.get("commands") or ())
    commands = tuple(str(entry.get("command", "")) for entry in entries_raw)
    confirm = _confirmer(payload)
    notes: list[str] = []
    searches: list[tuple[_Call, list[_Call]]] = []
    steps_under: Counter = Counter()
    for command_index, entry in enumerate(entries_raw):
        if entry.get("failure"):
            notes.append(f"command {command_index + 1} ({entry.get('command')}): {entry['failure']}")
        for process in entry.get("processes") or ():
            notes.extend(str(note) for note in process.get("notes") or ())
            if process.get("truncated"):
                notes.append(f"command {command_index + 1}: the watch stopped recording after its step limit; later steps are missing")
            calls = [_parse(command_index, raw, confirm) for raw in process.get("calls") or ()]
            steps = _assign_owners(calls)
            searches.extend((call, steps) for call in steps if call.owner is None)
            steps_under.update(_root(call).signature for call in steps if call.owner is not None)
    if not searches:
        return WatchMap(commands, None, None, tuple(None for _ in commands), (), searches_seen=0, notes=tuple(notes))

    # The most frequent; on a tie, the one that took a query, then the one with the most steps under it
    # (a corpus loader that ran once before the search is not the search). Only its searches make the map.
    started = Counter(call.signature for call, _steps in searches)
    with_query = {call.signature for call, _steps in searches if call.text}
    entry_key = max(started, key=lambda key: (started[key], key in with_query, steps_under[key]))
    entry_calls: list[_Call] = []
    marked: list[_Call] = []
    for call, steps in searches:
        if call.signature == entry_key:
            entry_calls.append(call)
            marked.extend(_analyse_search(call, steps, notes))
        else:
            notes.append(f"{call.symbol} ({call.path}) handled documents outside the search (returned {call.returned}); not part of the map")
    first_entry = {call.command: call for call in reversed(entry_calls)}
    query_parameter = next((call.text[0] for call in entry_calls if call.text), None)
    query_texts = tuple(first_entry[index].text[1] if index in first_entry and first_entry[index].text else None
                        for index in range(len(commands)))
    entrypoint = None
    if "<" in entry_key[1] or entry_key[1].count(".") > 1:
        notes.append(f"the search starts in {entry_key[1]} ({entry_key[0]}), which cannot carry a decorator; set discovery.entrypoint by hand")
    else:
        entrypoint = {"file": entry_key[0], "symbol": entry_key[1], "kind": "async_function" if entry_key[2] == "async" else "function"}

    grouped: dict[tuple[str, str], list[_Call]] = {}
    for call in marked:
        grouped.setdefault(call.key, []).append(call)
    unmarkable = tuple(
        {"symbol": calls[0].symbol, "relative_path": calls[0].path, "reason": "a nested function or lambda cannot carry a decorator"}
        for calls in grouped.values() if _unmarkable(calls[0])
    )
    kept = {key: calls for key, calls in grouped.items() if not _unmarkable(calls[0])}

    searched = sorted({call.command for call in entry_calls})
    chooser = None
    gate_key: tuple[str, str] | None = None
    if len(searched) > 1:
        by_command: dict[int, dict[tuple[str, str], str]] = {}
        for index in searched:
            entry = first_entry.get(index)
            if entry is not None:
                by_command[index] = {(item["path"], item["symbol"]): str(item["value"]) for item in entry.scalars}
        shared = set.intersection(*(set(values) for values in by_command.values())) if by_command else set()
        differing = [key for key in shared if len({values[key] for values in by_command.values()}) > 1]
        conditional_keys = [key for key, calls in kept.items() if sorted({call.command for call in calls}) != searched]
        if differing and conditional_keys:
            gate_key = sorted(differing)[0]
            chooser = {"symbol": gate_key[1], "relative_path": gate_key[0],
                       "values": {str(index): values[gate_key] for index, values in sorted(by_command.items())}}

    ids = _op_ids([*kept, *([gate_key] if gate_key else [])])
    built: list[WatchedStep] = []
    for key, calls in kept.items():
        kinds = Counter(kind for kind in (_kind(call) for call in calls) if kind is not None)
        step_notes: list[str] = []
        op_type = None
        if kinds:
            top = max(kinds.values())
            tied = [kind for kind in _KIND_ORDER if kinds.get(kind) == top]
            op_type = tied[0]
            if len(tied) > 1:
                step_notes.append(f"behaved as {' and '.join(tied)} equally often; chose {op_type}")
        else:
            step_notes.append("changed nothing in the watched searches, so its kind is not known from behaviour")
        parents: list[str] = []
        inputs_from: list[tuple[str, str]] = []
        for call in calls:
            for param, parent, _slot in call.links:
                if parent.key in ids and parent.key != key:
                    if ids[parent.key] not in parents:
                        parents.append(ids[parent.key])
                    if (param, ids[parent.key]) not in inputs_from:
                        inputs_from.append((param, ids[parent.key]))
                elif _unmarkable(parent):
                    note = f"{param} came from {parent.symbol}, which cannot carry a decorator; its documents enter here unlinked"
                    if note not in step_notes:
                        step_notes.append(note)
            for param in call.unlinked:
                owner = call.owner.symbol if call.owner else "the entrypoint"
                note = f"{param} received documents created inside {owner}, not by a separate function"
                if note not in step_notes:
                    step_notes.append(note)
        slots = Counter(call.slot for call in calls if call.slot is not None)
        last = max(calls, key=lambda call: (call.command, call.end))
        built.append(WatchedStep(
            op_id=ids[key], symbol=key[1], relative_path=key[0], op_type=op_type,
            parent_ids=tuple(parents), inputs_from=tuple(inputs_from),
            invocation="async" if any(call.callable == "async" for call in calls) else "sync",
            output_bundle=slots.most_common(1)[0][0] if slots else None,
            commands=tuple(sorted({call.command for call in calls})),
            took=last.took, returned=last.returned,
            inside=tuple(dict.fromkeys(item for call in calls for item in call.inside)),
            notes=tuple(step_notes),
        ))
    if gate_key is not None:
        built.append(WatchedStep(
            op_id=ids[gate_key], symbol=gate_key[1], relative_path=gate_key[0], op_type="GATE", commands=tuple(searched),
            notes=("returned a different route for each watched path; confirm it is the function that chooses the path",),
        ))
    conditional = tuple(step.op_id for step in built if step.op_type != "GATE" and len(searched) > 1 and list(step.commands) != searched)
    return WatchMap(
        commands=commands, entrypoint=entrypoint, query_parameter=query_parameter, query_texts=query_texts,
        steps=tuple(built), conditional=conditional, chooser=chooser, unmarkable=unmarkable,
        searches_seen=len(entry_calls), notes=tuple(dict.fromkeys(notes)),
    )
