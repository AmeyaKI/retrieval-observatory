from __future__ import annotations

import warnings

import retrieval_observatory as ro


def test_generate_testset_validate_warns_without_judge(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    corpus = {
        "doc2020": {"text": "annual revenue report 2020 quarterly growth earnings summary"},
        "doc2021": {"text": "annual revenue report 2021 quarterly growth earnings summary"},
        "doc2022": {"text": "annual revenue report 2022 quarterly growth earnings summary"},
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ds = ro.generate_testset(corpus, n_per_type=1, validate=True)
    assert hasattr(ds, "load")
    assert any("no LLM judge" in str(w.message) for w in caught)
