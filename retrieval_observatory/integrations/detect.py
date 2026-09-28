from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".retobs",
    "retobs",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    "tests",
    "test",
}
#: Installed-package directories; a vendored or checked-in environment is never project code.
_PACKAGE_DIRS = {"site-packages", "dist-packages"}
#: Directories of code that drives, measures or demonstrates the pipeline rather than serving it;
#: also any directory named ``bench*``/``eval*``. Scanned for datasets, never for operators or the entrypoint.
_NON_RUNTIME_DIRS = {
    "harness", "reports", "scripts", "notebooks", "fixtures", "examples", "experiments",
}

_FRAMEWORK_SIGNALS: Dict[str, List[re.Pattern[str]]] = {
    "langchain": [
        re.compile(r"\bfrom\s+langchain", re.I),
        re.compile(r"\bimport\s+langchain", re.I),
        re.compile(r"\bfrom\s+langchain_core", re.I),
        re.compile(r"\bLangChain\b"),
    ],
    "llamaindex": [
        re.compile(r"\bfrom\s+llama_index", re.I),
        re.compile(r"\bimport\s+llama_index", re.I),
        re.compile(r"\bllamaindex\b", re.I),
    ],
    "fastapi": [
        re.compile(r"\bFastAPI\s*\("),
        re.compile(r"\bapp\s*=\s*FastAPI\s*\("),
    ],
}

_ENTRYPOINT_PATTERNS = [
    (re.compile(r"^\s*def\s+(retrieve|search)\s*\(", re.M), "function"),
    (re.compile(r"^\s*async\s+def\s+(retrieve|search)\s*\(", re.M), "async_function"),
    (re.compile(r"^\s*class\s+(\w*Retriever\w*)\s*[:\(]", re.M), "class"),
    (re.compile(r"\.retrieve\s*\(", re.M), "method_call"),
    (re.compile(r"@app\.(get|post)\s*\(\s*[\"']/(?:search|retrieve)", re.M), "http_route"),
]


@dataclass
class EntrypointCandidate:
    file: str
    symbol: str
    line_hint: int
    kind: str
    score: float = 0.0


@dataclass
class DetectionResult:
    framework: str
    framework_scores: Dict[str, int] = field(default_factory=dict)
    entrypoints: List[EntrypointCandidate] = field(default_factory=list)
    http_routes: List[Dict[str, str]] = field(default_factory=list)


def is_excluded_dir(path: Path, named: frozenset[str] | set[str] = _SKIP_DIRS) -> bool:
    """A dot-directory, a named skip dir, an installed-package dir, or a virtualenv of any name."""
    name = path.name
    return name.startswith(".") or name in named or name in _PACKAGE_DIRS or (path / "pyvenv.cfg").is_file()


def is_non_runtime_path(relative: str | Path) -> bool:
    """Whether a project-relative file sits under a benchmark, eval, report, script, notebook, fixture or example dir."""
    return any(
        part.lower() in _NON_RUNTIME_DIRS or part.lower().startswith(("bench", "eval"))
        for part in Path(relative).parent.parts
    )


def iter_project_files(root: Path, suffixes: tuple[str, ...], named: frozenset[str] | set[str] = _SKIP_DIRS) -> List[Path]:
    """Files under ``root`` with one of ``suffixes``, sorted, never descending into an excluded dir.

    Only directories inside the project count: a project checked out under ``~/tests/`` or
    ``~/build/`` must not scan as empty.
    """
    files: List[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        base = Path(directory)
        dirnames[:] = [name for name in dirnames if not is_excluded_dir(base / name, named)]
        files.extend(base / name for name in filenames if name.endswith(suffixes))
    return sorted(files)


def _iter_python_files(root: Path) -> List[Path]:
    return iter_project_files(root, (".py",))


def _score_frameworks(text: str) -> Dict[str, int]:
    scores: Dict[str, int] = {"python": 1}
    for framework, patterns in _FRAMEWORK_SIGNALS.items():
        hits = sum(1 for pat in patterns if pat.search(text))
        if hits:
            scores[framework] = hits
    if re.search(r"@app\.(get|post)\s*\(\s*[\"']/(?:search|retrieve)", text):
        scores["fastapi"] = scores.get("fastapi", 0) + 2
        scores["http"] = scores.get("http", 0) + 1
    return scores


def _find_entrypoints(rel_path: str, text: str) -> List[EntrypointCandidate]:
    found: List[EntrypointCandidate] = []
    for pattern, kind in _ENTRYPOINT_PATTERNS:
        for match in pattern.finditer(text):
            symbol = match.group(1) if match.lastindex else kind
            line_hint = text[: match.start()].count("\n") + 1
            score = 2.0 if symbol in {"retrieve", "search"} else 1.0
            if "Retriever" in str(symbol):
                score = 1.5
            found.append(
                EntrypointCandidate(
                    file=rel_path,
                    symbol=str(symbol),
                    line_hint=line_hint,
                    kind=kind,
                    score=score,
                )
            )
    return found


def _find_http_routes(rel_path: str, text: str) -> List[Dict[str, str]]:
    routes: List[Dict[str, str]] = []
    for match in re.finditer(
        r"@app\.(get|post)\s*\(\s*[\"']([^\"']+)[\"']",
        text,
    ):
        path = match.group(2)
        if "search" in path or "retrieve" in path:
            routes.append({"file": rel_path, "method": match.group(1).upper(), "path": path})
    return routes


def detect_project(project_root: str | Path, framework: Optional[str] = None) -> DetectionResult:
    """Scan a project for framework signals and retrieval entrypoints."""
    root = Path(project_root).resolve()
    aggregate_scores: Dict[str, int] = {"python": 0}
    entrypoints: List[EntrypointCandidate] = []
    http_routes: List[Dict[str, str]] = []

    for py_file in _iter_python_files(root):
        try:
            text = py_file.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(py_file.relative_to(root))
        for fw, score in _score_frameworks(text).items():
            aggregate_scores[fw] = aggregate_scores.get(fw, 0) + score
        entrypoints.extend(_find_entrypoints(rel, text))
        http_routes.extend(_find_http_routes(rel, text))

    if framework:
        chosen = framework.lower().strip()
    else:
        # ``python`` scores one point per file, so a project with a few plain modules used to
        # outvote the framework it actually imports. Any framework signal beats the baseline.
        signals = {name: score for name, score in aggregate_scores.items() if name != "python" and score >= 1}
        chosen = max(signals, key=lambda k: signals[k]) if signals else "python"
        if chosen == "http" and aggregate_scores.get("fastapi", 0) >= aggregate_scores.get("http", 0):
            chosen = "fastapi"

    # Non-runtime candidates sort last so a bench or eval ``search`` never pushes the real one past the cut.
    entrypoints.sort(key=lambda e: (is_non_runtime_path(e.file), -e.score))
    return DetectionResult(
        framework=chosen,
        framework_scores=aggregate_scores,
        entrypoints=entrypoints[:10],
        http_routes=http_routes[:5],
    )
