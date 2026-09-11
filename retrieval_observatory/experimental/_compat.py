"""Import shim: the pre-0.6.0 package paths resolve to `retrieval_observatory.experimental`.

Installed once by `retrieval_observatory/__init__.py`. Importing an old path returns the
*same* module object as the new path (no double import) and emits a `DeprecationWarning`.
"""
from __future__ import annotations

import importlib
import sys
import warnings
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec

DEMOTED = ("advisor", "classifier", "diagram", "forge")
_OLD_PREFIX = "retrieval_observatory."
_NEW_PREFIX = "retrieval_observatory.experimental."


class _AliasLoader(Loader):
    def __init__(self, target: str) -> None:
        self.target = target

    def create_module(self, spec: ModuleSpec):
        warnings.warn(
            f"'{spec.name}' moved to '{self.target}' in 0.6.0; the old import path is deprecated.",
            DeprecationWarning,
            stacklevel=2,
        )
        return importlib.import_module(self.target)

    def exec_module(self, module) -> None:  # module is already executed
        return None


class _AliasFinder(MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):
        if not fullname.startswith(_OLD_PREFIX):
            return None
        rest = fullname[len(_OLD_PREFIX):]
        if rest.split(".", 1)[0] not in DEMOTED:
            return None
        return ModuleSpec(fullname, _AliasLoader(_NEW_PREFIX + rest))


def install() -> None:
    if not any(isinstance(finder, _AliasFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, _AliasFinder())
