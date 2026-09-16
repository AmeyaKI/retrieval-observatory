"""scripts/bench_analytics.py must use the package's null-centred paired test."""
from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

from retrieval_observatory.metrics.significance import paired_bootstrap_test


def _load():
    path = Path(__file__).parents[2] / "scripts" / "bench_analytics.py"
    spec = importlib.util.spec_from_file_location("bench_analytics", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_analytics"] = module
    spec.loader.exec_module(module)
    return module


def test_paired_pvalue_is_small_for_a_uniform_shift_and_large_for_noise():
    bench = _load()
    a = [0.1] * 200
    b = [0.9] * 200
    assert bench.paired_bootstrap_pvalue(a, b, n_boot=2000) < 0.01
    assert bench.paired_bootstrap_pvalue(a, b, n_boot=2000) == paired_bootstrap_test(a, b, n_resamples=2000, seed=42)

    rng = random.Random(1)
    base = [rng.random() for _ in range(200)]
    noisy = [x + rng.gauss(0, 0.05) for x in base]
    assert bench.paired_bootstrap_pvalue(base, noisy, n_boot=2000) > 0.05
    assert bench.paired_bootstrap_pvalue([1.0], [2.0]) is None


def test_methods_are_labelled():
    bench = _load()
    assert bench.CI_METHOD == "unpaired_percentile"
    assert bench.PVALUE_METHOD == "paired_sign_flip_permutation"
