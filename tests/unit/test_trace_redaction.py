from retrieval_observatory.tracing.config import PayloadLimits
from retrieval_observatory.tracing.serialization import normalize_trace

from tests.unit.test_trace_serialization import _trace


def test_redacts_nested_secrets_case_insensitively() -> None:
    trace = _trace(metadata={"Authorization": "Bearer secret", "nested": {"api_key": "x"}})
    normalized = normalize_trace(
        trace,
        limits=PayloadLimits(),
        redacted_keys=frozenset({"authorization", "api_key"}),
    )
    assert normalized.payload["metadata"]["Authorization"] == "[REDACTED]"
    assert normalized.payload["metadata"]["nested"]["api_key"] == "[REDACTED]"
    assert normalized.report.redacted_fields == 2
