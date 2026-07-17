import pytest

from retrieval_observatory.diagnostics import DiagnosticEngine, context_for_trace
from retrieval_observatory.store.sqlite import SQLiteStore
from tests.unit.test_diagnostic_engine import _trace


@pytest.mark.asyncio
async def test_diagnostic_roundtrip_preserves_typed_findings(tmp_path) -> None:
    store = SQLiteStore(db_path=str(tmp_path / "diagnostics.db"))
    await store.init_db()
    findings = DiagnosticEngine.default().evaluate(
        context_for_trace(_trace(), relevant_document_ids={"gold"}, corpus_document_ids={"gold", "other"})
    )
    await store.save_diagnostics("run", "query", findings)
    assert await store.query_diagnostics("run", "query") == list(findings)
