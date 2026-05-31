import pytest

from retrieval_observatory.classifier.data import (
    LabeledQuery,
    check_minimum_samples,
    class_distribution,
    normalize_query_text,
)
from retrieval_observatory.classifier.model import load_model, train_model


def _samples(n_easy=10, n_medium=10, n_hard=10):
    rows = []
    for cls, n in [("easy", n_easy), ("medium", n_medium), ("hard", n_hard)]:
        for i in range(n):
            text = f"{cls} query number {i} with unique tokens {cls}{i}"
            rows.append(
                LabeledQuery(
                    query_text=text,
                    query_id=f"{cls}_{i}",
                    run_id="r1",
                    bucket=cls if cls != "hard" else "discriminative",
                    training_class=cls,
                )
            )
    return rows


def test_normalize_query_text():
    assert normalize_query_text("  Hello   World ") == "hello world"


def test_class_distribution():
    dist = class_distribution(_samples(5, 3, 2))
    assert dist == {"easy": 5, "medium": 3, "hard": 2}


def test_check_minimum_samples():
    assert check_minimum_samples(_samples(10, 10, 10), min_total=30, min_per_class=5) is None
    assert "Need at least" in check_minimum_samples(_samples(2, 2, 2), min_total=30, min_per_class=5)


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("sklearn") is None,
    reason="scikit-learn not installed",
)
def test_train_predict_roundtrip(tmp_path):
    samples = _samples(12, 12, 12)
    out = tmp_path / "model.joblib"
    report = train_model(samples, "beir/nfcorpus", str(out), min_samples=30, min_per_class=5)
    assert report.n_samples == 36
    assert report.cv_accuracy >= 0
    assert out.exists()

    model = load_model(str(out))
    pred = model.predict("hard query number 99 with unique tokens hard99")
    assert pred["label"] in {"easy", "medium", "hard"}
    assert sum(pred["proba"].values()) == pytest.approx(1.0, abs=0.01)
