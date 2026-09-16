"""Graded nDCG uses linear gain (pytrec_eval / BEIR), clamps negative grades, and builds the
ideal from the query's own positive grades truncated at k."""
from __future__ import annotations

import math
import random

import pytest

from retrieval_observatory.metrics.ranking import ndcg_at_k, ndcg_at_k_graded


def _reference_ndcg(retrieved, qrels, k):
    """Independent linear-gain implementation mirroring trec_eval's ndcg_cut."""
    dcg = sum(max(qrels.get(d, 0), 0) / math.log2(r + 1) for r, d in enumerate(retrieved[:k], start=1))
    ideal = sorted((g for g in qrels.values() if g > 0), reverse=True)[:k]
    idcg = sum(g / math.log2(r + 1) for r, g in enumerate(ideal, start=1))
    return dcg / idcg if idcg else 0.0


def test_graded_ndcg_matches_hand_computation_with_linear_gain():
    qrels = {"a": 3, "b": 1, "c": 2}
    retrieved = ["b", "a", "x", "c"]
    dcg = 1 / math.log2(2) + 3 / math.log2(3) + 2 / math.log2(5)
    idcg = 3 / math.log2(2) + 2 / math.log2(3) + 1 / math.log2(4)
    assert ndcg_at_k_graded(retrieved, qrels, 10) == pytest.approx(dcg / idcg)
    # Exponential gain would give a different number: this guards the gain choice itself.
    exp_dcg = 1 / math.log2(2) + 7 / math.log2(3) + 3 / math.log2(5)
    exp_idcg = 7 / math.log2(2) + 3 / math.log2(3) + 1 / math.log2(4)
    assert ndcg_at_k_graded(retrieved, qrels, 10) != pytest.approx(exp_dcg / exp_idcg)


def test_graded_ndcg_ideal_is_truncated_at_k():
    qrels = {f"d{i}": 1 for i in range(10)}
    assert ndcg_at_k_graded(["d0", "d1"], qrels, 2) == pytest.approx(1.0)


def test_negative_grades_are_clamped_to_zero():
    qrels = {"a": 2, "b": -1}
    assert ndcg_at_k_graded(["b"], qrels, 10) == 0.0
    assert ndcg_at_k_graded(["b", "a"], qrels, 10) == pytest.approx((2 / math.log2(3)) / 2)


def test_binary_grades_reduce_to_binary_ndcg():
    rng = random.Random(1)
    for _ in range(100):
        docs = [f"d{i}" for i in range(rng.randint(1, 20))]
        relevant = set(rng.sample(docs, k=rng.randint(1, len(docs))))
        retrieved = rng.sample(docs, k=rng.randint(1, len(docs)))
        assert ndcg_at_k_graded(retrieved, {d: 1 for d in relevant}, 10) == pytest.approx(ndcg_at_k(retrieved, relevant, 10))


def test_graded_ndcg_matches_reference_on_random_graded_inputs():
    """Always checked against the in-test reference; also against pytrec_eval when installed."""
    try:
        import pytrec_eval
    except ImportError:  # pragma: no cover - reference library is optional
        pytrec_eval = None
    rng = random.Random(0)
    for _ in range(300):
        docs = [f"d{i}" for i in range(rng.randint(1, 40))]
        pool = docs + [f"missing{i}" for i in range(5)]
        graded = {d: rng.choice([1, 2, 3]) for d in rng.sample(pool, k=rng.randint(1, min(8, len(pool))))}
        zeros = [d for d in docs if d not in graded][:3]
        qrels = {**graded, **{d: 0 for d in zeros}}
        retrieved = rng.sample(docs, k=rng.randint(1, len(docs)))
        ours = ndcg_at_k_graded(retrieved, qrels, 10)
        assert ours == pytest.approx(_reference_ndcg(retrieved, qrels, 10), abs=1e-12)
        if pytrec_eval is not None:
            run = {d: float(len(retrieved) - i) for i, d in enumerate(retrieved)}
            ref = pytrec_eval.RelevanceEvaluator({"q": qrels}, {"ndcg_cut.10"}).evaluate({"q": run})["q"]["ndcg_cut_10"]
            assert ours == pytest.approx(ref, abs=1e-9)
