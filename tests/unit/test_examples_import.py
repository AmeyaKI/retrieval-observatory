"""Every shipped example app must import: a name that no longer exists in retrieval_observatory
fails here instead of in a user's terminal. Missing third-party packages are stubbed."""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = sorted((ROOT / "examples" / "integrations").glob("*/app.py"))
OPTIONAL_TOP_LEVELS = {
    "agents", "dspy", "faiss", "fastapi", "haystack", "langchain", "langchain_community", "langchain_core",
    "llama_index", "rank_bm25", "uvicorn",
}


class _Stub:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return _Stub()

    def __getattr__(self, name):
        return _Stub()

    def __or__(self, other):
        return _Stub()


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Stub


class _StubFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serve an attribute-permissive module for optional packages that are not installed."""

    def find_spec(self, name, path=None, target=None):
        top = name.split(".")[0]
        if top not in OPTIONAL_TOP_LEVELS or top in sys.modules and not isinstance(sys.modules[top], _StubModule):
            return None
        if top == name and importlib.machinery.PathFinder.find_spec(top) is not None:
            return None
        return importlib.util.spec_from_loader(name, self, is_package=True)

    def create_module(self, spec):
        module = _StubModule(spec.name)
        module.__path__ = []
        return module

    def exec_module(self, module):
        pass


@pytest.fixture
def stubbed_optional_packages(monkeypatch):
    finder = _StubFinder()
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if isinstance(sys.modules.get(name), _StubModule) or name.startswith("retobs_example_"):
            sys.modules.pop(name, None)


@pytest.mark.parametrize("path", EXAMPLES, ids=[path.parent.name for path in EXAMPLES])
def test_example_app_imports(path: Path, stubbed_optional_packages, monkeypatch) -> None:
    monkeypatch.setenv("RETOBS_MEMORY_SINK", "1")
    spec = importlib.util.spec_from_file_location(f"retobs_example_{path.parent.name}", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as error:
        if (error.name or "").split(".")[0] == "retrieval_observatory" or "retrieval_observatory" in str(error):
            raise
        pytest.skip(f"optional dependency unavailable for {path.parent.name}: {error}")
