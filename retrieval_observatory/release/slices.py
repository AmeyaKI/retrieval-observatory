from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from retrieval_observatory.release.policy import ReleasePolicy, SliceGuard
from retrieval_observatory.release.resolution import ResolvedPolicy, ResolvedSlice, RunEvidence
from retrieval_observatory.release.statistics import (
    CheckResult,
    GuardResult,
    GuardStatus,
    adjusted_confidence_level,
    evaluate_metric_guards,
    evaluate_resolved_check,
    resolved_adjusted_confidence,
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
    guards: list[CheckResult | GuardResult]
    #: The v3 checks this slice evaluates; empty for a v2 slice (every guard).
    check_ids: list[str] = Field(default_factory=list)


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


# --------------------------------------------------------------------------- resolved (v3) slices


def evaluate_resolved_slices(
    resolved: ResolvedPolicy,
    baseline: RunEvidence,
    candidate: RunEvidence,
    *,
    expected_query_ids: set[str] | None = None,
) -> list[SliceResult]:
    """Evaluate each declared slice's checks over its frozen membership.

    Membership comes from benchmark query metadata on the rows: a query is in the slice when
    either run's metadata says so (the baseline's metadata plus candidate rows carrying the same
    metadata). A disagreement between the runs is reported, never resolved by the candidate.
    ``expected_query_ids`` bounds membership to the attempted universe when given.
    """
    checks_by_id = {check.id: check for check in resolved.checks}
    confidence = resolved_adjusted_confidence(resolved)
    results = []
    for item in resolved.slices:
        baseline_members, baseline_labeled = _membership(baseline.metric_rows, item)
        candidate_members, candidate_labeled = _membership(candidate.metric_rows, item)
        disagreeing = sorted((baseline_labeled & candidate_labeled) & (baseline_members ^ candidate_members))
        members = baseline_members | candidate_members
        if expected_query_ids is not None:
            members &= set(expected_query_ids)
        present = {
            run.run_id: members & {row["query_id"] for row in run.metric_rows} for run in (baseline, candidate)
        }
        paired = present[baseline.run_id] & present[candidate.run_id]
        coverage = len(paired) / len(members) if members else None
        check_ids = list(item.metric_ids)

        if not members or not any(present.values()):
            limitation: str | None = "declared slice is absent from both runs"
        else:
            missing = [run_id for run_id, ids in present.items() if not ids]
            limitation = f"declared slice is absent from run {missing[0]}" if missing else None
        if limitation is not None:
            results.append(
                SliceResult(
                    id=item.id,
                    field=item.field,
                    value=item.value,
                    status="BLOCK",
                    paired_n=0,
                    label_coverage=coverage,
                    adjusted_confidence_level=confidence,
                    sample_limitation=_with_disagreement(limitation, item, disagreeing),
                    guards=[],
                    check_ids=check_ids,
                )
            )
            continue

        baseline_slice = replace(baseline, metric_rows=[row for row in baseline.metric_rows if row["query_id"] in members])
        candidate_slice = replace(candidate, metric_rows=[row for row in candidate.metric_rows if row["query_id"] in members])
        guards = [
            evaluate_resolved_check(checks_by_id[check_id], resolved, baseline_slice, candidate_slice, members)
            for check_id in check_ids
            if check_id in checks_by_id
        ]
        results.append(
            SliceResult(
                id=item.id,
                field=item.field,
                value=item.value,
                status=_combined_status([guard.status for guard in guards]),
                paired_n=min((guard.paired_n for guard in guards), default=0),
                label_coverage=coverage,
                adjusted_confidence_level=confidence,
                sample_limitation=_with_disagreement(_slice_limitation(guards), item, disagreeing),
                guards=guards,
                check_ids=check_ids,
            )
        )
    return results


def _membership(rows: Sequence[dict[str, Any]], item: ResolvedSlice) -> tuple[set[str], set[str]]:
    """(query ids in the slice, query ids whose metadata carries the field) for one run's rows."""
    members: set[str] = set()
    labeled: set[str] = set()
    for row in rows:
        metadata = _metadata(row)
        if item.field not in metadata:
            continue
        labeled.add(row["query_id"])
        observed = metadata[item.field]
        if type(observed) is type(item.value) and observed == item.value:
            members.add(row["query_id"])
    return members, labeled


def _with_disagreement(limitation: str | None, item: ResolvedSlice, disagreeing: list[str]) -> str | None:
    if not disagreeing:
        return limitation
    shown = ", ".join(disagreeing[:10]) + (", ..." if len(disagreeing) > 10 else "")
    note = (
        f"query metadata {item.field!r} disagrees between runs for {len(disagreeing)} queries ({shown}); "
        "membership is the union and was not redefined by the candidate"
    )
    return f"{limitation}; {note}" if limitation else note


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


def _slice_limitation(guards: Sequence[GuardResult]) -> str | None:
    limitations = [guard.sample_limitation for guard in guards if guard.sample_limitation]
    return "; ".join(limitations) if limitations else None
