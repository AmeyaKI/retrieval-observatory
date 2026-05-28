from __future__ import annotations

from typing import List, Tuple

import numpy as np


def benjamini_hochberg(p_values: List[float], fdr: float = 0.05) -> List[float]:
    """Return BH-adjusted p-values (q-values) for a family of hypotheses.

    Applies the Benjamini-Hochberg procedure to control false discovery rate.
    Use q < fdr (default 0.05) instead of p < 0.05 when testing multiple metrics.
    """
    n = len(p_values)
    if n == 0:
        return []
    # Rank p-values (1-based) from smallest to largest
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    q_values = [0.0] * n
    min_q = 1.0
    for rank, (orig_idx, p) in reversed(list(enumerate(indexed, start=1))):
        q = min(p * n / rank, 1.0)
        min_q = min(q, min_q)  # enforce monotonicity
        q_values[orig_idx] = min_q
    return q_values


def bootstrap_ci(
    scores: List[float],
    n_resamples: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> Tuple[float, float]:
    """Return (lower, upper) bootstrap confidence interval."""
    if not scores:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed)
    arr = np.array(scores, dtype=float)
    means = [rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n_resamples)]
    alpha = (1 - ci) / 2
    return (float(np.quantile(means, alpha)), float(np.quantile(means, 1 - alpha)))


def paired_bootstrap_test(
    scores_a: List[float],
    scores_b: List[float],
    n_resamples: int = 1000,
    seed: int = 42,
) -> float:
    """Paired bootstrap significance test. Returns two-tailed p-value.

    H0: mean(A) == mean(B). Small p-value → A and B differ significantly.
    """
    if len(scores_a) != len(scores_b):
        raise ValueError("scores_a and scores_b must have equal length")
    rng = np.random.default_rng(seed)
    a = np.array(scores_a, dtype=float)
    b = np.array(scores_b, dtype=float)
    observed_diff = abs(a.mean() - b.mean())

    diffs = a - b
    count_extreme = 0
    for _ in range(n_resamples):
        signs = rng.choice([-1.0, 1.0], size=len(diffs))
        resampled_diff = abs((diffs * signs).mean())
        if resampled_diff >= observed_diff:
            count_extreme += 1

    return count_extreme / n_resamples
