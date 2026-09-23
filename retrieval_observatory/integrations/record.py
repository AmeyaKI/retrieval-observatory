"""The verification record Connect reads.

``integrate --phase verify`` persists one ``integration`` analysis record per
(service, pipeline) in the trace database it verified against, so the dashboard can show the
plan summary, the capability report, and the open questions without access to the project tree.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from retrieval_observatory.integrations.model import IntegrationManifest, IntegrationPlan, IntegrationResult, OperatorMapping

INTEGRATION_RECORD_KIND = "integration"
RECORD_SCHEMA_VERSION = 1


def integration_id(service_id: str, pipeline_id: str) -> str:
    return f"{service_id}:{pipeline_id}"


def integration_depth(operators: Sequence[OperatorMapping]) -> str:
    """``internal`` when at least one operator receives another's output; else ``final_only``.

    A final-output-only integration still supports quality evaluation, but no internal
    transition is observed, so per-stage loss attribution is out of reach and Connect says so.
    """
    return "internal" if any(operator.parent_ids for operator in operators) else "final_only"


def build_integration_record(
    manifest: IntegrationManifest,
    result: IntegrationResult,
    *,
    project_root: Path,
    db_path: str,
    plan: IntegrationPlan | None = None,
) -> dict[str, Any]:
    payload = result.to_dict()  # JSON-safe: datetimes in telemetry health are normalized here
    return {
        "schema_version": RECORD_SCHEMA_VERSION,
        "integration_id": integration_id(manifest.service_id, manifest.pipeline_id),
        "service_id": manifest.service_id,
        "pipeline_id": manifest.pipeline_id,
        "plan_id": manifest.plan_id,
        "project_root": str(project_root),
        "db_path": db_path,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "status": result.status,
        "depth": integration_depth(manifest.operators),
        "capabilities": payload["capabilities"],
        "errors": payload["errors"],
        "observed_operator_ids": payload["observed_operator_ids"],
        "telemetry_health": payload["telemetry_health"],
        "release_readiness": payload["release_readiness"],
        "operators": [operator.to_dict() for operator in manifest.operators],
        "scenarios": [scenario.to_dict() for scenario in manifest.scenarios],
        "boundary": manifest.boundary.to_dict(),
        "identity": manifest.identity.to_dict(),
        "judgments": dict(manifest.judgments),
        "expected_capabilities": dict(manifest.expected_capabilities),
        "actions": [action.to_dict() for action in plan.actions] if plan else [],
        "open_questions": list(plan.open_questions) if plan else [],
        "unresolved": list(plan.unresolved) if plan else [],
    }


async def save_integration_record(store: Any, payload: Mapping[str, Any]) -> int:
    """Append a new version of the record; returns the version written."""
    current = await store.get_analysis_record(INTEGRATION_RECORD_KIND, payload["integration_id"])
    version = int((current or {}).get("version", 0)) + 1
    await store.save_analysis_record(INTEGRATION_RECORD_KIND, payload["integration_id"], dict(payload), version)
    return version


async def list_integration_records(store: Any) -> list[dict[str, Any]]:
    records = await store.list_analysis_records(INTEGRATION_RECORD_KIND)
    return sorted(records, key=lambda item: str(item.get("verified_at", "")), reverse=True)


async def get_integration_record(store: Any, record_id: str) -> dict[str, Any] | None:
    return await store.get_analysis_record(INTEGRATION_RECORD_KIND, record_id)
