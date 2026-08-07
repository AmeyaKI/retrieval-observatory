from __future__ import annotations

import ast
import json
from pathlib import Path
import re

from retrieval_observatory.integrations.detect import detect_project
from retrieval_observatory.integrations.model import IntegrationPlan, OperatorMapping, PatchOperation, VerificationScenario

_TYPE_RULES = ((r"gate|intent|route", "GATE"), (r"fuse|fusion|rrf", "FUSE"), (r"filter", "FILTER"), (r"rerank|cross_encoder", "RERANK"), (r"source|retrieve|search|bm25|dense", "SOURCE"))


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


def _instrument_source(source: str, nodes: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, OperatorMapping]]) -> str:
    lines = source.splitlines(keepends=True)
    needs_import = not any("retrieval_observatory.sdk import observe" in line for line in lines)
    insert_at = _import_insertion_line(source, ast.parse(source)) if needs_import else -1
    # Decorators go in first, bottom-up, so every `node.lineno` still refers to the line it was
    # parsed from. The import is added afterwards at a position above all of them.
    for node, operator in sorted(nodes, key=lambda item: item[0].lineno, reverse=True):
        original_index = node.lineno - 1
        decorator = (
            f'@observe("{operator.op_type}", op_id="{operator.op_id}", '
            f'parent_ids={operator.parent_ids!r})\n'
        )
        nearby = "".join(lines[max(0, original_index - len(node.decorator_list) - 2) : original_index])
        if f'op_id="{operator.op_id}"' not in nearby:
            lines.insert(original_index, decorator)
    if needs_import:
        lines.insert(insert_at, "from retrieval_observatory.sdk import observe\n")
    instrumented = "".join(lines)
    try:
        ast.parse(instrumented)
    except SyntaxError as error:  # pragma: no cover - guards against a malformed patch
        raise ValueError(f"instrumented source does not parse: {error}") from error
    return instrumented


def build_integration_plan(project_root: Path, framework: str | None = None) -> IntegrationPlan:
    root = project_root.resolve()
    service_id, pipeline_id = _fixture_identity(root)
    detection = detect_project(root, framework)
    operators: list[OperatorMapping] = []
    patches: list[PatchOperation] = []
    unresolved: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if any(part.startswith(".") or part in {"venv", "node_modules", "retobs"} for part in path.relative_to(root).parts):
            continue
        relative = str(path.relative_to(root))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        nodes = [
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _op_type(node.name)
        ]
        ids = {node.name: stable_op_id(relative, node.name) for node in nodes}
        parent_names: dict[str, set[str]] = {name: set() for name in ids}
        assigned_operators = {
            target.id: assignment.value.func.id
            for assignment in ast.walk(tree)
            if isinstance(assignment, ast.Assign)
            and isinstance(assignment.value, ast.Call)
            and isinstance(assignment.value.func, ast.Name)
            and assignment.value.func.id in ids
            for target in assignment.targets
            if isinstance(target, ast.Name)
        }

        def outer_known(value: ast.AST) -> list[ast.Call]:
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in ids:
                return [value]
            return [call for child in ast.iter_child_nodes(value) for call in outer_known(child)]

        def record_call(call: ast.Call) -> str | None:
            children = [candidate for child in [*call.args, *(keyword.value for keyword in call.keywords)] for candidate in outer_known(child)]
            nested = [candidate.func.id for candidate in children if isinstance(candidate.func, ast.Name)]
            named_parents = [
                assigned_operators[value.id]
                for value in [*call.args, *(keyword.value for keyword in call.keywords)]
                if isinstance(value, ast.Name) and value.id in assigned_operators
            ]
            for candidate in children:
                record_call(candidate)
            if isinstance(call.func, ast.Name) and call.func.id in ids:
                parent_names[call.func.id].update([*nested, *named_parents])
                return call.func.id
            return None

        for node in nodes:
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
                if callee and call not in nested_calls and callee != node.name:
                    parent_names[node.name].add(callee)
        discovered: list[tuple[ast.FunctionDef | ast.AsyncFunctionDef, OperatorMapping]] = []
        for node in nodes:
            operator = OperatorMapping(
                ids[node.name], _op_type(node.name) or "TRANSFORM", node.name, relative,
                tuple(ids[name] for name in ids if name in parent_names[node.name]), .9,
            )
            operators.append(operator)
            discovered.append((node, operator))
        if discovered:
            source = path.read_text(encoding="utf-8")
            replacement = _instrument_source(source, discovered)
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
        "http_routes": detection.http_routes,
        "datasets": datasets,
        "operator_symbols": [operator.symbol for operator in operators],
    }
    scenarios = (VerificationScenario("representative", "retobs verification query", tuple(op.op_id for op in operators), tuple((p, op.op_id) for op in operators for p in op.parent_ids)),)
    return IntegrationPlan.create(project_root=root, framework=detection.framework, service_id=service_id, pipeline_id=pipeline_id, patches=patches, operators=operators, candidate_mapping=mapping, scenarios=scenarios, unresolved=unresolved, discovery=discovery)
