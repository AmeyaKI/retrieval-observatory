"""Model loading for the reranker; a factory, not an operator."""
from __future__ import annotations


class _OverlapModel:
    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [float(len(set(query.split()) & set(text.lower().split()))) for query, text in pairs]


def get_cross_encoder() -> _OverlapModel:
    return _OverlapModel()
