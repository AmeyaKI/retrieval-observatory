from __future__ import annotations

import ast
from dataclasses import replace
import json
from pathlib import Path
import re
from typing import Any

from retrieval_observatory.integrations.detect import DetectionResult, detect_project
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

_TYPE_RULES = (
    (r"gate|intent|route", "GATE"),
    (r"fuse|fusion|rrf", "FUSE"),
    (r"filter", "FILTER"),
    (r"rerank|cross_encoder", "RERANK"),
    (r"source|retriev|search|bm25|dense|relevant_documents", "SOURCE"),
)
_QUERY_PARAMETERS = {"query", "q", "question", "text"}
_LANE_PARAMETERS = {"lanes", "groups", "lists"}
_HTTP_DECORATOR_METHODS = {"get", "post", "put", "patch", "delete", "route", "api_route", "websocket"}
_RETRIEVAL_ROUTE = re.compile(r"search|retriev|query|ask|rag|answer|chat", re.I)
_SKIP_PARTS = {"venv", "node_modules", "retobs", "tests", "test"}
#: Below this a name-only match is not instrumented; ``IntegrationPlan.validate_for_apply``
#: enforces the same threshold on hand-edited plans.
APPLY_CONFIDENCE = 0.8
_OBSERVE_IMPORT = re.compile(r"^from retrieval_observatory\.sdk(?:\.observe)? import .*\bobserve\b")
_SCOPE_IMPORT = re.compile(r"^from retrieval_observatory\.sdk(?:\.observe)? import .*\btrace_scope\b")
_ADAPTER_IMPORT = re.compile(rf"^import {ADAPTER_MODULE}\b")
#: Marks every module apply edits; ``--phase revert`` restores the pre-apply bytes from the manifest.
INSTRUMENTATION_MARKER = "# retobs instrumentation: added by 'retobs integrate --phase apply'; remove with '--phase revert'"
#: Frameworks with a pip extra of their own (FastAPI projects need only the base package).
_FRAMEWORK_EXTRAS = {"langchain", "llamaindex"}
_JUDGMENT_FILES = (("queries", ("quer",)), ("qrels", ("qrel", "judg", "label")), ("corpus", ("corpus", "docs", "document")))
SCENARIO_QUERY_TEXT = "retobs verification query"
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


def _op_type(symbol: str) -> str | None:
    return next((kind for pattern, kind in _TYPE_RULES if re.search(pattern, symbol, re.I)), None)


def _is_test_path(relative: Path) -> bool:
    name = relative.name
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def _is_skipped(relative: Path) -> bool:
    # The project's capture adapter defines CaptureSpecs, not operators, so its helpers are never proposed.
    if relative.name == f"{ADAPTER_MODULE}.py":
        return True
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


def _describe_boundary(node: FunctionNode, operator: OperatorMapping) -> OperatorMapping:
    """Fill the mappings the source determines; a reviewed ``capture`` reference governs both sides."""
    mapped = "capture" if operator.capture else None
    return replace(
        operator,
        input_mapping=mapped or _input_mapping(node, operator.parent_ids),
        output_mapping=mapped or ("return" if _returns_value(node) else "unavailable"),
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
    needs_adapter = any(operator.capture for _node, operator in nodes) and not any(_ADAPTER_IMPORT.match(line) for line in lines)
    insert_at = _import_insertion_line(source, ast.parse(source)) if needs_observe or needs_scope else -1
    # Decorators go in first, bottom-up, so every `node.lineno` still refers to the line it was
    # parsed from. The import is added afterwards at a position above all of them.
    by_line: dict[int, tuple[FunctionNode, list[str]]] = {}
    for node, operator in nodes:
        capture = f", capture={ADAPTER_MODULE}.{operator.capture.split(':', 1)[1]}" if operator.capture else ""
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
    if needs_adapter:
        observe_line = next(index for index, line in enumerate(lines) if _OBSERVE_IMPORT.match(line) or _SCOPE_IMPORT.match(line))
        lines.insert(observe_line + 1, f"import {ADAPTER_MODULE}\n")
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
) -> Entrypoint | None:
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


def _judgments(datasets: list[str]) -> dict[str, Any]:
    found = {
        key: next((path for path in datasets if any(needle in Path(path).name.lower() for needle in needles)), None)
        for key, needles in _JUDGMENT_FILES
    }
    notes = []
    if found["queries"] is None:
        notes.append("no queries file discovered: benchmark setup needs a queries JSON/JSONL file")
    if found["qrels"] is None:
        notes.append("no qrels file discovered: judgment mapping stays unavailable; candidate movement inspection still works")
    if found["corpus"] is None:
        notes.append("no corpus file discovered: pass --corpus to retobs evaluate when the pipeline needs one")
    status = "resolved" if found["queries"] and found["qrels"] else "unresolved"
    return {**found, "status": status, "notes": notes}


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


def _scenario_command(entrypoint: Entrypoint) -> str | None:
    """A ``python -c`` call of a module-level entrypoint; a route or method needs a reviewer-supplied command."""
    relative, symbol, node, kind = entrypoint
    if kind == "http_route" or "." in symbol:
        return None
    parts = Path(relative).with_suffix("").parts
    module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
    call = f"{symbol}({SCENARIO_QUERY_TEXT!r})"
    if isinstance(node, ast.AsyncFunctionDef):
        return f'python -c "import asyncio; from {module} import {symbol}; asyncio.run({call})"'
    return f'python -c "from {module} import {symbol}; {call}"'


def _scenarios(operators: list[OperatorMapping], entrypoint: Entrypoint | None) -> tuple[VerificationScenario, ...]:
    """The same query twice: the repeat is what cross-run entity alignment is checked against."""
    ids = tuple(op.op_id for op in operators)
    edges = tuple((parent, op.op_id) for op in operators for parent in op.parent_ids)
    command = _scenario_command(entrypoint) if entrypoint else None
    return tuple(
        VerificationScenario(scenario_id, SCENARIO_QUERY_TEXT, ids, edges, command=command)
        for scenario_id in ("representative", "representative-repeat")
    )


def _benchmark_setup(entrypoint: Entrypoint | None, judgments: dict[str, Any], db_path: str, pipeline_id: str) -> PlannedAction:
    resolved = judgments.get("status") == "resolved"
    if resolved and entrypoint is not None and entrypoint[3] == "function":
        relative, symbol, _node, _kind = entrypoint
        corpus = f" --corpus {judgments['corpus']}" if judgments.get("corpus") else ""
        command = (
            f"retobs evaluate {relative}:{symbol} --queries {judgments['queries']} --qrels {judgments['qrels']}{corpus}"
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
    a missing one is ``unresolved``), its scenarios, identity, judgments, candidate mapping and
    entrypoint are kept when set, and everything derived from them (patches, boundary, actions,
    expected capabilities, open questions, plan_id) is regenerated.
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
        if reviewed is None:
            discovered, low = _discover_file_operators(relative, tree, candidates)
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
    operators = [
        _describe_boundary(located[key], operator) if (key := (operator.relative_path, operator.symbol)) in located else operator
        for operator in operators
    ]
    discovered_by_file: dict[str, list[tuple[FunctionNode, OperatorMapping]]] = {}
    for operator in operators:
        node = located.get((operator.relative_path, operator.symbol))
        if node is not None:
            discovered_by_file.setdefault(operator.relative_path, []).append((node, operator))
    reviewed_entry = reviewed.discovery.get("entrypoint") if reviewed is not None else None
    if reviewed_entry:
        node = _locate(root, reviewed_entry["file"], reviewed_entry["symbol"], functions)
        if node is None:
            unresolved.append(f"entrypoint {reviewed_entry['symbol']} not found in {reviewed_entry['file']}")
        entrypoint = (reviewed_entry["file"], reviewed_entry["symbol"], node, reviewed_entry["kind"]) if node is not None else None
    else:
        sourced = [(op.relative_path, op) for op in operators if (op.relative_path, op.symbol) in located]
        entrypoint = _select_entrypoint(routes, functions, sourced, detection)
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
            if any(op.capture for _node, op in file_operators):
                added.append(f"import {ADAPTER_MODULE}")
            edits.append(PlannedAction("source_edit", f"edit {relative}: add " + " and ".join(added), performed_by="apply"))
    if not operators:
        unresolved.append("no retrieval operators discovered")
    mapping = dict(reviewed.candidate_mapping) if reviewed is not None and reviewed.candidate_mapping else {
        "doc_id": "item.id", "score": "item.score", "rank": "enumerate",
    }
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
        "runbook": str(RUNBOOK_PATH) if RUNBOOK_PATH.is_file() else None,
    }
    judgments = dict(reviewed.judgments) if reviewed is not None and reviewed.judgments else _judgments(datasets)
    identity = reviewed.identity if reviewed is not None else _identity(entrypoint, mapping)
    scenarios = reviewed.scenarios if reviewed is not None and reviewed.scenarios else _scenarios(operators, entrypoint)
    boundary = _boundary(entrypoint, operators)
    open_questions = [question for operator in operators if not operator.capture for question in _mapping_questions(operator)]
    if entrypoint is None:
        open_questions.append("no entrypoint found: set discovery.entrypoint {file, symbol, kind} in the plan and each scenario's command")
    else:
        route = next((item[3] for item in routes if item[:2] == entrypoint[:2]), None)
        target = (
            f"the request that exercises route {route or entrypoint[1]} ({entrypoint[1]} in {entrypoint[0]})"
            if entrypoint[3] == "http_route"
            else f"the call that exercises {entrypoint[1]} in {entrypoint[0]}"
        )
        open_questions.extend(
            f"scenario {scenario.scenario_id}: set command to {target}"
            for scenario in scenarios
            if scenario.command is None
        )
    if not any(scenario.route for scenario in scenarios):
        open_questions.extend(f"gate {op.op_id}: declare one scenario per route with `route` set" for op in operators if op.op_type == "GATE")
    package = f'"retrieval-observatory[{detection.framework}]"' if detection.framework in _FRAMEWORK_EXTRAS else "retrieval-observatory"
    actions = (
        PlannedAction("install", "install retobs into the project's environment", f"pip install {package}"),
        *edits,
        _benchmark_setup(entrypoint, judgments, db_path, pipeline_id),
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
    )
