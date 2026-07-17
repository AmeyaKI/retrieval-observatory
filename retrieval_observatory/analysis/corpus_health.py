from typing import Any, Mapping
from retrieval_observatory.analysis.contracts import AnalysisScope, result, unavailable


def analyze_corpus_health(snapshot: Mapping[str, Any] | None, previous: Mapping[str, Any] | None, scope: AnalysisScope):
    if not snapshot:
        return unavailable(scope, "corpus_health", "No corpus/index health snapshot was captured.")
    required = {"document_count", "index_document_count", "duplicate_count", "empty_count"}
    missing = required - set(snapshot)
    data = {
        "document_count": snapshot.get("document_count"),
        "index_coverage": snapshot.get("index_document_count", 0) / max(1, snapshot.get("document_count", 0)),
        "duplicate_rate": snapshot.get("duplicate_count", 0) / max(1, snapshot.get("document_count", 0)),
        "empty_rate": snapshot.get("empty_count", 0) / max(1, snapshot.get("document_count", 0)),
        "drift": None if not previous else snapshot.get("document_count", 0) - previous.get("document_count", 0),
    }
    return result(
        scope,
        "corpus_health",
        data,
        len(required) - len(missing),
        len(required),
        limitations=(f"Missing snapshot fields: {sorted(missing)}",) if missing else (),
    )
