from __future__ import annotations

import importlib
import sys
import warnings

import pytest

from retrieval_observatory.experimental._compat import DEMOTED


@pytest.mark.parametrize("name", sorted(DEMOTED))
def test_old_path_warns_and_returns_the_experimental_module(name: str) -> None:
    old = f"retrieval_observatory.{name}"
    new = f"retrieval_observatory.experimental.{name}"
    sys.modules.pop(old, None)
    with pytest.warns(DeprecationWarning, match="moved to"):
        module = importlib.import_module(old)
    assert module is importlib.import_module(new)


def test_old_submodule_path_is_the_same_object() -> None:
    sys.modules.pop("retrieval_observatory.forge", None)
    sys.modules.pop("retrieval_observatory.forge.types", None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        old = importlib.import_module("retrieval_observatory.forge.types")
    new = importlib.import_module("retrieval_observatory.experimental.forge.types")
    assert old is new
    assert old.TestSetSummary is new.TestSetSummary


def test_new_path_does_not_warn() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        importlib.import_module("retrieval_observatory.experimental.advisor")
