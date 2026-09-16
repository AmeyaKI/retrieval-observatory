"""paired_bootstrap_test is a sign-flip permutation test whose p-value is never exactly 0."""
from __future__ import annotations

import itertools
import random

import pytest

from retrieval_observatory.metrics.significance import paired_bootstrap_test


def test_p_value_is_never_exactly_zero():
    p = paired_bootstrap_test([0.0] * 30, [1.0] * 30, n_resamples=1000)
    assert p == pytest.approx(1 / 1001)
    assert p > 0.0


def test_identical_samples_give_p_of_one():
    assert paired_bootstrap_test([0.5, 0.6, 0.55], [0.5, 0.6, 0.55], n_resamples=100) == 1.0


def test_monte_carlo_p_tracks_exact_sign_flip_enumeration():
    rng = random.Random(3)
    a = [rng.random() for _ in range(10)]
    b = [x + rng.gauss(0.05, 0.1) for x in a]
    diffs = [x - y for x, y in zip(a, b)]
    observed = abs(sum(diffs) / len(diffs))
    exact = sum(
        1
        for signs in itertools.product((-1, 1), repeat=10)
        if abs(sum(s * d for s, d in zip(signs, diffs)) / 10) >= observed - 1e-12
    ) / 2**10
    assert paired_bootstrap_test(a, b, n_resamples=20000, seed=0) == pytest.approx(exact, abs=0.02)
