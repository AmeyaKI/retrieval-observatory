from __future__ import annotations

import ast
import json
from pathlib import Path
import re

from retrieval_observatory.integrations.detect import DetectionResult, detect_project
from retrieval_observatory.integrations.model import IntegrationPlan, OperatorMapping, PatchOperation, VerificationScenario

_TYPE_RULES = (
    (r"gate|intent|route", "GATE"),
    (r"fuse|fusion|rrf", "FUSE"),
    (r"filter", "FILTER"),
    (r"rerank|cross_encoder", "RERANK"),
    (r"source|retriev|search|bm25|dense|relevant_documents", "SOURCE"),
)
_QUERY_PARAMETERS = {"query", "q", "question", "text"}
_HTTP_DECORATOR_METHODS = {"get", "post", "put", "patch", "delete", "route", "api_route", "websocket"}
_RETRIEVAL_ROUTE = re.compile(r"search|retriev|query|ask|rag|answer|chat", re.I)
_SKIP_PARTS = {"venv", "node_modules", "retobs", "tests", "test"}
#: Below this a name-only match is not instrumented; ``IntegrationPlan.validate_for_apply``
#: enforces the same threshold on hand-edited plans.
APPLY_CONFIDENCE = 0.8
_OBSERVE_IMPORT = re.compile(r"^from retrieval_observatory\.sdk(?:\.observe)? import .*\bobserve\b")
_SCOPE_IMPORT = re.compile(r"^from retrieval_observatory\.sdk(?:\.observe)? import .*\btrace_scope\b")

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


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


def _op_type(symbol: str) -> str | None:
    return next((kind for pattern, kind in _TYPE_RULES if re.search(pattern, symbol, re.I)), None)


def _is_test_path(relative: Path) -> bool:
    name = relative.name
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def _is_skipped(relative: Path) -> bool:
    return any(part.startswith(".") or part in _SKIP_PARTS for part in relative.parts) or _is_test_path(relative)


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


def _confidence(node: FunctionNode, op_type: str) -> float:
    """0.9 when the body looks like an operator, 0.6 when only the name matched.

    A SOURCE must take a query-like parameter (``query``/``q``/``question``/``text``); every other
    operator must take at least one argument (its candidates). Both must return a value: a helper
    that merely builds a retriever, or a method with a lone ``k`` argument, is a name-only hit.
    """
    parameters = _parameters(node)
    keyword_only = {item.arg for item in node.args.kwonlyargs}
    returns_value = any(isinstance(item, ast.Return) and item.value is not None for item in ast.walk(node))
    if not returns_value:
        return 0.6
    if op_type == "SOURCE":
        query_like = bool(parameters) and (parameters[0] in _QUERY_PARAMETERS or bool(set(parameters) & _QUERY_PARAMETERS))
        return 0.9 if query_like or bool(keyword_only & _QUERY_PARAMETERS) else 0.6
    return 0.9 if parameters or node.args.vararg else 0.6


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
        by_line.setdefault(node.lineno, (node, []))[1].append(
            f'@observe("{operator.op_type}", op_id="{operator.op_id}", parent_ids={operator.parent_ids!r})\n'
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
    instrumented = "".join(lines)
    try:
        ast.parse(instrumented)
    except SyntaxError as error:  # pragma: no cover - guards against a malformed patch
        raise ValueError(f"instrumented source does not parse: {error}") from error
    return instrumented


def _select_entrypoint(
    routes: list[tuple[str, str, FunctionNode, str]],
    functions: dict[tuple[str, str], FunctionNode],
    operators: list[tuple[str, OperatorMapping]],
    detection: DetectionResult,
) -> tuple[str, str, FunctionNode, str] | None:
    """``(relative_path, symbol, node, kind)`` of the function the verification scenarios call."""
    retrieval_routes = [route for route in routes if _RETRIEVAL_ROUTE.search(route[3] or route[1])]
    if retrieval_routes or routes:
        relative, symbol, node, _path = (retrieval_routes or routes)[0]
        return relative, symbol, node, "http_route"
    for candidate in detection.entrypoints:
        node = functions.get((candidate.file, candidate.symbol))
        if node is not None and candidate.kind in ("function", "async_function"):
            return candidate.file, candidate.symbol, node, "function"
    parents = {parent for _relative, operator in operators for parent in operator.parent_ids}
    for relative, operator in operators:
        if operator.op_id not in parents:
            return relative, operator.symbol, functions[(relative, operator.symbol)], "operator"
    return None


def build_integration_plan(
    project_root: Path, framework: str | None = None, *, db_path: str = ".retobs/results.db"
) -> IntegrationPlan:
    root = project_root.resolve()
    service_id, pipeline_id = _fixture_identity(root)
    detection = detect_project(root, framework)
    operators: list[OperatorMapping] = []
    located: list[tuple[str, OperatorMapping]] = []
    low_confidence: list[dict[str, object]] = []
    discovered_by_file: dict[str, list[tuple[FunctionNode, OperatorMapping]]] = {}
    functions: dict[tuple[str, str], FunctionNode] = {}
    routes: list[tuple[str, str, FunctionNode, str]] = []
    unresolved: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative_path = path.relative_to(root)
        if _is_skipped(relative_path):
            continue
        relative = str(relative_path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        candidates = _candidate_functions(tree)
        for symbol, _call_name, node in candidates:
            functions[(relative, symbol)] = node
            decorator = _route_decorator(node)
            if decorator is not None:
                routes.append((relative, symbol, node, _route_path(decorator)))
        nodes: list[tuple[str, str, FunctionNode]] = []
        for symbol, call_name, node in candidates:
            op_type = _op_type(node.name)
            if op_type is None or _route_decorator(node) is not None:
                continue
            confidence = _confidence(node, op_type)
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
        discovered: list[tuple[FunctionNode, OperatorMapping]] = []
        for symbol, _call_name, node in nodes:
            operator = OperatorMapping(
                ids[symbol], _op_type(node.name) or "TRANSFORM", symbol, relative,
                tuple(ids[name] for name in ids if name in parent_names[symbol]), .9,
            )
            operators.append(operator)
            located.append((relative, operator))
            discovered.append((node, operator))
        if discovered:
            discovered_by_file[relative] = discovered
    entrypoint = _select_entrypoint(routes, functions, located, detection)
    patches: list[PatchOperation] = []
    for relative in sorted({*discovered_by_file, *([entrypoint[0]] if entrypoint else [])}):
        path = root / relative
        source = path.read_text(encoding="utf-8")
        scope = None
        if entrypoint is not None and entrypoint[0] == relative:
            scope = (entrypoint[2], f'@trace_scope("{service_id}", "{pipeline_id}", db_path="{db_path}")')
        replacement = _instrument_source(source, discovered_by_file.get(relative, []), scope)
        if replacement != source:
            patches.append(PatchOperation.from_file(root, path, replacement))
    if not operators:
        unresolved.append("no retrieval operators discovered")
    mapping = {"doc_id": "item.id", "score": "item.score", "rank": "enumerate"}
    datasets = sorted(
        str(path.relative_to(root))
        for pattern in ("*.jsonl", "*.json", "*.csv", "*.parquet")
        for path in root.rglob(pattern)
        if not any(part.startswith(".") or part in {"venv", "node_modules", "retobs"} for part in path.relative_to(root).parts)
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
    }
    scenarios = (VerificationScenario("representative", "retobs verification query", tuple(op.op_id for op in operators), tuple((p, op.op_id) for op in operators for p in op.parent_ids)),)
    return IntegrationPlan.create(project_root=root, framework=detection.framework, service_id=service_id, pipeline_id=pipeline_id, patches=patches, operators=operators, candidate_mapping=mapping, scenarios=scenarios, unresolved=unresolved, discovery=discovery)
