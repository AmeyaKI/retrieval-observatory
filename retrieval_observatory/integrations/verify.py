from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence

from retrieval_observatory.integrations.model import IntegrationCheck, IntegrationManifest, IntegrationResult
from retrieval_observatory.tracing.model import RetrievalTrace

DEFAULT_DB_PATH = ".retobs/results.db"
DEFAULT_SERVE_PORT = 4000

_KNOWN_OP_TYPES = {
    "SOURCE", "FUSE", "RERANK", "BOOST", "EXPAND", "FILTER", "GATE",
    "TRANSFORM", "GENERATE",
}
_CAPABILITIES = (
    "basic_tracing", "pipeline_graph", "stage_metrics", "candidate_lineage",
    "replay", "attribution", "drift",
)


def _check(
    name: str,
    category: str,
    status: str,
    detail: str,
    *,
    required: bool = False,
    affects: tuple[str, ...] = (),
    fix: str | None = None,
) -> Dict[str, Any]:
    return {
        "name": name,
        "category": category,
        "status": status,
        "required": required,
        "detail": detail,
        "affects": list(affects),
        "fix": fix,
    }


def _has_cycle(spans: list) -> bool:
    parents = {span.op_id: list(span.parent_ids) for span in spans}
    state: Dict[str, int] = {}

    def visit(op_id: str) -> bool:
        if state.get(op_id) == 1:
            return True
        if state.get(op_id) == 2:
            return False
        state[op_id] = 1
        if any(parent in parents and visit(parent) for parent in parents.get(op_id, [])):
            return True
        state[op_id] = 2
        return False

    return any(visit(op_id) for op_id in parents)


def _integration_checks(traces: list) -> List[Dict[str, Any]]:
    """Validate the persisted evidence needed by each product capability."""
    checks: List[Dict[str, Any]] = []
    n = len(traces)
    if n == 0:
        return [
            _check(
                "traces_present", "arrival", "error",
                "No traces found; instrumentation has not been observed.",
                required=True, affects=_CAPABILITIES,
                fix="Run at least one representative query and push or persist its trace.",
            )
        ]

    checks.append(_check("traces_present", "arrival", "ok", f"{n} traces recorded.", required=True))

    now = datetime.now(timezone.utc)
    timestamps = []
    for trace in traces:
        timestamp = getattr(trace, "timestamp", None)
        if isinstance(timestamp, datetime):
            timestamps.append(timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc))
    future = sum(timestamp > now + timedelta(minutes=5) for timestamp in timestamps)
    if future:
        checks.append(_check(
            "clock_skew", "arrival", "error", f"{future}/{n} traces are more than five minutes in the future.",
            required=True, affects=("drift",), fix="Synchronize producer clocks before collecting traces.",
        ))
    else:
        checks.append(_check("clock_skew", "arrival", "ok", "No material producer clock skew detected.", required=True))

    latest = max(timestamps, default=None)
    if latest is not None and latest < now - timedelta(hours=24):
        checks.append(_check(
            "recent_arrival", "arrival", "warn", f"Latest trace is {latest.isoformat()}, more than 24 hours old.",
            affects=("drift",), fix="Send a current representative trace before relying on production health.",
        ))
    else:
        checks.append(_check("recent_arrival", "arrival", "ok", "Recent trace arrival confirmed."))

    ingestion_failures = sum(bool(getattr(t, "metadata", {}).get("ingestion_failure")) for t in traces)
    checks.append(_check(
        "ingestion_failures", "arrival", "error" if ingestion_failures else "ok",
        f"{ingestion_failures} ingestion failures declared." if ingestion_failures else "No ingestion failures declared.",
        required=True, affects=_CAPABILITIES,
        fix="Fix producer serialization or sink delivery errors, then resend representative traces." if ingestion_failures else None,
    ))

    rates = {
        t.metadata.get("sampling_rate")
        for t in traces
        if getattr(t, "metadata", None) and "sampling_rate" in t.metadata
    }
    invalid_rates = [rate for rate in rates if not isinstance(rate, (int, float)) or not 0 < float(rate) <= 1]
    if invalid_rates:
        checks.append(_check(
            "sampling_rate", "arrival", "error", f"Invalid sampling rates: {invalid_rates}.",
            required=True, affects=("stage_metrics", "attribution", "drift"),
            fix="Record sampling_rate as a number greater than 0 and at most 1.",
        ))
    elif rates and any(float(rate) < 1 for rate in rates):
        checks.append(_check(
            "sampling_rate", "arrival", "warn", f"Sampled traffic declared (rates={sorted(rates)}).",
            affects=("stage_metrics", "attribution", "drift"),
            fix="Use representative sampling and interpret aggregate findings using the declared rate.",
        ))
    else:
        checks.append(_check("sampling_rate", "arrival", "ok", "Full or default trace sampling recorded."))

    blank_identity = sum(
        not getattr(t, "trace_id", "") or not getattr(t, "run_id", "")
        or not getattr(t, "query_id", "") or not getattr(t, "pipeline_id", "")
        for t in traces
    )
    duplicate_trace_ids = [key for key, count in Counter(t.trace_id for t in traces).items() if key and count > 1]
    query_texts: Dict[str, set[str]] = {}
    for trace in traces:
        query_texts.setdefault(trace.query_id, set()).add(trace.query_text)
    query_collisions = [query_id for query_id, texts in query_texts.items() if query_id and len(texts) > 1]
    identity_error = blank_identity or duplicate_trace_ids or query_collisions
    identity_detail = (
        f"blank={blank_identity}, duplicate_trace_ids={len(duplicate_trace_ids)}, "
        f"query_id_collisions={len(query_collisions)}."
    )
    checks.append(_check(
        "stable_identity", "identity", "error" if identity_error else "ok",
        identity_detail if identity_error else "Trace, run, query, and pipeline identities are stable.",
        required=True, affects=_CAPABILITIES,
        fix="Emit non-empty stable IDs; a query_id must always identify the same query text." if identity_error else None,
    ))

    spans = [span for trace in traces for span in trace.spans]
    duplicate_ops = sum(len(span_ids) != len(set(span_ids)) for span_ids in ([s.op_id for s in t.spans] for t in traces))
    blank_ops = sum(not span.op_id for span in spans)
    missing_parents = sum(
        parent not in {span.op_id for span in trace.spans}
        for trace in traces for span in trace.spans for parent in span.parent_ids
    )
    cycles = sum(_has_cycle(trace.spans) for trace in traces)
    topology_error = duplicate_ops or blank_ops or missing_parents or cycles
    checks.append(_check(
        "valid_topology", "topology", "error" if topology_error else "ok",
        (
            f"duplicate_operator_sets={duplicate_ops}, blank_operator_ids={blank_ops}, "
            f"missing_parents={missing_parents}, cyclic_traces={cycles}."
            if topology_error else "All parent graphs are acyclic and reference observed operators."
        ),
        required=True, affects=("pipeline_graph", "stage_metrics", "candidate_lineage", "replay", "attribution"),
        fix="Emit unique operator IDs per trace, valid parent IDs, and an acyclic graph." if topology_error else None,
    ))

    missing_final = sum(
        trace.status == "OK" and (
            not trace.final_op_ids or not set(trace.final_op_ids) <= {span.op_id for span in trace.spans}
        )
        for trace in traces
    )
    checks.append(_check(
        "final_output", "topology", "error" if missing_final else "ok",
        f"{missing_final}/{n} successful traces lack an observed final operator." if missing_final else "Successful traces identify an observed final operator.",
        required=True, affects=("pipeline_graph", "candidate_lineage", "replay", "attribution"),
        fix="Set final_op_id to the actual terminal operator for every successful trace." if missing_final else None,
    ))

    unknown_ops = sorted({str(span.op_type) for span in spans if str(span.op_type) not in _KNOWN_OP_TYPES})
    checks.append(_check(
        "supported_operators", "completeness", "error" if unknown_ops else "ok",
        f"Unsupported operator types: {unknown_ops}." if unknown_ops else "All operator types use the canonical vocabulary.",
        required=True, affects=("pipeline_graph", "stage_metrics", "candidate_lineage", "replay", "attribution"),
        fix="Map each custom operation to a canonical OperatorType." if unknown_ops else None,
    ))

    invalid_durations = sum(span.latency_ms < 0 for span in spans)
    invalid_timing = 0
    for trace in traces:
        timing = getattr(trace, "timing", None)
        if timing is None or min(timing.wall_clock_ms, timing.critical_path_ms, timing.operator_sum_ms) < 0:
            invalid_timing += 1
        elif timing.critical_path_ms > timing.operator_sum_ms + 1e-6:
            invalid_timing += 1
    timing_error = invalid_durations or invalid_timing
    checks.append(_check(
        "timing_semantics", "timing", "error" if timing_error else "ok",
        (
            f"negative_operator_durations={invalid_durations}, invalid_trace_timing={invalid_timing}."
            if timing_error else "Wall-clock, critical-path, and operator-sum timing fields are valid."
        ),
        required=True, affects=("stage_metrics", "drift"),
        fix="Record non-negative durations with critical_path_ms no greater than operator_sum_ms." if timing_error else None,
    ))
    cache_declared = sum("cache_hit" in span.params for span in spans)
    checks.append(_check(
        "cache_indicators", "timing", "ok" if cache_declared else "warn",
        f"Cache state declared on {cache_declared}/{len(spans)} spans." if cache_declared else "No operator declares cache_hit; cold and cached latency cannot be separated.",
        affects=("stage_metrics",),
        fix="Record params.cache_hit on cacheable operators." if not cache_declared else None,
    ))

    candidates = [candidate for span in spans for candidate in [*span.inputs, *span.outputs]]
    blank_docs = sum(not candidate.doc_id for candidate in candidates)
    missing_scores = sum(candidate.score is None for candidate in candidates)
    invalid_ranks = sum((candidate.output_rank or candidate.rank) < 1 for candidate in candidates)
    missing_origins = sum(not candidate.origin_op_ids for candidate in candidates)
    candidate_error = blank_docs or invalid_ranks
    candidate_status = "error" if candidate_error else ("warn" if missing_scores or missing_origins else "ok")
    checks.append(_check(
        "candidate_identity", "candidates", candidate_status,
        (
            f"blank_doc_ids={blank_docs}, missing_scores={missing_scores}, "
            f"invalid_ranks={invalid_ranks}, missing_origins={missing_origins}."
            if candidate_status != "ok" else "Candidate IDs, scores, ranks, and source origins are available."
        ),
        required=bool(candidate_error), affects=("candidate_lineage", "replay", "attribution"),
        fix="Emit stable doc IDs, positive ranks, scores, and immutable origin_op_ids." if candidate_status != "ok" else None,
    ))
    missing_inputs = sum(span.op_type != "SOURCE" and span.status == "FIRED" and not span.inputs for span in spans)
    checks.append(_check(
        "candidate_transitions", "candidates", "warn" if missing_inputs else "ok",
        f"{missing_inputs} fired non-source operators omit input candidates." if missing_inputs else "Non-source operators preserve candidate inputs and outputs.",
        affects=("candidate_lineage", "replay", "attribution"),
        fix="Record the actual input candidate list before every non-source operator." if missing_inputs else None,
    ))

    has_ground_truth = any(
        any(key in getattr(trace, "metadata", {}) for key in ("qrel_ids", "relevant_doc_ids", "label_method"))
        for trace in traces
    )
    checks.append(_check(
        "ground_truth", "ground_truth", "ok" if has_ground_truth else "warn",
        "Ground-truth provenance is declared." if has_ground_truth else "No trace-level qrel or label provenance is available; production quality is unavailable.",
        affects=("attribution",),
        fix="Join qrels/corpus identity and record label_method before using quality attribution." if not has_ground_truth else None,
    ))

    missing_query_text = sum(not getattr(trace, "query_text", "") for trace in traces)
    checks.append(_check(
        "query_text_metadata", "completeness", "warn" if missing_query_text else "ok",
        f"{missing_query_text}/{n} traces have no query_text." if missing_query_text else "All traces carry query text.",
        affects=("candidate_lineage", "attribution"),
        fix="Record the normalized query text on every trace." if missing_query_text else None,
    ))
    partial = sum(trace.status in ("ERROR", "TIMEOUT") for trace in traces)
    checks.append(_check(
        "trace_health", "completeness", "warn" if partial else "ok",
        f"{partial}/{n} traces are terminal partial ERROR/TIMEOUT traces." if partial else "No error or timeout traces in this sample.",
        affects=("stage_metrics", "attribution", "drift"),
        fix="Inspect partial traces and verify whether the observed failure rate is expected." if partial else None,
    ))
    return checks


@dataclass(frozen=True)
class VerificationCheck:
    name: str
    status: str
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationReport:
    checks: tuple[VerificationCheck, ...]

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(item.status == "ok" for item in self.checks)

    def check(self, name: str) -> VerificationCheck:
        return next(item for item in self.checks if item.name == name)


def operator_signature(trace: RetrievalTrace) -> dict[str, tuple[str, tuple[str, ...]]]:
    return {span.op_id: (span.op_type, tuple(span.parent_ids)) for span in trace.spans}


def verify_trace_contract(
    manifest: IntegrationManifest, traces: Sequence[RetrievalTrace]
) -> VerificationReport:
    declared = {item.op_id: (item.op_type, tuple(item.parent_ids)) for item in manifest.operators}
    signatures = [operator_signature(trace) for trace in traces]
    drift = [
        {op_id: actual for op_id, actual in signature.items() if declared.get(op_id) != actual}
        for signature in signatures
    ]
    missing = [sorted(set(declared) - set(signature)) for signature in signatures]
    unknown = sorted({op_id for signature in signatures for op_id in signature if op_id not in declared})
    topology_error = bool(unknown or any(drift) or any(missing))

    parent_missing = sorted({
        f"{span.op_id}:{parent}"
        for trace in traces for span in trace.spans for parent in span.parent_ids
        if parent not in operator_signature(trace)
    })
    grouped_missing = sorted({
        span.op_id for trace in traces for span in trace.spans
        if span.status == "FIRED" and span.parent_ids and set(span.input_groups) != set(span.parent_ids)
    })

    declared_branches: set[str] = set()
    for item in manifest.operators:
        declared_branches.update(getattr(item, "branches", {}) or {})
    declared_branches.update(getattr(manifest, "branches", {}) or {})
    observed_routes = {
        str(span.gate_values["selected_route"])
        for trace in traces for span in trace.spans
        if span.op_type == "GATE" and span.gate_values.get("selected_route") is not None
    }
    missing_branches = sorted(declared_branches - observed_routes)

    invalid_finals = [
        trace.trace_id for trace in traces
        if trace.status == "OK" and (
            not trace.final_op_ids or not set(trace.final_op_ids) <= set(operator_signature(trace))
        )
    ]
    checks = (
        VerificationCheck(
            "topology_identity", "error" if topology_error else "ok",
            {"unknown": unknown, "missing_by_trace": missing, "drift_by_trace": drift},
        ),
        VerificationCheck(
            "parent_coverage", "error" if parent_missing or grouped_missing else "ok",
            {"missing_parents": parent_missing, "missing_candidate_groups": grouped_missing},
        ),
        VerificationCheck(
            "branch_coverage", "error" if missing_branches else "ok",
            {"observed": sorted(observed_routes), "missing": missing_branches},
        ),
        VerificationCheck("unknown_components", "error" if unknown else "ok", {"unknown": unknown}),
        VerificationCheck("final_output", "error" if invalid_finals else "ok", {"invalid": invalid_finals}),
    )
    return VerificationReport(checks)


def _capability_matrix(checks: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    matrix: Dict[str, Dict[str, Any]] = {}
    for capability in _CAPABILITIES:
        relevant = [check for check in checks if capability in check.get("affects", [])]
        errors = [check["name"] for check in relevant if check["status"] == "error"]
        warnings = [check["name"] for check in relevant if check["status"] == "warn"]
        state = "unavailable" if errors else ("limited" if warnings else "ready")
        matrix[capability] = {"status": state, "errors": errors, "warnings": warnings}
    return matrix


def dashboard_base_url() -> str:
    port = int(os.environ.get("RETOBS_SERVE_PORT", DEFAULT_SERVE_PORT))
    host = os.environ.get("RETOBS_SERVE_HOST", "127.0.0.1")
    return f"http://{host}:{port}"


def dashboard_run_url(run_id: str, section: str = "overview") -> str:
    return f"{dashboard_base_url()}/#/runs/{run_id}/{section}"


def _store(db_path: str):
    from retrieval_observatory.store.sqlite import SQLiteStore

    return SQLiteStore(db_path=db_path)


async def verify_integration(
    db_path: str = DEFAULT_DB_PATH,
    run_id: Optional[str] = None,
    expected_stages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Verify evidence contracts and return capability-specific readiness."""
    store = _store(db_path)
    await store.init_db()
    runs = await store.list_runs()
    if not runs:
        checks = _integration_checks([])
        return {
            "status": "not_verified",
            "message": "No runs or observed traces exist in this database.",
            "checks": checks,
            "check_status": "error",
            "capabilities": _capability_matrix(checks),
            "next": "Run a representative evaluation or push traces, then verify again.",
            "dashboard_url": dashboard_base_url(),
        }

    target = run_id or runs[0]["run_id"]
    from retrieval_observatory.store.base import TraceQuery

    traces = await store.list_traces(TraceQuery(run_id=target))
    from retrieval_observatory.metrics.engine import MetricsEngine

    metrics = await MetricsEngine().aggregate(target, store)
    stages_seen = sorted({span.op_id for trace in traces for span in trace.spans})
    pipeline_ids = sorted({value["pipeline_id"] for value in metrics.values() if value.get("stage_index", -1) >= 0})
    missing_stages = sorted(set(expected_stages or []) - set(stages_seen))
    checks = _integration_checks(traces)
    if missing_stages:
        checks.append(_check(
            "expected_stages", "topology", "error",
            f"Expected operators were not observed: {missing_stages}.",
            required=True, affects=("pipeline_graph", "stage_metrics", "candidate_lineage", "replay", "attribution"),
            fix=f"Instrument and exercise these operators: {', '.join(missing_stages)}.",
        ))

    required_errors = [check for check in checks if check["status"] == "error" and check.get("required")]
    warnings = [check for check in checks if check["status"] == "warn"]
    if required_errors:
        status = "failed"
        check_status = "error"
    elif warnings:
        status = "partially_instrumented"
        check_status = "warn"
    else:
        status = "ready"
        check_status = "ok"

    next_steps = ["get_run_metrics"]
    if pipeline_ids:
        next_steps.extend(["get_pareto_frontier", "get_pipeline_graph"])
    next_steps[:0] = [check["fix"] for check in checks if check.get("fix")]
    return {
        "status": status,
        "run_id": target,
        "trace_count": len(traces),
        "stages_seen": stages_seen,
        "missing_stages": missing_stages,
        "pipeline_ids": pipeline_ids,
        "has_metrics": bool(metrics),
        "instrumentation": "trace_native" if traces else "benchmark_only",
        "checks": checks,
        "check_status": check_status,
        "capabilities": _capability_matrix(checks),
        "dashboard_url": dashboard_run_url(target),
        "next": next_steps,
    }


def verify_observed_traces(manifest: IntegrationManifest, traces: Sequence[RetrievalTrace]) -> IntegrationResult:
    declared = {op.op_id for op in manifest.operators}
    observed = {span.op_id for trace in traces for span in trace.spans}
    expected_edges = {(parent, op.op_id) for op in manifest.operators for parent in op.parent_ids}
    observed_edges = {(parent, span.op_id) for trace in traces for span in trace.spans for parent in span.parent_ids}
    specifications = (
        ("trace_sample", bool(traces), "Run every verification scenario."),
        ("expected_operators", declared <= observed, f"Missing operators: {sorted(declared-observed)}"),
        ("stable_operator_identity", observed <= declared, f"Unknown operators: {sorted(observed-declared)}"),
        ("declared_edges", expected_edges <= observed_edges, f"Missing edges: {sorted(expected_edges-observed_edges)}"),
        ("candidate_transitions", all(not s.parent_ids or bool(s.input_groups) for t in traces for s in t.spans), "Capture parent-grouped candidates."),
        ("timing", all(t.timing is not None for t in traces), "Capture trace timing."),
    )
    checks = tuple(IntegrationCheck(name, "ok" if passed else "error", "measured", "1.0", len(traces), fix=None if passed else fix) for name, passed, fix in specifications)
    errors = tuple(check.fix or check.check_id for check in checks if check.status == "error")
    signatures = Counter(tuple(sorted((span.op_id, tuple(span.parent_ids)) for span in trace.spans)) for trace in traces)
    variants = tuple({"signature": repr(signature), "count": count} for signature, count in signatures.items())
    available = not errors
    capabilities = {
        "candidate_transitions": {"available": available, "status": "ready" if available else "unavailable"},
        "operator_debugging": {"available": available, "status": "ready" if available else "unavailable"},
        "production_investigation": {"available": available, "status": "ready" if available else "unavailable"},
        "stable_topology": {"available": available, "status": "ready" if available else "unavailable"},
    }
    return IntegrationResult("verify", "ready" if available else "failed", checks=checks, capabilities=capabilities, observed_operator_ids=tuple(sorted(observed)), topology_variants=variants, errors=errors)


def _release_preflight(policy, manifest, traces, health) -> Dict[str, Any]:
    from retrieval_observatory.release.assessment import assess_evidence
    from retrieval_observatory.release.evidence import EvidenceProfile
    from retrieval_observatory.release.readiness import ClaimReadiness, EvidenceFinding

    profile = EvidenceProfile.from_run(
        {
            "release_identity": {
                "service_id": manifest.service_id,
                "deployment_revision": manifest.plan_id,
            }
        },
        traces,
        health,
    )
    preflight_manifest = {
        "dataset": {
            "query_hash": "integration-preflight",
            "corpus_hash": "integration-preflight",
            "qrel_hash": "integration-preflight",
        },
        "labeling": {"method": "integration-preflight-unavailable"},
        "release_identity": profile.release_identity.model_dump(mode="json"),
        "evidence_profile": profile.model_dump(mode="json"),
    }
    assessment = assess_evidence(policy, preflight_manifest, preflight_manifest)
    promotion_findings = [
        *assessment.readiness["promotion"].findings,
        EvidenceFinding(
            code="paired_metrics_unavailable",
            scope="promotion",
            status="HOLD",
            observed=None,
            required=[guard.metric for guard in policy.metrics],
            detail="Integration preflight does not execute paired release metrics.",
            next_action="Run a baseline/candidate comparison before making a promotion decision.",
        ),
    ]
    promotion = ClaimReadiness(
        scope="promotion",
        status="BLOCK" if any(item.status == "BLOCK" for item in promotion_findings) else "HOLD",
        findings=promotion_findings,
    )
    return {
        "promotion": promotion.model_dump(mode="json"),
        "lineage_diagnosis": assessment.readiness["lineage_diagnosis"].model_dump(mode="json"),
    }


async def verify_project(root, store, policy=None) -> IntegrationResult:
    from pathlib import Path
    from retrieval_observatory.integrations.manifest import load_manifest
    from retrieval_observatory.store.base import TraceQuery
    manifest = load_manifest(Path(root))
    traces = await store.list_traces(TraceQuery(service_id=manifest.service_id, pipeline_id=manifest.pipeline_id))
    result = verify_observed_traces(manifest, traces)
    health = await store.get_instrumentation_health(manifest.service_id)
    telemetry_health = asdict(health) if health is not None else {
        "serialization_failures": 0,
        "export_failures": 0,
    }
    if health is not None:
        telemetry_health["export_failures"] = health.permanent_failures
    release_readiness = _release_preflight(policy, manifest, traces, health) if policy is not None else {}
    return replace(
        result,
        telemetry_health=telemetry_health,
        release_readiness=release_readiness,
    )
