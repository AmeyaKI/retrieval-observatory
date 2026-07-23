from __future__ import annotations

import json
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, JsonValue

from retrieval_observatory.release.policy import ReleasePolicy, SliceGuard
from retrieval_observatory.release.statistics import (
    GuardResult,
    GuardStatus,
    adjusted_confidence_level,
    evaluate_metric_guards,
)


class SliceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str
    field: str
    value: JsonValue
    status: GuardStatus
    paired_n: int
    label_coverage: float | None
    adjusted_confidence_level: float
    sample_limitation: str | None
    guards: list[GuardResult]


def evaluate_declared_slices(
    policy: ReleasePolicy,
    baseline_rows: Sequence[dict[str, Any]],
    candidate_rows: Sequence[dict[str, Any]],
) -> list[SliceResult]:
    confidence = adjusted_confidence_level(policy)
    results = []
    for declaration in policy.slices:
        baseline_slice = _filter_rows(baseline_rows, declaration)
        candidate_slice = _filter_rows(candidate_rows, declaration)
        baseline_ids = {row["query_id"] for row in baseline_slice}
        candidate_ids = {row["query_id"] for row in candidate_slice}
        paired_ids = baseline_ids & candidate_ids
        all_ids = baseline_ids | candidate_ids
        coverage = len(paired_ids) / len(all_ids) if all_ids else None

        if not baseline_slice or not candidate_slice:
            results.append(
                SliceResult(
                    id=declaration.id,
                    field=declaration.field,
                    value=declaration.value,
                    status="BLOCK",
                    paired_n=0,
                    label_coverage=coverage,
                    adjusted_confidence_level=confidence,
                    sample_limitation="declared slice is absent from one or both runs",
                    guards=[],
                )
            )
            continue

        guards = evaluate_metric_guards(policy, baseline_slice, candidate_slice)
        results.append(
            SliceResult(
                id=declaration.id,
                field=declaration.field,
                value=declaration.value,
                status=_combined_status([guard.status for guard in guards]),
                paired_n=min((guard.paired_n for guard in guards), default=0),
                label_coverage=coverage,
                adjusted_confidence_level=confidence,
                sample_limitation=_slice_limitation(guards),
                guards=guards,
            )
        )
    return results


def _filter_rows(rows: Sequence[dict[str, Any]], declaration: SliceGuard) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        metadata = _metadata(row)
        if declaration.field not in metadata:
            continue
        observed = metadata[declaration.field]
        if type(observed) is type(declaration.value) and observed == declaration.value:
            selected.append(row)
    return selected


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("query_metadata")
    if isinstance(value, dict):
        return value
    value = row.get("query_metadata_json")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _combined_status(statuses: list[GuardStatus]) -> GuardStatus:
    for status in ("BLOCK", "FAIL", "HOLD", "PASS"):
        if status in statuses:
            return status
    return "BLOCK"


def _slice_limitation(guards: list[GuardResult]) -> str | None:
    limitations = [guard.sample_limitation for guard in guards if guard.sample_limitation]
    return "; ".join(limitations) if limitations else None
