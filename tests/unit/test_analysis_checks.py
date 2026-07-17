from retrieval_observatory.analysis.checks import RegressionCheck, evaluate_check, evaluate_saved_check
from retrieval_observatory.analysis.contracts import result, unavailable
from tests.fixtures.analysis_fixtures import analysis_scope
import pytest


def test_check_pass_and_failure():
    check = RegressionCheck("c", "latency", "b", "value", "increase", 1)
    assert evaluate_check(check, {"value": 1}, result(analysis_scope(), "x", {"value": 1.5}, 1))["state"] == "passed"
    assert evaluate_check(check, {"value": 1}, result(analysis_scope(), "x", {"value": 3}, 1))["alert"]


def test_check_unavailable_never_alerts():
    assert not evaluate_check(
        RegressionCheck("c", "x", "b", "value", "increase", 1),
        {"value": 1},
        unavailable(analysis_scope(), "x", "missing"),
    )["alert"]


@pytest.mark.asyncio
async def test_saved_check_persists_only_factual_alert(tmp_path):
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(str(tmp_path / "checks.db"))
    await store.init_db()
    await store.save_baseline("b", {"data": {"value": 1}})
    await store.save_regression_check(
        "c", {"analysis_id": "latency", "baseline_id": "b", "metric": "value", "operator": "increase", "threshold": 1}
    )
    outcome = await evaluate_saved_check(store, "c", result(analysis_scope(), "x", {"value": 3}, 1))
    assert outcome["alert"] and len(await store.list_analysis_records("alert")) == 1
