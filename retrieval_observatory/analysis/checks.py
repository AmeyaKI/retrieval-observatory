from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from retrieval_observatory.analysis.contracts import AnalysisResult


@dataclass(frozen=True)
class SavedBaseline:
    baseline_id: str
    analysis_id: str
    scope: Mapping[str, Any]
    data: Mapping[str, Any]
    created_at: str


@dataclass(frozen=True)
class RegressionCheck:
    check_id: str
    analysis_id: str
    baseline_id: str
    metric: str
    operator: str
    threshold: float


def evaluate_check(check: RegressionCheck, baseline: Mapping[str, Any], current: AnalysisResult[Any]) -> dict[str, Any]:
    if current.state != "ready":
        return {
            "check_id": check.check_id,
            "state": "unavailable",
            "alert": False,
            "reason": f"analysis state is {current.state}",
        }
    before = float(baseline[check.metric])
    after = float(current.data[check.metric])
    delta = after - before
    failed = {"increase": delta > check.threshold, "decrease": delta < -check.threshold}.get(
        check.operator, abs(delta) > check.threshold
    )
    return {
        "check_id": check.check_id,
        "state": "failed" if failed else "passed",
        "alert": failed,
        "baseline": before,
        "current": after,
        "delta": delta,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


async def evaluate_saved_check(store: Any, check_id: str, current: AnalysisResult[Any]) -> dict[str, Any]:
    record = await store.get_analysis_record("check", check_id)
    if record is None:
        raise ValueError(f"Unknown regression check '{check_id}'")
    baseline = await store.get_analysis_record("baseline", str(record["baseline_id"]))
    if baseline is None:
        raise ValueError(f"Unknown baseline '{record['baseline_id']}'")
    check = RegressionCheck(
        check_id,
        str(record["analysis_id"]),
        str(record["baseline_id"]),
        str(record["metric"]),
        str(record["operator"]),
        float(record["threshold"]),
    )
    outcome = evaluate_check(check, baseline["data"], current)
    if outcome["alert"]:
        await store.append_alert(f"{check_id}:{outcome['evaluated_at']}", outcome)
    return outcome
