from __future__ import annotations

import ast
from collections import Counter
from dataclasses import replace
import itertools
import json
from pathlib import Path
import re
import shlex
from types import SimpleNamespace
from typing import Any, Callable

from retrieval_observatory.datasets.records import evaluate_inputs, read_json_records
from retrieval_observatory.integrations.detect import DetectionResult, detect_project, is_non_runtime_path, iter_project_files
from retrieval_observatory.integrations.model import (
    ADAPTER_MODULE,
    FinalBoundary,
    IdentityChoice,
    IntegrationPlan,
    OperatorMapping,
    PatchOperation,
    PlannedAction,
    VerificationScenario,
)
from retrieval_observatory.tracing.capture import _CANDIDATE_PARAMETERS

#: Matched against a symbol's name tokens (``_name_tokens``): a token must start with a stem, and a
#: GATE token must equal one, so ``aggregate`` is not a gate and ``researcher`` is not a search.
_TYPE_RULES = (
    (r"\b(?:gate|gates|intent|route|router|routing)\b", "GATE"),
    (r"\b(?:fuse|fusion|rrf)", "FUSE"),
    (r"\bfilter", "FILTER"),
    (r"\b(?:rerank|cross encoder)", "RERANK"),
    (r"\b(?:source|retriev|search|bm25|dense|relevant documents)", "SOURCE"),
)
#: Predicates, factories and formatters: a name match with one of these prefixes is not an operator.
_NOT_OPERATOR_PREFIXES = (
    "is_", "has_", "should_", "can_", "get_", "load_", "build_", "make_", "create_", "init_",
    "format_", "render_", "print_", "aggregate_", "summarize_",
)
_SCALAR_ANNOTATIONS = {"bool", "str", "int", "float", "None"}
_QUERY_PARAMETERS = {"query", "q", "question", "text"}
_LANE_PARAMETERS = {"lanes", "groups", "lists"}
_HTTP_DECORATOR_METHODS = {"get", "post", "put", "patch", "delete", "route", "api_route", "websocket"}
_RETRIEVAL_ROUTE = re.compile(r"search|retriev|query|ask|rag|answer|chat", re.I)
#: Below this a name-only match is not instrumented; ``IntegrationPlan.validate_for_apply``
#: enforces the same threshold on hand-edited plans.
APPLY_CONFIDENCE = 0.8
_OBSERVE_IMPORT = re.compile(r"^from retrieval_observatory\.sdk(?:\.observe)? import .*\bobserve\b")
_SCOPE_IMPORT = re.compile(r"^from retrieval_observatory\.sdk(?:\.observe)? import .*\btrace_scope\b")
#: Marks every module apply edits; ``--phase revert`` restores the pre-apply bytes from the manifest.
INSTRUMENTATION_MARKER = "# retobs instrumentation: added by 'retobs integrate --phase apply'; remove with '--phase revert'"
#: Frameworks with a pip extra of their own (FastAPI projects need only the base package).
_FRAMEWORK_EXTRAS = {"langchain", "llamaindex"}
#: Needles in priority order: a ``qrels`` file wins over a ``labels`` export that sorts first.
_JUDGMENT_FILES = (("queries", ("quer",)), ("qrels", ("qrel", "judg", "label")), ("corpus", ("corpus", "docs", "document")))
_CAPTURE_FIELDS = ("inputs", "outputs", "decisions")
SCENARIO_QUERY_TEXT = "retobs verification query"
#: Judgment files are validated on at most this many lines each.
JUDGMENT_ROW_LIMIT = 100_000
#: The packaged agent runbook; reported in ``discovery.runbook`` so MCP-only agents can find it.
RUNBOOK_PATH = Path(__file__).resolve().parents[1] / "examples" / "agent_integration" / "SKILL.md"

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
#: ``(relative_path, symbol, node, kind)`` of the function the verification scenarios call.
Entrypoint = tuple[str, str, FunctionNode, str]


def stable_op_id(relative_path: str, symbol: str) -> str:
    del relative_path
    return re.sub(r"[^a-z0-9]+", "_", symbol.lower()).strip("_")


def _fixture_identity(root: Path) -> tuple[str, str]:
    expected_path = root / "expected.json"
    if expected_path.is_file():
        try:
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            service_id = expected.get("service_id")
            pipeline_id = expected.get("pipeline_id")
            if isinstance(service_id, str) and isinstance(pipeline_id, str):
                return service_id, pipeline_id
        except (OSError, ValueError):
            pass
    return root.name, f"{root.name}-retrieval"


def _name_tokens(symbol: str) -> str:
    """``symbol`` as lower-case, space-separated tokens: ``BM25Retriever`` -> ``bm25 retriever``."""
    return " ".join(re.split(r"[^A-Za-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", symbol))).strip().lower()


def _op_type(symbol: str) -> str | None:
    tokens = _name_tokens(symbol)
    return next((kind for pattern, kind in _TYPE_RULES if re.search(pattern, tokens)), None)


def _is_boolean(value: ast.expr) -> bool:
    return (
        isinstance(value, (ast.Compare, ast.BoolOp))
        or (isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not))
        or (isinstance(value, ast.Constant) and isinstance(value.value, bool))
    )


def _operator_shape(node: FunctionNode, op_type: str) -> bool:
    """Whether a name match looks like an operator rather than a predicate, factory or formatter.

    Excluded: a predicate/factory/formatter name prefix; for a non-GATE, a ``bool``/``str``/number/
    ``None`` return annotation or only comparison, boolean, f-string or constant returns, and (past
    a SOURCE) no parameter besides the query. A GATE must take a query or candidates and must not
    return a boolean; a route label (a string) is its output.
    """
    if node.name.startswith(_NOT_OPERATOR_PREFIXES):
        return False
    annotation = node.returns
    annotated = (
        annotation.id if isinstance(annotation, ast.Name)
        else str(annotation.value) if isinstance(annotation, ast.Constant)
        else None
    )
    values = [item.value for item in ast.walk(node) if isinstance(item, ast.Return) and item.value is not None]
    names, vararg = _signature(node)
    if op_type == "GATE":
        takes_input = vararg is not None or any(name in _QUERY_PARAMETERS or name in _CANDIDATE_PARAMETERS for name in names)
        return takes_input and annotated != "bool" and not (values and all(_is_boolean(value) for value in values))
    scalar = all(_is_boolean(value) or isinstance(value, (ast.JoinedStr, ast.Constant)) for value in values)
    if annotated in _SCALAR_ANNOTATIONS or (values and scalar):
        return False
    return op_type == "SOURCE" or vararg is not None or any(name not in _QUERY_PARAMETERS for name in names)


def _left_out(operator: OperatorMapping, reason: str) -> dict[str, object]:
    """A ``discovery.low_confidence_operators`` entry for a discovered operator the plan does not propose."""
    return {
        "symbol": operator.symbol, "relative_path": operator.relative_path, "op_type": operator.op_type,
        "confidence": operator.confidence, "reason": reason,
    }


def _is_test_path(relative: Path) -> bool:
    name = relative.name
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def _is_skipped(relative: Path) -> bool:
    # The project's capture adapter defines CaptureSpecs, not operators, so its helpers are never proposed.
    return relative.name == f"{ADAPTER_MODULE}.py" or _is_test_path(relative)


def _route_decorator(node: FunctionNode) -> ast.Call | None:
    """The ``@app.<method>(...)`` / ``@router.<method>(...)`` decorator of an HTTP route handler."""
    for decorator in node.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.attr in _HTTP_DECORATOR_METHODS
        ):
            return decorator
    return None


def _route_path(decorator: ast.Call) -> str:
    first = decorator.args[0] if decorator.args else None
    return first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else ""


def _parameters(node: FunctionNode) -> list[str]:
    names = [item.arg for item in (*node.args.posonlyargs, *node.args.args)]
    if names and names[0] in ("self", "cls"):
        names = names[1:]
    return names


def _signature(node: FunctionNode) -> tuple[list[str], str | None]:
    """Parameter names (positional, then keyword-only; no self/cls) and the ``*args`` name."""
    names = [*_parameters(node), *(item.arg for item in node.args.kwonlyargs)]
    return names, node.args.vararg.arg if node.args.vararg else None


def _returns_value(node: FunctionNode) -> bool:
    return any(isinstance(item, ast.Return) and item.value is not None for item in ast.walk(node))


def _confidence(node: FunctionNode, op_type: str) -> float:
    """0.9 when the body looks like an operator, 0.6 when only the name matched.

    A SOURCE must take a query-like parameter (``query``/``q``/``question``/``text``); every other
    operator must take at least one argument (its candidates). Both must return a value: a helper
    that merely builds a retriever, or a method with a lone ``k`` argument, is a name-only hit.
    """
    parameters = _parameters(node)
    keyword_only = {item.arg for item in node.args.kwonlyargs}
    if not _returns_value(node):
        return 0.6
    if op_type == "SOURCE":
        query_like = bool(parameters) and (parameters[0] in _QUERY_PARAMETERS or bool(set(parameters) & _QUERY_PARAMETERS))
        return 0.9 if query_like or bool(keyword_only & _QUERY_PARAMETERS) else 0.6
    return 0.9 if parameters or node.args.vararg else 0.6


def _input_mapping(node: FunctionNode, parent_ids: tuple[str, ...]) -> str:
    """Static mirror of ``capture.default_input_groups``: how the actual inputs will be read."""
    names, vararg = _signature(node)
    if not parent_ids:
        query = next((name for name in names if name in _QUERY_PARAMETERS), names[0] if names else None)
        return f"query:{query}" if query else "unavailable"
    if not names and vararg is None:
        return "unavailable"
    if all(parent in names for parent in parent_ids):
        return "parameters:" + ",".join(parent_ids)
    if len(parent_ids) == 1:
        candidates = [name for name in names if name in _CANDIDATE_PARAMETERS]
        if len(candidates) != 1:
            candidates = [name for name in names if name not in _QUERY_PARAMETERS]
        return f"parameter:{candidates[0]}" if len(candidates) == 1 else "default"
    lanes = vararg or next((name for name in names if name in _LANE_PARAMETERS), None)
    return f"positional_lanes:{lanes}" if lanes else "default"


def _capture_coverage(adapter: Path, symbol: str) -> set[str] | None:
    """The ``CaptureSpec`` fields ``symbol = CaptureSpec(...)`` sets in the root adapter; ``None`` when unreadable statically."""
    try:
        tree = ast.parse(adapter.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        call = getattr(node, "value", None)
        if not any(isinstance(item, ast.Name) and item.id == symbol for item in targets) or not isinstance(call, ast.Call):
            continue
        name = call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", None)
        if name != "CaptureSpec" or any(isinstance(item, ast.Starred) for item in call.args) or any(k.arg is None for k in call.keywords):
            return None
        given = {**dict(zip(_CAPTURE_FIELDS, call.args)), **{keyword.arg: keyword.value for keyword in call.keywords}}
        return {field for field, value in given.items() if not (isinstance(value, ast.Constant) and value.value is None)}
    return None


def _describe_boundary(node: FunctionNode, operator: OperatorMapping, root: Path) -> OperatorMapping:
    """Fill the mappings the source determines; a reviewed ``capture`` governs only the sides its spec maps.

    A spec with only ``inputs`` leaves outputs to the default return-value capture (``return``); a
    spec that cannot be read statically is taken to govern both sides.
    """
    covered: set[str] = set()
    if operator.capture:
        found = _capture_coverage(root / f"{ADAPTER_MODULE}.py", operator.capture.split(":", 1)[-1])
        covered = {"inputs", "outputs"} if found is None else found
    return replace(
        operator,
        input_mapping="capture" if "inputs" in covered else _input_mapping(node, operator.parent_ids),
        output_mapping="capture" if "outputs" in covered else ("return" if _returns_value(node) else "unavailable"),
        invocation="async" if isinstance(node, ast.AsyncFunctionDef) else "sync",
    )


def _mapping_questions(operator: OperatorMapping) -> list[str]:
    where = f"operator {operator.op_id} ({operator.symbol} in {operator.relative_path})"
    fix = (
        f"define a CaptureSpec named {operator.op_id}_capture in {ADAPTER_MODULE}.py and set "
        f'capture: "{ADAPTER_MODULE}:{operator.op_id}_capture" on it in the plan'
    )
    questions = []
    if operator.input_mapping in ("default", "unavailable"):
        questions.append(f"{where}: actual inputs cannot be read statically (input_mapping={operator.input_mapping}); {fix}")
    elif operator.input_mapping.startswith("positional_lanes:"):
        questions.append(
            f"{where}: lanes are matched to parents by position (verify reports inferred_inputs, partial); "
            f"for an exact lane-to-parent mapping {fix}"
        )
    if operator.output_mapping == "unavailable":
        questions.append(f"{where}: no returned value to read outputs from; {fix}")
    return questions


def _candidate_functions(tree: ast.Module) -> list[tuple[str, str, FunctionNode]]:
    """``(symbol, call_name, node)`` for module-level functions and class methods."""
    found: list[tuple[str, str, FunctionNode]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append((node.name, node.name, node))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not (
                    item.name.startswith("__") and item.name.endswith("__")
                ):
                    found.append((f"{node.name}.{item.name}", item.name, item))
    return [entry for entry in found if not entry[2].name.startswith("test_")]


def _locate(root: Path, relative: str, symbol: str, functions: dict[tuple[str, str], FunctionNode]) -> FunctionNode | None:
    """The function ``symbol`` (``name`` or ``Class.method``) in ``relative``; parses files the scan skipped."""
    if (relative, symbol) not in functions:
        try:
            tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            return None
        for found, _call_name, node in _candidate_functions(tree):
            functions.setdefault((relative, found), node)
    return functions.get((relative, symbol))


def _import_insertion_line(source: str, tree: ast.Module) -> int:
    """Zero-based line index for a new top-level import.

    Must land after the shebang, any encoding cookie, the module docstring, and every
    `from __future__` import — a `__future__` import that is not the first statement is a
    SyntaxError, and jumping the docstring silently demotes it to a bare expression.
    """
    lines = source.splitlines()
    insert_at = 0
    while insert_at < len(lines) and insert_at < 2 and (
        lines[insert_at].startswith("#!") or re.match(r"^#.*coding[:=]", lines[insert_at])
    ):
        insert_at += 1
    for node in tree.body:
        is_docstring = (
            node is tree.body[0]
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        is_future = isinstance(node, ast.ImportFrom) and node.module == "__future__"
        if not (is_docstring or is_future):
            break
        insert_at = max(insert_at, (node.end_lineno or node.lineno))
    return insert_at


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _instrument_source(
    source: str,
    nodes: list[tuple[FunctionNode, OperatorMapping]],
    entrypoint: tuple[FunctionNode, str] | None = None,
) -> str:
    """Add ``@observe`` to each operator and, outermost of the two, ``@trace_scope`` to the entrypoint."""
    lines = source.splitlines(keepends=True)
    needs_observe = bool(nodes) and not any(_OBSERVE_IMPORT.match(line) for line in lines)
    needs_scope = entrypoint is not None and not any(_SCOPE_IMPORT.match(line) for line in lines)
    insert_at = _import_insertion_line(source, ast.parse(source)) if needs_observe or needs_scope else -1
    # Decorators go in first, bottom-up, so every `node.lineno` still refers to the line it was
    # parsed from. The import is added afterwards at a position above all of them.
    by_line: dict[int, tuple[FunctionNode, list[str]]] = {}
    for node, operator in nodes:
        # A string reference: ``observe`` resolves it from the root adapter file, so no import
        # is added that would fail when the application does not run from the project root.
        capture = f', capture="{operator.capture}"' if operator.capture else ""
        by_line.setdefault(node.lineno, (node, []))[1].append(
            f'@observe("{operator.op_type}", op_id="{operator.op_id}", parent_ids={operator.parent_ids!r}{capture})\n'
        )
    if entrypoint is not None:
        # Listed first so it wraps ``@observe``: a trace must be active before the span is built.
        by_line.setdefault(entrypoint[0].lineno, (entrypoint[0], []))[1].insert(0, entrypoint[1] + "\n")
    for lineno, (node, decorators) in sorted(by_line.items(), reverse=True):
        original_index = lineno - 1
        indent = _indent(lines[original_index])
        existing_from = min((item.lineno for item in node.decorator_list), default=lineno) - 1
        nearby = "".join(lines[existing_from:original_index])
        for decorator in reversed(decorators):
            marker = decorator.split("(", 1)[0] + "("
            op_marker = re.search(r'op_id="[^"]*"', decorator)
            already = (op_marker.group(0) in nearby) if op_marker else (marker in nearby)
            if not already:
                lines.insert(original_index, indent + decorator)
    if needs_observe or needs_scope:
        names = [name for name, needed in (("observe", needs_observe), ("trace_scope", needs_scope)) if needed]
        lines.insert(insert_at, f"from retrieval_observatory.sdk.observe import {', '.join(names)}\n")
        if not any(line.rstrip("\n") == INSTRUMENTATION_MARKER for line in lines):
            lines.insert(insert_at, INSTRUMENTATION_MARKER + "\n")
    instrumented = "".join(lines)
    try:
        ast.parse(instrumented)
    except SyntaxError as error:  # pragma: no cover - guards against a malformed patch
        raise ValueError(f"instrumented source does not parse: {error}") from error
    return instrumented


def _module_name(relative: str) -> str:
    parts = Path(relative).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _import_name(root: Path, relative: str) -> tuple[str, str]:
    """``(import_root, module)``: the directory a file is imported from and its dotted name there.

    The import root is the parent of the file's topmost package directory (walking up while the
    directory has ``__init__.py``); a loose module's is its own directory. ``.`` is the project root:
    ``services/api/ticket_search/entry.py`` without ``services/api/__init__.py`` is
    ``("services/api", "ticket_search.entry")``.
    """
    directory = Path(relative).parent
    while directory.parts and (root / directory / "__init__.py").is_file():
        directory = directory.parent
    return directory.as_posix(), _module_name(str(Path(relative).relative_to(directory)))


def _imported_modules(relative: str, tree: ast.Module) -> set[str]:
    """Dotted names ``relative`` may import (every import, including function-level ones), with their packages."""
    package = Path(relative).parent.parts
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level > len(package) + 1:
                continue
            base = package[: len(package) - node.level + 1] if node.level else ()
            module = ".".join([*base, *(node.module.split(".") if node.module else [])])
            # ``from pkg import mod`` may name a submodule as well as an attribute.
            targets = [module, *(f"{module}.{alias.name}" if module else alias.name for alias in node.names)]
        else:
            continue
        for target in filter(None, targets):
            parts = target.split(".")
            names.update(".".join(parts[: index + 1]) for index in range(len(parts)))
    return names


def _import_resolver(trees: dict[str, ast.Module], root: Path) -> Callable[[str, str], str | None]:
    """``resolve(name, importer)``: the project file an import of dotted ``name`` in ``importer`` loads.

    Tried in order: the file named ``name`` under its import root (see ``_import_name``; a name
    several files share resolves to the one under the importer's own import root, else to none),
    the root-relative dotted name (relative imports resolve to these), a sibling of the importer
    (script-style), and last the one file whose root-relative name ends with ``.<name>``: a
    namespace package (no ``__init__.py``) imported from a directory put on ``PYTHONPATH``. Several
    such files, or a one-part name (``json``, ``models``), resolve to none.
    """
    roots: dict[str, str] = {}
    named: dict[str, list[str]] = {}
    index: dict[str, str] = {}
    suffixed: dict[str, list[str]] = {}
    for relative in trees:
        roots[relative], name = _import_name(root, relative)
        named.setdefault(name, []).append(relative)
        dotted = _module_name(relative)
        index.setdefault(dotted, relative)
        if dotted.startswith("src."):
            index.setdefault(dotted[len("src."):], relative)
        parts = dotted.split(".")
        for start in range(1, len(parts) - 1):
            suffixed.setdefault(".".join(parts[start:]), []).append(relative)

    def resolve(name: str, importer: str) -> str | None:
        found = named.get(name, [])
        own = [relative for relative in found if roots[relative] == roots.get(importer)]
        if len(own or found) == 1:
            return (own or found)[0]
        package = ".".join(Path(importer).parent.parts)
        by_suffix = suffixed.get(name, [])
        return (
            index.get(name)
            or (index.get(f"{package}.{name}") if package else None)
            or (by_suffix[0] if len(by_suffix) == 1 else None)
        )

    return resolve


def _reachable_files(entry: str, trees: dict[str, ast.Module], resolve: Callable[[str, str], str | None]) -> set[str]:
    """Project files reachable from ``entry`` through imports, each resolved by ``_import_resolver``."""
    seen, queue = {entry}, [entry]
    while queue:
        current = queue.pop()
        if current not in trees:
            continue
        for name in _imported_modules(current, trees[current]):
            target = resolve(name, current)
            if target is not None and target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def _entry_import_name(root: Path, relative: str, tree: ast.Module | None, resolve: Callable[[str, str], str | None]) -> tuple[str, str]:
    """``_import_name`` of the entrypoint; outside any package, the import root its own absolute imports imply.

    ``apps/py/ticket_rag/pipeline.py`` (no ``__init__.py``) importing ``ticket_rag.fusion``, which
    resolves to ``apps/py/ticket_rag/fusion.py``, is ``("apps/py", "ticket_rag.pipeline")``: the
    import must land in the top-level package directory that holds the entrypoint.
    """
    path = Path(relative)
    if tree is None or (root / path.parent / "__init__.py").is_file():
        return _import_name(root, relative)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.update([node.module, *(f"{node.module}.{alias.name}" for alias in node.names)])
    for name in sorted(names):
        target = resolve(name, relative)
        parts = tuple(name.split("."))
        found = tuple(_module_name(target).split(".")) if target else ()
        if found[-len(parts):] == parts:
            base = Path(*found[: -len(parts)])
            if path.is_relative_to(base / parts[0]):
                return base.as_posix(), _module_name(str(path.relative_to(base)))
    return _import_name(root, relative)


def _select_entrypoint(
    routes: list[tuple[str, str, FunctionNode, str]],
    functions: dict[tuple[str, str], FunctionNode],
    operators: list[tuple[str, OperatorMapping]],
    detection: DetectionResult,
    trees: dict[str, ast.Module],
    resolve: Callable[[str, str], str | None],
) -> Entrypoint | None:
    """``(relative_path, symbol, node, kind)`` of the function the verification scenarios call.

    Among detected ``retrieve``/``search`` functions, the one whose imports reach the most
    discovered operators wins (ties keep detection order): a helper named ``search`` must not
    become the entrypoint of the pipeline next to it. Nothing under a non-runtime dir (bench,
    eval, scripts, ...) is chosen.
    """
    routes = [route for route in routes if not is_non_runtime_path(route[0])]
    retrieval_routes = [route for route in routes if _RETRIEVAL_ROUTE.search(route[3] or route[1])]
    if retrieval_routes or routes:
        relative, symbol, node, _path = (retrieval_routes or routes)[0]
        return relative, symbol, node, "http_route"
    candidates = [
        (candidate.file, candidate.symbol, node)
        for candidate in detection.entrypoints
        if candidate.kind in ("function", "async_function")
        and not is_non_runtime_path(candidate.file)
        and (node := functions.get((candidate.file, candidate.symbol))) is not None
    ]
    if candidates:
        def coverage(candidate: tuple[str, str, FunctionNode]) -> int:
            reachable = _reachable_files(candidate[0], trees, resolve)
            return sum(1 for relative, _operator in operators if relative in reachable)

        relative, symbol, node = max(candidates, key=coverage)
        return relative, symbol, node, "function"
    parents = {parent for _relative, operator in operators for parent in operator.parent_ids}
    for relative, operator in operators:
        if operator.op_id not in parents:
            return relative, operator.symbol, functions[(relative, operator.symbol)], "operator"
    return None


def _discover_file_operators(
    relative: str, tree: ast.Module, candidates: list[tuple[str, str, FunctionNode]]
) -> tuple[list[tuple[FunctionNode, OperatorMapping]], list[dict[str, object]]]:
    """Operators in one module with parents inferred from plain-name calls, plus the name-only hits left out."""
    low_confidence: list[dict[str, object]] = []
    nodes: list[tuple[str, str, FunctionNode]] = []
    for symbol, call_name, node in candidates:
        op_type = _op_type(node.name)
        if op_type is None or _route_decorator(node) is not None:
            continue
        confidence = _confidence(node, op_type)
        if not _operator_shape(node, op_type):
            low_confidence.append({
                "symbol": symbol, "relative_path": relative, "op_type": op_type, "confidence": confidence,
                "reason": "not_operator_shape",
            })
            continue
        if confidence < APPLY_CONFIDENCE:
            low_confidence.append({"symbol": symbol, "relative_path": relative, "op_type": op_type, "confidence": confidence})
            continue
        nodes.append((symbol, call_name, node))
    ids = {symbol: stable_op_id(relative, symbol) for symbol, _call_name, _node in nodes}
    # Parentage is inferred from plain-name calls; a method is reachable by its bare name only
    # when no module-level function shares it.
    by_call_name: dict[str, str] = {}
    for symbol, call_name, _node in nodes:
        by_call_name.setdefault(call_name, symbol)
    parent_names: dict[str, set[str]] = {symbol: set() for symbol in ids}
    assigned_operators = {
        target.id: by_call_name[assignment.value.func.id]
        for assignment in ast.walk(tree)
        if isinstance(assignment, ast.Assign)
        and isinstance(assignment.value, ast.Call)
        and isinstance(assignment.value.func, ast.Name)
        and assignment.value.func.id in by_call_name
        for target in assignment.targets
        if isinstance(target, ast.Name)
    }

    def outer_known(value: ast.AST) -> list[ast.Call]:
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in by_call_name:
            return [value]
        return [call for child in ast.iter_child_nodes(value) for call in outer_known(child)]

    def record_call(call: ast.Call) -> str | None:
        children = [candidate for child in [*call.args, *(keyword.value for keyword in call.keywords)] for candidate in outer_known(child)]
        nested = [by_call_name[candidate.func.id] for candidate in children if isinstance(candidate.func, ast.Name)]
        named_parents = [
            assigned_operators[value.id]
            for value in [*call.args, *(keyword.value for keyword in call.keywords)]
            if isinstance(value, ast.Name) and value.id in assigned_operators
        ]
        for candidate in children:
            record_call(candidate)
        if isinstance(call.func, ast.Name) and call.func.id in by_call_name:
            symbol = by_call_name[call.func.id]
            parent_names[symbol].update([*nested, *named_parents])
            return symbol
        return None

    for symbol, _call_name, node in nodes:
        calls = [candidate for candidate in ast.walk(node) if isinstance(candidate, ast.Call)]
        nested_calls = {
            nested
            for call in calls
            for child in [*call.args, *(keyword.value for keyword in call.keywords)]
            for nested in ast.walk(child)
            if isinstance(nested, ast.Call)
        }
        for call in calls:
            callee = record_call(call)
            if callee and call not in nested_calls and callee != symbol:
                parent_names[symbol].add(callee)
    discovered = [
        (
            node,
            OperatorMapping(
                ids[symbol], _op_type(node.name) or "TRANSFORM", symbol, relative,
                tuple(ids[name] for name in ids if name in parent_names[symbol]), .9,
            ),
        )
        for symbol, _call_name, node in nodes
    ]
    return discovered, low_confidence


def _boundary(entrypoint: Entrypoint | None, operators: list[OperatorMapping]) -> FinalBoundary:
    if entrypoint is None:
        return FinalBoundary()
    relative, symbol, _node, kind = entrypoint
    if kind == "operator":
        op_id = next((op.op_id for op in operators if (op.relative_path, op.symbol) == (relative, symbol)), None)
        return FinalBoundary("operator_output", symbol, relative, op_id=op_id)
    return FinalBoundary("entrypoint_return", symbol, relative)


def _identity(entrypoint: Entrypoint | None, candidate_mapping: dict[str, str]) -> IdentityChoice:
    names = _signature(entrypoint[2])[0] if entrypoint else []
    return IdentityChoice(
        candidate_id_field=candidate_mapping["doc_id"].rsplit(".", 1)[-1],
        query_id="argument:query_id" if "query_id" in names else "hash:query_text",
        query_text_parameter=next((name for name in names if name in _QUERY_PARAMETERS), None),
    )


def _read_rows(path: Path) -> tuple[Any, bool]:
    """``retobs evaluate``'s records of a JSON/JSONL file, cut to its first ``JUDGMENT_ROW_LIMIT`` lines (``True`` when cut)."""
    with path.open(encoding="utf-8") as handle:
        head = list(itertools.islice(handle, JUDGMENT_ROW_LIMIT + 1))
    if len(head) <= JUDGMENT_ROW_LIMIT:
        return read_json_records(path), False
    return [json.loads(line) for line in head[:JUDGMENT_ROW_LIMIT] if line.strip()], True


def _first_query_text(root: Path, queries: str | None) -> str | None:
    """The first query's text as ``retobs evaluate`` reads the queries file; ``None`` when it does not load."""
    from retrieval_observatory.datasets.inmemory import InMemoryDataset

    if not queries:
        return None
    try:
        rows, _cut = _read_rows(root / queries)
        loaded = InMemoryDataset(rows[:1] if isinstance(rows, list) else rows).load()[0]
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return loaded[0].text if loaded and loaded[0].text else None


def _check_judgments(root: Path, found: dict[str, str | None]) -> tuple[list[str], list[str]]:
    """``(problems, remarks)`` for loading ``found``'s files the way ``retobs evaluate`` does.

    Problems: a file that does not load, no qrels query id among the queries, an empty corpus, or a
    qrels doc id missing from the corpus. A membership check against a file cut at
    ``JUDGMENT_ROW_LIMIT`` rows is skipped and said so in the remarks.
    """
    from retrieval_observatory.datasets.inmemory import InMemoryDataset

    rows: dict[str, Any] = {}
    cut: set[str] = set()
    remarks: list[str] = []
    try:
        for key in ("queries", "qrels", "corpus"):
            if found[key]:
                rows[key], was_cut = _read_rows(root / str(found[key]))
                if was_cut:
                    cut.add(key)
                    remarks.append(f"{found[key]} has more than {JUDGMENT_ROW_LIMIT} rows: checked the first {JUDGMENT_ROW_LIMIT} rows only")
        if found["corpus"] and not rows["corpus"]:
            return [f"corpus {found['corpus']} is empty"], remarks
        # evaluate refuses to run without a corpus; with none chosen a stand-in keeps that out of these checks.
        module = SimpleNamespace(QUERIES=rows["queries"], QRELS=rows["qrels"], CORPUS=rows.get("corpus") or {"": ""})
        query_rows, corpus, qrels = evaluate_inputs(module, None, None, None)
        queries = InMemoryDataset(query_rows, corpus, qrels).load()[0]
        judged = {str(query_id): {str(doc_id) for doc_id in relevant} for query_id, relevant in dict(qrels or {}).items()}
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError) as error:
        files = ", ".join(str(path) for path in found.values() if path)
        return [f"{files} do not load the way retobs evaluate reads them: {type(error).__name__}: {error}"], remarks
    if not judged:
        return [f"qrels {found['qrels']} has no rows with a query_id"], remarks
    problems: list[str] = []
    missing = set(judged) - {query.query_id for query in queries}
    if "queries" not in cut and len(missing) == len(judged):
        problems.append(f"none of the {len(judged)} qrels query ids are in the queries {found['queries']}")
    elif "queries" not in cut and missing:
        remarks.append(f"{len(missing)} of {len(judged)} qrels query ids are not in the queries {found['queries']}")
    documents = set().union(*judged.values())
    if found["corpus"] and "corpus" not in cut and (absent := documents - set(corpus)):
        problems.append(f"{len(absent)} of {len(documents)} qrels doc ids are not in the corpus {found['corpus']}")
    return problems, remarks


def _judgments(root: Path, datasets: list[str]) -> dict[str, Any]:
    """Queries, qrels and corpus files ``retobs evaluate`` accepts, preferring one directory holding all of them.

    ``resolved`` when a directory's (or, with none holding both, the best-named) queries and qrels
    load and agree; ``candidate`` when files were found but a check failed (see ``notes``);
    ``unresolved`` when queries or qrels are missing.
    """
    def pick(paths: list[str]) -> dict[str, str | None]:
        return {
            key: next((path for needle in needles for path in paths if needle in Path(path).name.lower()), None)
            for key, needles in _JUDGMENT_FILES
        }

    by_dir: dict[str, list[str]] = {}
    for path in datasets:
        by_dir.setdefault(str(Path(path).parent), []).append(path)
    choices = [found for paths in by_dir.values() if (found := pick(paths))["queries"] and found["qrels"]] or [pick(datasets)]
    checked: list[tuple[dict[str, str | None], list[str], list[str]]] = []
    for found in choices:
        if not (found["queries"] and found["qrels"]):
            checked.append((found, [], []))
            break
        problems, remarks = _check_judgments(root, found)
        checked.append((found, problems, remarks))
        if not problems:
            break
    # The first choice that passes; with none passing, the first one found, reported as a candidate.
    found, problems, remarks = next((item for item in checked if not item[1]), checked[0])
    notes = []
    if found["queries"] is None:
        notes.append("no queries file discovered: benchmark setup needs a queries JSON/JSONL file")
    if found["qrels"] is None:
        notes.append("no qrels file discovered: judgment mapping stays unavailable; candidate movement inspection still works")
    if found["corpus"] is None:
        notes.append("no corpus file discovered: pass --corpus to retobs evaluate when the pipeline needs one")
    status = "unresolved" if not (found["queries"] and found["qrels"]) else "candidate" if problems else "resolved"
    return {**found, "status": status, "notes": [*notes, *problems, *remarks]}


def _expected_capabilities(
    operators: list[OperatorMapping],
    identity: IdentityChoice,
    boundary: FinalBoundary,
    judgments: dict[str, Any],
    scenarios: tuple[VerificationScenario, ...],
) -> dict[str, str]:
    mapped = [
        op for op in operators
        if op.input_mapping not in ("default", "unavailable")
        and not op.input_mapping.startswith("positional_lanes:")
        and op.output_mapping != "unavailable"
    ]
    gates = [op for op in operators if op.op_type == "GATE"]
    routes_declared = any(scenario.route for scenario in scenarios)
    return {
        "topology_observed": "ready" if operators else "unavailable",
        "actual_input_output_capture": "ready" if operators and len(mapped) == len(operators) else "partial" if mapped else "unavailable",
        "candidate_identity": "ready" if operators else "unavailable",
        "query_identity": "ready" if identity.query_text_parameter or identity.query_id.startswith("argument:") else "partial",
        "final_output_capture": "ready" if boundary.kind != "unresolved" else "unavailable",
        "judgment_mapping": "ready" if judgments.get("status") == "resolved" else "unavailable",
        "declared_route_coverage": "partial" if gates and not routes_declared else "ready" if scenarios else "unavailable",
        "cross_run_entity_alignment": "ready",
    }


def _scenario_command(entrypoint: Entrypoint, import_name: tuple[str, str], query_text: str) -> str | None:
    """A ``python -c`` call of a module-level entrypoint, run from the project root with its import
    root (``_entry_import_name``) put on ``sys.path``; a route or method needs a reviewer-supplied command."""
    _relative, symbol, node, kind = entrypoint
    if kind == "http_route" or "." in symbol:
        return None
    import_root, module = import_name
    call = f"{symbol}({query_text!r})"
    code = f"from {module} import {symbol}; {call}"
    if isinstance(node, ast.AsyncFunctionDef):
        code = f"import asyncio; from {module} import {symbol}; asyncio.run({call})"
    if import_root != ".":
        code = f"import sys; sys.path.insert(0, {import_root!r}); {code}"
    # Double quotes unless the code holds a character the shell expands inside them.
    return f"python -c {shlex.quote(code)}" if re.search(r'["\\$`!]', code) else f'python -c "{code}"'


def _scenarios(
    operators: list[OperatorMapping], entrypoint: Entrypoint | None, import_name: tuple[str, str] | None, query_text: str
) -> tuple[VerificationScenario, ...]:
    """The same query twice: the repeat is what cross-run entity alignment is checked against."""
    ids = tuple(op.op_id for op in operators)
    edges = tuple((parent, op.op_id) for op in operators for parent in op.parent_ids)
    command = _scenario_command(entrypoint, import_name, query_text) if entrypoint and import_name else None
    return tuple(
        VerificationScenario(scenario_id, query_text, ids, edges, command=command)
        for scenario_id in ("representative", "representative-repeat")
    )


def _qualify_duplicate_ids(root: Path, operators: list[OperatorMapping]) -> list[OperatorMapping]:
    """Operators sharing an op_id get their module as a prefix (``retrieval_app_lanes_keyword__filter_candidates``);
    parent ids, always inferred within one file, follow the rename.

    The module is the dotted name under the import root; where that still collides (two loose
    ``lanes.py`` in different dirs) it is the project-relative dotted path, unique per file.
    """
    def qualified(op: OperatorMapping, module: str) -> str:
        return f"{stable_op_id(op.relative_path, module)}__{op.op_id}"

    counts = Counter(op.op_id for op in operators)
    renamed = {
        (op.relative_path, op.op_id): qualified(op, _import_name(root, op.relative_path)[1])
        for op in operators
        if counts[op.op_id] > 1
    }
    final = Counter(renamed.get((op.relative_path, op.op_id), op.op_id) for op in operators)
    renamed = {
        key: new if final[new] == 1 else qualified(op, _module_name(op.relative_path))
        for op in operators
        if (new := renamed.get(key := (op.relative_path, op.op_id))) is not None
    }
    return [
        replace(
            op,
            op_id=renamed.get((op.relative_path, op.op_id), op.op_id),
            parent_ids=tuple(renamed.get((op.relative_path, parent), parent) for parent in op.parent_ids),
        )
        for op in operators
    ]


def _benchmark_setup(
    entrypoint: Entrypoint | None, import_name: tuple[str, str] | None, judgments: dict[str, Any], db_path: str, pipeline_id: str
) -> PlannedAction:
    """``retobs evaluate`` run from the project root: a loose module by file path, a package module
    as ``module:callable`` with its import root on ``PYTHONPATH`` (the file loader cannot resolve
    relative imports or a nested import root)."""
    resolved = judgments.get("status") == "resolved"
    if resolved and entrypoint is not None and entrypoint[3] == "function" and import_name is not None:
        relative, symbol, _node, _kind = entrypoint
        import_root, module = import_name
        target = f"{module}:{symbol}" if "." in module else f"{relative}:{symbol}"
        pythonpath = f"PYTHONPATH={shlex.quote(import_root)} " if "." in module and import_root != "." else ""
        corpus = f" --corpus {judgments['corpus']}" if judgments.get("corpus") else ""
        command = (
            f"{pythonpath}retobs evaluate {target} --queries {judgments['queries']} --qrels {judgments['qrels']}{corpus}"
            f" --name {pipeline_id} --db {db_path}"
        )
        return PlannedAction("benchmark_setup", f"evaluate {symbol} against the discovered queries and qrels", command)
    needs = []
    if not (entrypoint is not None and entrypoint[3] == "function"):
        needs.append("a module-level callable retrieve(query) -> list")
    if not resolved:
        needs.append("queries and qrels files")
    return PlannedAction(
        "benchmark_setup",
        "benchmark setup needs " + " and ".join(needs) + "; then run retobs evaluate <file.py:callable> --queries ... --qrels ... --db " + db_path,
    )


def build_integration_plan(
    project_root: Path,
    framework: str | None = None,
    *,
    db_path: str = ".retobs/results.db",
    reviewed: IntegrationPlan | None = None,
) -> IntegrationPlan:
    """Discover operators and the entrypoint, or re-plan from a reviewed plan.

    With ``reviewed`` its operators are taken as given (each symbol is checked against the source;
    a missing one is ``unresolved``), its scenarios, identity, judgments, candidate mapping,
    entrypoint and reviewer ``notes`` are kept when set, and everything derived from them
    (patches, boundary, actions, expected capabilities, open questions, plan_id) is regenerated.

    Without ``reviewed``, operators in files no import path from the entrypoint reaches are
    listed under ``discovery.low_confidence_operators`` instead of proposed.
    """
    root = project_root.resolve()
    service_id, pipeline_id = _fixture_identity(root)
    detection = detect_project(root, framework)
    operators: list[OperatorMapping] = []
    low_confidence: list[dict[str, object]] = []
    located: dict[tuple[str, str], FunctionNode] = {}
    functions: dict[tuple[str, str], FunctionNode] = {}
    routes: list[tuple[str, str, FunctionNode, str]] = []
    unresolved: list[str] = []
    trees: dict[str, ast.Module] = {}
    for path in iter_project_files(root, (".py",)):
        relative_path = path.relative_to(root)
        if _is_skipped(relative_path):
            continue
        relative = str(relative_path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        trees[relative] = tree
        candidates = _candidate_functions(tree)
        for symbol, _call_name, node in candidates:
            functions[(relative, symbol)] = node
            decorator = _route_decorator(node)
            if decorator is not None:
                routes.append((relative, symbol, node, _route_path(decorator)))
        if reviewed is None:
            discovered, low = _discover_file_operators(relative, tree, candidates)
            if is_non_runtime_path(relative_path):
                # Bench, eval, report and script code drives or measures the pipeline; it is not part of it.
                low_confidence.extend({**item, "reason": "non_runtime_dir"} for item in low)
                low_confidence.extend(_left_out(operator, "non_runtime_dir") for _node, operator in discovered)
                continue
            low_confidence.extend(low)
            for node, operator in discovered:
                operators.append(operator)
                located[(relative, operator.symbol)] = node
    if reviewed is not None:
        operators = list(reviewed.operators)
        for operator in operators:
            node = _locate(root, operator.relative_path, operator.symbol, functions)
            if node is None:
                unresolved.append(f"operator {operator.op_id}: symbol {operator.symbol} not found in {operator.relative_path}")
            else:
                located[(operator.relative_path, operator.symbol)] = node
    resolve = _import_resolver(trees, root)
    reviewed_entry = reviewed.discovery.get("entrypoint") if reviewed is not None else None
    if reviewed_entry:
        node = _locate(root, reviewed_entry["file"], reviewed_entry["symbol"], functions)
        if node is None:
            unresolved.append(f"entrypoint {reviewed_entry['symbol']} not found in {reviewed_entry['file']}")
        entrypoint = (reviewed_entry["file"], reviewed_entry["symbol"], node, reviewed_entry["kind"]) if node is not None else None
    else:
        sourced = [(op.relative_path, op) for op in operators if (op.relative_path, op.symbol) in located]
        entrypoint = _select_entrypoint(routes, functions, sourced, detection, trees, resolve)
    unreachable = False
    if reviewed is None and entrypoint is not None and entrypoint[3] != "operator":
        # A name match no import path from the entrypoint reaches (a script, a notebook, an
        # unrelated module) is left for the reviewer rather than instrumented.
        reachable = _reachable_files(entrypoint[0], trees, resolve)
        low_confidence.extend(_left_out(op, "unreachable_from_entrypoint") for op in operators if op.relative_path not in reachable)
        unreachable = bool(operators) and not any(op.relative_path in reachable for op in operators)
        if unreachable:
            unresolved.append(
                f"no operator is reachable by import from {entrypoint[0]}:{entrypoint[1]}: set discovery.entrypoint to the "
                "function that runs the pipeline, or list its operators in a reviewed plan"
            )
        operators = [op for op in operators if op.relative_path in reachable]
    if reviewed is None:
        operators = _qualify_duplicate_ids(root, operators)
    # After qualification: a ``parameters:<parent ids>`` mapping must name the final ids.
    operators = [
        _describe_boundary(located[key], operator, root) if (key := (operator.relative_path, operator.symbol)) in located else operator
        for operator in operators
    ]
    discovered_by_file: dict[str, list[tuple[FunctionNode, OperatorMapping]]] = {}
    for operator in operators:
        node = located.get((operator.relative_path, operator.symbol))
        if node is not None:
            discovered_by_file.setdefault(operator.relative_path, []).append((node, operator))
    patches: list[PatchOperation] = []
    edits: list[PlannedAction] = []
    for relative in sorted({*discovered_by_file, *([entrypoint[0]] if entrypoint else [])}):
        path = root / relative
        source = path.read_text(encoding="utf-8")
        scope = None
        if entrypoint is not None and entrypoint[0] == relative:
            scope = (entrypoint[2], f'@trace_scope("{service_id}", "{pipeline_id}", db_path="{db_path}")')
        file_operators = discovered_by_file.get(relative, [])
        replacement = _instrument_source(source, file_operators, scope)
        if replacement != source:
            patches.append(PatchOperation.from_file(root, path, replacement))
            added = [f"@observe to {', '.join(op.op_id for _node, op in file_operators)}"] if file_operators else []
            if scope:
                added.append(f"@trace_scope to {entrypoint[1]}")
            edits.append(PlannedAction("source_edit", f"edit {relative}: add " + " and ".join(added), performed_by="apply"))
    if not operators and not unreachable:
        unresolved.append("no retrieval operators discovered")
    mapping = dict(reviewed.candidate_mapping) if reviewed is not None and reviewed.candidate_mapping else {
        "doc_id": "item.id", "score": "item.score", "rank": "enumerate",
    }
    datasets = sorted(
        str(path.relative_to(root))
        for path in iter_project_files(root, (".jsonl", ".json", ".csv", ".parquet"), {"venv", "node_modules", "retobs"})
    )
    discovery = {
        "entrypoints": [candidate.__dict__ for candidate in detection.entrypoints],
        "entrypoint": (
            {"file": entrypoint[0], "symbol": entrypoint[1], "kind": entrypoint[3]} if entrypoint else None
        ),
        "http_routes": detection.http_routes,
        "datasets": datasets,
        "operator_symbols": [operator.symbol for operator in operators],
        "low_confidence_operators": low_confidence,
        "db_path": db_path,
        "runbook": str(RUNBOOK_PATH) if RUNBOOK_PATH.is_file() else None,
    }
    judgments = dict(reviewed.judgments) if reviewed is not None and reviewed.judgments else _judgments(root, datasets)
    identity = reviewed.identity if reviewed is not None else _identity(entrypoint, mapping)
    generated = not (reviewed is not None and reviewed.scenarios)
    query_text = _first_query_text(root, judgments.get("queries")) or SCENARIO_QUERY_TEXT
    import_name = _entry_import_name(root, entrypoint[0], trees.get(entrypoint[0]), resolve) if entrypoint else None
    scenarios = _scenarios(operators, entrypoint, import_name, query_text) if generated else reviewed.scenarios
    # A blank command runs nothing: it is a missing command, stated as such (``None``) and asked for.
    scenarios = tuple(
        scenario if scenario.command is None or scenario.command.strip() else replace(scenario, command=None)
        for scenario in scenarios
    )
    boundary = _boundary(entrypoint, operators)
    open_questions = [question for operator in operators for question in _mapping_questions(operator)]
    if judgments.get("status") != "resolved":
        open_questions.append(
            f"judgments are {judgments.get('status')}: " + "; ".join(judgments.get("notes") or ())
            + "; set judgments.queries/qrels/corpus to files retobs evaluate accepts, then status to resolved"
        )
    if generated and query_text == SCENARIO_QUERY_TEXT:
        open_questions.append(
            f"scenario query_text is the placeholder {SCENARIO_QUERY_TEXT!r}: no queries file loads; "
            "set each scenario's query_text and command to a real query"
        )
    if entrypoint is None:
        open_questions.append("no entrypoint found: set discovery.entrypoint {file, symbol, kind} in the plan and each scenario's command")
        target = "the call that exercises the pipeline's entrypoint"
    else:
        route = next((item[3] for item in routes if item[:2] == entrypoint[:2]), None)
        target = (
            f"the request that exercises route {route or entrypoint[1]} ({entrypoint[1]} in {entrypoint[0]})"
            if entrypoint[3] == "http_route"
            else f"the call that exercises {entrypoint[1]} in {entrypoint[0]}"
        )
    open_questions.extend(
        f"scenario {scenario.scenario_id}: set command to {target}; until then nothing runs it and verify reports it unobserved"
        for scenario in scenarios
        if scenario.command is None
    )
    if not any(scenario.route for scenario in scenarios):
        open_questions.extend(f"gate {op.op_id}: declare one scenario per route with `route` set" for op in operators if op.op_type == "GATE")
    package = f'"retrieval-observatory[{detection.framework}]"' if detection.framework in _FRAMEWORK_EXTRAS else "retrieval-observatory"
    actions = (
        PlannedAction("install", "install retobs into the project's environment", f"pip install {package}"),
        *edits,
        _benchmark_setup(entrypoint, import_name, judgments, db_path, pipeline_id),
        *(
            PlannedAction(
                "scenario_execution",
                f"run scenario {scenario.scenario_id} against the instrumented project" + ("" if scenario.command else " (command not yet supplied)"),
                scenario.command,
            )
            for scenario in scenarios
        ),
    )
    return IntegrationPlan.create(
        project_root=root,
        framework=detection.framework,
        service_id=service_id,
        pipeline_id=pipeline_id,
        patches=patches,
        operators=operators,
        candidate_mapping=mapping,
        scenarios=scenarios,
        unresolved=unresolved,
        discovery=discovery,
        boundary=boundary,
        identity=identity,
        judgments=judgments,
        expected_capabilities=_expected_capabilities(operators, identity, boundary, judgments, scenarios),
        actions=actions,
        open_questions=open_questions,
        notes=reviewed.notes if reviewed is not None else None,
    )
