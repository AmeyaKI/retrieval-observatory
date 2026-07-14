from __future__ import annotations

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


def _iter_python_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for path in root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


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
        chosen = max(aggregate_scores, key=lambda k: aggregate_scores.get(k, 0))
        if chosen == "http" and aggregate_scores.get("fastapi", 0) >= aggregate_scores.get("http", 0):
            chosen = "fastapi"

    entrypoints.sort(key=lambda e: e.score, reverse=True)
    return DetectionResult(
        framework=chosen,
        framework_scores=aggregate_scores,
        entrypoints=entrypoints[:10],
        http_routes=http_routes[:5],
    )
