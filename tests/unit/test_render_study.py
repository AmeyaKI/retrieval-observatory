"""scripts/render_study.py applies the PREREGISTRATION.md §2 decision rule and renders only from cell JSON."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from retrieval_observatory.analysis.loss_attribution import Rate

ROOT = Path(__file__).parents[2]


def _load():
    path = ROOT / "scripts" / "render_study.py"
    spec = importlib.util.spec_from_file_location("render_study", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


render = _load()
SHARES = {"fusion": Rate(0.7, 0.6, 0.8, 70, 100), "rerank": Rate(0.3, 0.2, 0.4, 30, 100)}


@pytest.mark.parametrize(
    ("rate", "completeness", "branch"),
    [
        (Rate(0.15, 0.12, 0.18, 15, 100), 1.0, "positive"),
        (Rate(0.03, 0.02, 0.04, 3, 100), 1.0, "null"),
        (Rate(0.10, 0.08, 0.12, 10, 100), 1.0, "indeterminate"),   # straddles the threshold
        (Rate(0.15, 0.12, 0.18, 15, 100), 0.90, "indeterminate"),  # completeness below 95%
        (Rate(0.30, 0.15, 0.40, 30, 100), 1.0, "indeterminate"),   # interval wider than 20 pp
        (Rate(None, None, None, 0, 0), 1.0, "indeterminate"),
    ],
)
def test_headline_branch_follows_the_preregistered_rule(rate, completeness, branch):
    assert render.headline(rate, SHARES, 100, 3, completeness).branch == branch


def test_positive_headline_names_the_top_class_and_flags_an_overlapping_runner_up():
    separable = render.headline(Rate(0.15, 0.12, 0.18, 15, 100), SHARES, 1234, 3, 1.0)
    assert "most often by fusion." in separable.sentence and "1,234 queries on 3 datasets" in separable.sentence
    close = {"fusion": Rate(0.55, 0.45, 0.65, 55, 100), "rerank": Rate(0.45, 0.35, 0.55, 45, 100)}
    assert "not separable from rerank" in render.headline(Rate(0.15, 0.12, 0.18, 15, 100), close, 10, 3, 1.0).sentence


def test_ratio_of_means_is_paired_on_shared_queries():
    value, low, high, n = render.ratio_of_means({"a": 2.0, "b": 4.0, "x": 9.0}, {"a": 1.0, "b": 2.0})
    assert n == 2 and value == pytest.approx(2.0) and low == pytest.approx(2.0) and high == pytest.approx(2.0)


def test_committed_cells_render_and_every_missing_cell_is_named():
    cells = render.load_cells()
    expected = render.expected_cells()
    text = render.render(cells, expected)
    missing = [key for key in expected if key not in cells]
    for dataset, pipeline in missing:
        assert f"`{dataset}__{pipeline}`" in text
    assert ("Draft —" in text) == bool(missing)
