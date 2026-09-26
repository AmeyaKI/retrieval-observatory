from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from retrieval_observatory.integrations.model import CAPABILITY_NAMES, IntegrationCheck, IntegrationManifest, IntegrationResult
from retrieval_observatory.tracing.lineage_contract import validate_unique_candidate_ids
from retrieval_observatory.tracing.model import OperatorSpan, RetrievalTrace

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


def _integration_checks(traces: list, *, require_run_id: bool = True) -> List[Dict[str, Any]]:
    """Validate the persisted evidence needed by each product capability.

    ``require_run_id=False`` is for production traces recorded outside a benchmark run, where
    ``run_id`` is legitimately empty; every other identity field is still required.
    """
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
        not getattr(t, "trace_id", "") or (require_run_id and not getattr(t, "run_id", ""))
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
    unknown = sorted({op_id for signature in signatures for op_id in signature if op_id not in declared})
    # A declared operator absent from one trace is a route that did not fire for that query
    # (declared_route_coverage's concern), not a topology mismatch.
    topology_error = bool(unknown or any(drift))

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
            {"unknown": unknown, "drift_by_trace": drift},
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


def _trace_has_evidence(trace: RetrievalTrace) -> bool:
    """A trace counts as evidence only if something observable happened in it: a FIRED operator
    whose output was actually read (a candidate with a doc_id, or a gate's recorded decision,
    which legitimately yields no candidates on a skip route), a query, and measured wall-clock time."""
    fired_with_output = any(
        span.status == "FIRED"
        and (any(candidate.doc_id for candidate in span.outputs) or (span.op_type == "GATE" and bool(span.gate_values)))
        for span in trace.spans
    )
    timed = trace.timing is not None and trace.timing.wall_clock_ms > 0
    return fired_with_output and bool(trace.query_text) and timed


_CORE_CAPABILITIES = ("topology_observed", "query_identity", "candidate_identity", "final_output_capture")
_CHECK_STATUS = {"ready": "ok", "partial": "warn", "unavailable": "error"}
_COMPLETE_INPUT_CAPTURE = {"recorded", "not_applicable"}
_CAPTURE_SPEC_FIX = (
    "define a CaptureSpec `{op}_capture` in retobs_adapter.py whose `inputs` maps the bound arguments to "
    "{{parent_id: candidates}} and set capture: 'retobs_adapter:{op}_capture' in the plan"
)
_OUTPUT_SHAPE_FIX = (
    "return a sequence of candidates or a mapping with a `documents` key, "
    "or declare the last operator's output as the boundary"
)


def _operator_id(span: OperatorSpan) -> str:
    return span.operator_id or span.op_id


def _is_return_boundary(span: OperatorSpan) -> bool:
    """The ``return`` span ``trace_scope`` and ``evaluate`` synthesize from the entrypoint's result."""
    return span.params.get("boundary") == "callable_return"


def _failure(code: str, detail: str, fix: str, op_id: str | None = None) -> Dict[str, Any]:
    return {"code": code, "detail": detail, "fix": fix, "op_id": op_id}


def _capability(status: str, evidence: Mapping[str, Any], scope: str, failures: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {"status": status, "evidence": dict(evidence), "scope": scope, "failures": [dict(item) for item in failures]}


def _status(passed: int, checked: int) -> str:
    """ready when everything checked passed, partial when some did, unavailable when nothing did."""
    if checked == 0 or passed == 0:
        return "unavailable"
    return "ready" if passed == checked else "partial"


def _trace_invariant_failures(trace: RetrievalTrace) -> List[Dict[str, Any]]:
    """Graph invariants one trace must satisfy on its own, whatever the manifest declares."""
    failures: List[Dict[str, Any]] = []
    spans = list(trace.spans)
    by_id: Dict[str, OperatorSpan] = {}
    for span in spans:
        if span.op_id in by_id:
            failures.append(_failure(
                "duplicate_op_id", f"trace {trace.trace_id}: node key {span.op_id!r} is used by two spans",
                "give each invocation its own node key (next_node_id yields rerank#2 for a repeated operator)", span.op_id,
            ))
        by_id[span.op_id] = span
    for span in spans:
        for parent in span.parent_ids:
            if parent not in by_id:
                failures.append(_failure(
                    "parent_unknown", f"trace {trace.trace_id}: {span.op_id} names parent {parent!r}, which is not a span of this trace",
                    "parents must be operators observed in the same trace", span.op_id,
                ))
    if _has_cycle(spans):
        failures.append(_failure("cyclic_graph", f"trace {trace.trace_id}: the parent graph has a cycle", "an operator cannot be its own ancestor"))
    invocations: Dict[str, str] = {}
    for span in spans:
        if not span.invocation_id:
            continue
        if span.invocation_id in invocations:
            failures.append(_failure(
                "invocation_id_reused",
                f"trace {trace.trace_id}: {span.op_id} reuses invocation_id {span.invocation_id} of {invocations[span.invocation_id]}",
                "record a fresh invocation_id for every call", span.op_id,
            ))
        invocations.setdefault(span.invocation_id, span.op_id)
    for span in spans:
        for invocation_id in span.parent_invocation_ids:
            if invocation_id not in invocations:
                failures.append(_failure(
                    "parent_invocation_unknown",
                    f"trace {trace.trace_id}: {span.op_id} references parent invocation {invocation_id}, which no span of this trace carries",
                    "parent_invocation_ids must name invocations observed in the same trace", span.op_id,
                ))
    for span in spans:
        if span.input_capture != "recorded" or span.parent_linkage not in ("recorded", "declared"):
            continue
        for parent_id, group in span.input_groups.items():
            parent = by_id.get(parent_id)
            if parent is None or parent.output_capture != "recorded":
                continue
            absent = {candidate.doc_id for candidate in group} - {candidate.doc_id for candidate in parent.outputs}
            if absent:
                failures.append(_failure(
                    "parent_inputs_unrelated",
                    f"trace {trace.trace_id}: {len(absent)} of {len(group)} recorded input ids of {span.op_id} are absent from the "
                    f"outputs of its parent {parent_id}: an operator between them is not instrumented, or the parent link is fabricated",
                    f"instrument the operator that feeds {span.op_id}, or declare its actual parent", span.op_id,
                ))
    return failures


def _return_transition_failures(trace: RetrievalTrace) -> List[Dict[str, Any]]:
    """A ``return`` boundary whose ids differ from its parents' outputs hides an uninstrumented step."""
    by_id = {span.op_id: span for span in trace.spans}
    failures: List[Dict[str, Any]] = []
    for span in trace.spans:
        if not _is_return_boundary(span) or span.status != "FIRED" or span.output_capture != "recorded":
            continue
        upstream = [c.doc_id for parent in span.parent_ids if parent in by_id for c in by_id[parent].outputs]
        returned = [c.doc_id for c in span.outputs]
        if upstream == returned:
            continue
        parents = ", ".join(span.parent_ids) or "the observed operators"
        differing = len(set(upstream) ^ set(returned))
        change = f"differs from {parents} by {differing} ids" if differing else f"reorders the outputs of {parents}"
        failures.append(_failure(
            "unobserved_transition_before_return",
            f"trace {trace.trace_id}: final output {change}: an operator between them is not instrumented",
            "instrument the operator that runs after the last observed one, or declare its output as the boundary", span.op_id,
        ))
    return failures


def _topology_observed(manifest: IntegrationManifest, traces: Sequence[RetrievalTrace], no_traces: str) -> Dict[str, Any]:
    declared = sorted({op.op_id for op in manifest.operators})
    observed = sorted({_operator_id(span) for trace in traces for span in trace.spans if not _is_return_boundary(span)})
    undeclared = sorted(set(observed) - set(declared))
    failures: List[Dict[str, Any]] = []
    transitions: List[Dict[str, Any]] = []
    valid = 0
    for trace in traces:
        invariants = _trace_invariant_failures(trace)
        valid += not invariants
        failures.extend(invariants)
        transitions.extend(_return_transition_failures(trace))
    failures.extend(transitions)
    for op_id in undeclared:
        failures.append(_failure(
            "undeclared_operator_observed", f"operator {op_id!r} fired but the manifest does not declare it",
            f"add {op_id!r} to the plan's operators, or remove its @observe decorator if it is not part of this pipeline", op_id,
        ))
    if not traces:
        failures.append(_failure("no_traces", no_traces, "run one declared scenario, then verify again"))
        status = "unavailable"
    elif valid == 0:
        status = "unavailable"
    elif valid < len(traces) or undeclared or transitions:
        status = "partial"
    else:
        status = "ready"
    evidence = {
        "traces": len(traces), "traces_valid": valid, "declared_operators": declared,
        "observed_operators": observed, "undeclared_operators": undeclared,
    }
    scope = (
        f"{len(traces)} traces; graph invariants checked per trace independently of the manifest, "
        f"then observed operators compared with the {len(declared)} declared"
    )
    return _capability(status, evidence, scope, failures)


def _actual_input_output_capture(traces: Sequence[RetrievalTrace]) -> Dict[str, Any]:
    spans = [span for trace in traces for span in trace.spans if span.status == "FIRED" and not _is_return_boundary(span)]
    output_codes: Dict[str, set[str]] = {}
    for trace in traces:
        for failure in trace.capture_failures:
            if failure.get("phase") == "outputs":
                output_codes.setdefault(str(failure.get("op_id")), set()).add(str(failure.get("code")))

    def complete(span: OperatorSpan) -> bool:
        return span.input_capture in _COMPLETE_INPUT_CAPTURE and span.output_capture == "recorded"

    by_operator: Dict[str, Dict[str, int]] = {}
    codes_by_operator: Dict[str, set[str]] = {}
    for span in spans:
        operator = _operator_id(span)
        row = by_operator.setdefault(operator, {"recorded": 0, "positional": 0, "inferred": 0, "unavailable": 0, "output_unavailable": 0})
        row["recorded" if span.input_capture in _COMPLETE_INPUT_CAPTURE else span.input_capture] += 1
        if span.output_capture != "recorded":
            row["output_unavailable"] += 1
            codes_by_operator.setdefault(operator, set()).update(output_codes.get(span.op_id, ()))
    failures: List[Dict[str, Any]] = []
    for operator, row in sorted(by_operator.items()):
        invocations = sum(row[key] for key in ("recorded", "positional", "inferred", "unavailable"))
        if row["unavailable"]:
            failures.append(_failure(
                "missing_actual_inputs", f"{row['unavailable']} of {invocations} invocations of {operator} lack recorded inputs",
                _CAPTURE_SPEC_FIX.format(op=operator), operator,
            ))
        if row["positional"] or row["inferred"]:
            failures.append(_failure(
                "inferred_inputs",
                f"{row['positional'] + row['inferred']} of {invocations} invocations of {operator} have inputs matched by "
                "position or reconstructed from parent spans rather than read from the call",
                _CAPTURE_SPEC_FIX.format(op=operator), operator,
            ))
        if row["output_unavailable"]:
            codes = sorted(codes_by_operator.get(operator, ()))
            failures.append(_failure(
                "output_capture_unavailable",
                f"{row['output_unavailable']} of {invocations} invocations of {operator} have no recorded outputs"
                + (f" ({', '.join(codes)})" if codes else ""),
                f"return a sequence of candidates or a mapping with a `documents` key from {operator}, or define a CaptureSpec "
                f"`{operator}_capture` in retobs_adapter.py whose `outputs` maps the returned object to candidates",
                operator,
            ))
    completed = sum(1 for span in spans if complete(span))
    # Status follows the candidate transitions (spans with parents): a pipeline whose interior
    # boundaries are all missing is final-output-only, however well its sources are captured.
    scored = [span for span in spans if span.parent_ids] or spans
    if not spans:
        failures.append(_failure("no_fired_operators", "no FIRED operator span was observed", "run one declared scenario against the instrumented entrypoint"))
        status = "unavailable"
    elif completed == len(spans):
        status = "ready"
    elif not any(complete(span) for span in scored):
        status = "unavailable"
    else:
        status = "partial"
    evidence = {
        "spans": len(spans), "complete": completed,
        "positional_or_inferred": sum(1 for span in spans if span.input_capture in ("positional", "inferred")),
        "unavailable": sum(1 for span in spans if span.input_capture == "unavailable"),
        "by_operator": by_operator,
    }
    scope = f"{len(spans)} FIRED spans across {len(traces)} traces; inputs must be read from the call and outputs from the returned object"
    return _capability(status, evidence, scope, failures)


def _candidate_identity(traces: Sequence[RetrievalTrace]) -> Dict[str, Any]:
    candidates = [candidate for trace in traces for span in trace.spans for candidate in (*span.inputs, *span.outputs)]
    blank = sum(1 for candidate in candidates if not candidate.doc_id)
    invalid_ranks = sum(1 for candidate in candidates if (candidate.output_rank or candidate.rank) < 1)
    valid = sum(1 for candidate in candidates if candidate.doc_id and (candidate.output_rank or candidate.rank) >= 1)
    duplicate_spans: List[tuple[str, str]] = []
    for trace in traces:
        for span in trace.spans:
            try:
                validate_unique_candidate_ids(span.outputs)
            except ValueError:
                duplicate_spans.append((trace.trace_id, span.op_id))
    failures: List[Dict[str, Any]] = []
    if not candidates:
        failures.append(_failure(
            "no_candidates", "no span carries a candidate with a doc_id: outputs were not captured, or candidate_mapping.doc_id does not name the id field",
            "map candidate_mapping.doc_id to the field holding the document id and capture every operator's outputs",
        ))
    if blank:
        failures.append(_failure("blank_candidate_ids", f"{blank} of {len(candidates)} candidates have an empty doc_id", "emit a non-empty stable document id for every candidate"))
    if invalid_ranks:
        failures.append(_failure("invalid_candidate_ranks", f"{invalid_ranks} of {len(candidates)} candidates have a rank below 1", "ranks start at 1 and follow the returned order"))
    for trace_id, op_id in duplicate_spans:
        failures.append(_failure(
            "duplicate_candidate_ids", f"trace {trace_id}: {op_id} emitted the same candidate id twice",
            "deduplicate candidates before returning them, or give chunks of one document distinct ids", op_id,
        ))
    status = "partial" if valid and (blank or invalid_ranks or duplicate_spans) else _status(valid, len(candidates))
    evidence = {"candidates": len(candidates), "blank_ids": blank, "invalid_ranks": invalid_ranks, "duplicate_output_spans": len(duplicate_spans)}
    scope = f"{len(candidates)} candidates across every span's inputs and outputs in {len(traces)} traces"
    return _capability(status, evidence, scope, failures)


def _query_identity(traces: Sequence[RetrievalTrace]) -> Dict[str, Any]:
    texts_by_id: Dict[str, set[str]] = {}
    for trace in traces:
        texts_by_id.setdefault(trace.query_id, set()).add(trace.query_text)
    collisions = sorted(query_id for query_id, texts in texts_by_id.items() if query_id and len(texts) > 1)
    trace_ids = Counter(trace.trace_id for trace in traces)
    duplicates = sorted(trace_id for trace_id, count in trace_ids.items() if count > 1)
    missing_text = [trace.trace_id for trace in traces if not trace.query_text]
    missing_id = [trace.trace_id for trace in traces if not trace.query_id]
    valid = sum(
        1 for trace in traces
        if trace.query_text and trace.query_id and trace.query_id not in collisions and trace_ids[trace.trace_id] == 1
    )
    failures: List[Dict[str, Any]] = []
    if not traces:
        failures.append(_failure("no_traces", "no trace was observed", "run one declared scenario, then verify again"))
    if missing_text:
        failures.append(_failure(
            "missing_query_text", f"{len(missing_text)} of {len(traces)} traces have no query_text (e.g. {missing_text[0]})",
            "record the query text on every trace; trace_scope reads it from the entrypoint's query argument",
        ))
    if missing_id:
        failures.append(_failure("missing_query_id", f"{len(missing_id)} of {len(traces)} traces have no query_id", "give every trace a stable query_id"))
    for query_id in collisions:
        failures.append(_failure(
            "query_id_collision", f"query_id {query_id!r} maps to {len(texts_by_id[query_id])} different query texts",
            "derive query_id from the query text, or pass one stable id per query",
        ))
    for trace_id in duplicates:
        failures.append(_failure("duplicate_trace_id", f"trace_id {trace_id!r} was recorded {trace_ids[trace_id]} times", "give every trace a fresh trace_id"))
    evidence = {
        "traces": len(traces), "missing_query_text": len(missing_text), "missing_query_id": len(missing_id),
        "query_id_collisions": len(collisions), "duplicate_trace_ids": len(duplicates),
    }
    scope = f"{len(traces)} traces; each needs a query_id, a query_text, one text per query_id and a unique trace_id"
    return _capability(_status(valid, len(traces)), evidence, scope, failures)


def _final_output_capture(manifest: IntegrationManifest, traces: Sequence[RetrievalTrace]) -> Dict[str, Any]:
    successful = [trace for trace in traces if trace.status == "OK"]
    operator_boundary = manifest.boundary.kind == "operator_output"
    failures: List[Dict[str, Any]] = []
    captured = 0
    with_return_boundary = 0
    for trace in successful:
        by_id = {span.op_id: span for span in trace.spans}
        with_return_boundary += any(_is_return_boundary(span) for span in trace.spans)
        finals = [by_id[op_id] for op_id in trace.final_op_ids if op_id in by_id]
        fired = [span for span in finals if span.status == "FIRED"]
        problems: List[Dict[str, Any]] = []
        if not trace.final_op_ids or len(finals) != len(trace.final_op_ids):
            problems.append(_failure(
                "final_boundary_missing", f"trace {trace.trace_id}: final_op_ids {list(trace.final_op_ids)} do not name observed spans",
                "finish the trace through trace_scope, or set final_op_ids to the operators whose output leaves the application",
            ))
        elif not fired:
            problems.append(_failure(
                "final_boundary_missing", f"trace {trace.trace_id}: no final operator fired",
                "finish the trace through trace_scope, or set final_op_ids to the operators whose output leaves the application",
            ))
        problems.extend(
            _failure("final_boundary_missing", f"trace {trace.trace_id}: final operator {span.op_id} has no recorded outputs", _OUTPUT_SHAPE_FIX, span.op_id)
            for span in fired if span.output_capture != "recorded"
        )
        if not operator_boundary:
            problems.extend(
                _failure(
                    "final_output_shape_unsupported",
                    f"trace {trace.trace_id}: the entrypoint returned {failure.get('detail')}, which is not a candidate sequence",
                    _OUTPUT_SHAPE_FIX, "return",
                )
                for failure in trace.capture_failures if failure.get("code") == "final_output_shape_unsupported"
            )
        failures.extend(problems)
        captured += not problems
    if not successful:
        failures.append(_failure("no_successful_traces", "no trace finished with status OK", "run one declared scenario to completion, then verify again"))
    evidence = {"ok_traces": len(successful), "captured": captured, "with_return_boundary": with_return_boundary}
    scope = f"{len(successful)} successful traces; the final boundary must be an observed operator with recorded outputs" + (
        " (the plan declares an operator output as the boundary)" if operator_boundary else ""
    )
    return _capability(_status(captured, len(successful)), evidence, scope, failures)


def _judgment_mapping(manifest: IntegrationManifest, traces: Sequence[RetrievalTrace], project_root) -> Dict[str, Any]:
    from retrieval_observatory.datasets.custom import _load_qrels

    observed = {c.doc_id for trace in traces for span in trace.spans for c in (*span.inputs, *span.outputs) if c.doc_id}
    evidence = {"judged_queries": 0, "judged_entities": 0, "observed_entities": len(observed), "matched_entities": 0, "matched_queries": 0}
    fix = "set plan.judgments.qrels to the labels file; candidate movement inspection works without labels"
    declared = (manifest.judgments or {}).get("qrels")
    path = Path(str(declared)) if declared else None
    if path is not None and not path.is_absolute():
        path = Path(project_root) / path if project_root is not None else None

    def unavailable(detail: str) -> Dict[str, Any]:
        scope = f"{len(observed)} observed candidate ids; no judgments to map them against"
        return _capability("unavailable", evidence, scope, [_failure("judgments_unavailable", detail, fix)])

    if not declared:
        return unavailable("plan.judgments.qrels is not set")
    if path is None:
        return unavailable(f"declared qrels {declared!r} is relative and no project root was given")
    if not path.is_file():
        return unavailable(f"declared qrels file {path} does not exist")
    try:
        qrels = _load_qrels(str(path))
    except Exception as exc:
        return unavailable(f"could not load {path}: {exc}")
    judged = {doc_id for relevant in qrels.values() for doc_id in relevant}
    matched = judged & observed
    evidence.update(
        judged_queries=len(qrels), judged_entities=len(judged), matched_entities=len(matched),
        matched_queries=sum(1 for trace in traces if trace.query_id in qrels),
    )
    failures: List[Dict[str, Any]] = []
    if not matched:
        failures.append(_failure(
            "judgment_ids_unmatched",
            f"0 of {len(judged)} judged document ids appear among observed candidates: candidate id field or namespace mismatch",
            "map candidate_mapping.doc_id (and identity.namespace) to the id space the qrels use",
        ))
    scope = f"{len(judged)} judged ids from {path} against {len(observed)} observed candidate ids"
    return _capability("ready" if matched else "partial", evidence, scope, failures)


def _declared_route_coverage(manifest: IntegrationManifest, traces: Sequence[RetrievalTrace]) -> Dict[str, Any]:
    with_evidence = [trace for trace in traces if _trace_has_evidence(trace)]
    fired = {trace.trace_id: {_operator_id(span) for span in trace.spans if span.status == "FIRED"} for trace in with_evidence}
    routes = {
        trace.trace_id: {
            str(span.gate_values["selected_route"])
            for span in trace.spans if span.op_type == "GATE" and span.gate_values.get("selected_route") is not None
        }
        for trace in traces
    }
    satisfied_by: Dict[str, str] = {}
    missing_by_scenario: Dict[str, List[str]] = {}
    failures: List[Dict[str, Any]] = []
    for scenario in manifest.scenarios:
        expected = set(scenario.expected_operator_ids)
        on_route = [trace for trace in with_evidence if scenario.route is None or scenario.route in routes[trace.trace_id]]
        qualifying = [trace for trace in on_route if expected <= fired[trace.trace_id]]
        chosen = next((trace for trace in qualifying if trace.query_text == scenario.query_text), qualifying[0] if qualifying else None)
        if chosen is not None:
            satisfied_by[scenario.scenario_id] = chosen.trace_id
            continue
        pool = on_route or with_evidence
        missing = sorted(min((expected - fired[trace.trace_id] for trace in pool), key=len, default=expected))
        missing_by_scenario[scenario.scenario_id] = missing
        what = f"no evidence-bearing trace fired {missing} together" if missing else f"no evidence-bearing trace fired all of {sorted(expected)}"
        if scenario.route is not None:
            what += f" with a GATE selecting route {scenario.route!r}"
        failures.append(_failure(
            "scenario_unobserved",
            f"scenario '{scenario.scenario_id}' (query_text={scenario.query_text!r}, route={scenario.route!r}) was not observed: {what}",
            "run the scenario's command, then verify again" + (f": {scenario.command}" if scenario.command else ""),
        ))
    if not manifest.scenarios:
        failures.append(_failure(
            "no_scenarios_declared", "the manifest declares no verification scenarios",
            "declare one scenario per route with its query_text, expected operators and command",
        ))
    evidence = {
        "declared_scenarios": len(manifest.scenarios),
        "observed_scenarios": len(satisfied_by),
        "unobserved": [scenario.scenario_id for scenario in manifest.scenarios if scenario.scenario_id not in satisfied_by],
        "missing_by_scenario": missing_by_scenario,
        "observed_routes": sorted({route for seen in routes.values() for route in seen}),
        "satisfied_by": satisfied_by,
    }
    scope = (
        f"{len(traces)} traces; {len(satisfied_by)} of {len(manifest.scenarios)} declared scenarios observed; "
        "coverage is of declared scenarios only"
    )
    return _capability(_status(len(satisfied_by), len(manifest.scenarios)), evidence, scope, failures)


def _cross_run_entity_alignment(traces: Sequence[RetrievalTrace]) -> Dict[str, Any]:
    has_candidates = any(c.doc_id for trace in traces for span in trace.spans for c in (*span.inputs, *span.outputs))
    groups: Dict[str, List[RetrievalTrace]] = {}
    for trace in traces:
        if trace.query_text:
            groups.setdefault(trace.query_text, []).append(trace)
    repeated = {text: group for text, group in groups.items() if len(group) >= 2}
    consistent = inconsistent = 0
    unstable: Dict[str, str] = {}
    for text, group in repeated.items():
        ids_by_op: Dict[str, List[List[str]]] = {}
        for trace in group:
            for span in trace.spans:
                if span.status == "FIRED" and span.output_capture == "recorded":
                    ids_by_op.setdefault(span.op_id, []).append([c.doc_id for c in span.outputs])
        for op_id, observed in ids_by_op.items():
            if len(observed) < 2:
                continue
            if all(ids == observed[0] for ids in observed):
                consistent += 1
            else:
                inconsistent += 1
                unstable.setdefault(op_id, text)
    failures = [
        _failure("unstable_candidate_ids", f"{op_id} returned different ids for identical query {text!r}", "use stable document ids, not per-call ids", op_id)
        for op_id, text in sorted(unstable.items())
    ]
    if not repeated:
        failures.append(_failure(
            "alignment_unverified", "no query text was observed twice, so candidate ids could not be compared across runs",
            "run one scenario twice, e.g. the representative-repeat scenario",
        ))
    if not has_candidates:
        failures.append(_failure("no_candidates", "no candidate ids were observed", "capture operator outputs, then run one scenario twice"))
        status = "unavailable"
    elif repeated and not inconsistent:
        status = "ready"
    else:
        status = "partial"
    evidence = {"repeated_queries": len(repeated), "consistent": consistent, "inconsistent": inconsistent}
    scope = f"{len(traces)} traces; {len(repeated)} query texts observed more than once; ordered candidate ids compared per operator across their traces"
    return _capability(status, evidence, scope, failures)


def verify_observed_traces(
    manifest: IntegrationManifest, traces: Sequence[RetrievalTrace], *, db_path: str | None = None, project_root=None
) -> IntegrationResult:
    """Report every capability of master plan section 3.5 from the observed traces.

    Matching the agent-authored manifest is only a structural check: graph invariants, actual
    boundary snapshots, candidate and query identity and the final boundary are verified from the
    traces themselves, and scenario coverage is coverage of declared scenarios only.
    """
    traces = list(traces)
    # With no traces at all, every declared operator is trivially "missing" and every declared
    # edge trivially absent. Reporting them that way names a symptom and hides the cause, which
    # is that the instrumented code never ran — usually an import error or an unexercised path.
    no_traces = (
        f"No traces found for service_id={manifest.service_id!r} pipeline_id={manifest.pipeline_id!r} "
        f"in {db_path or 'the configured database'}: the instrumented code did not run, or it persisted to a "
        "different database. Check that the patched modules import cleanly, that the entrypoint was called "
        "(its trace_scope decorator records the trace), and that verify uses the same --db."
    )
    builders = {
        "topology_observed": lambda: _topology_observed(manifest, traces, no_traces),
        "actual_input_output_capture": lambda: _actual_input_output_capture(traces),
        "candidate_identity": lambda: _candidate_identity(traces),
        "query_identity": lambda: _query_identity(traces),
        "final_output_capture": lambda: _final_output_capture(manifest, traces),
        "judgment_mapping": lambda: _judgment_mapping(manifest, traces, project_root),
        "declared_route_coverage": lambda: _declared_route_coverage(manifest, traces),
        "cross_run_entity_alignment": lambda: _cross_run_entity_alignment(traces),
    }
    capabilities = {name: builders[name]() for name in CAPABILITY_NAMES}
    failed_core = [name for name in _CORE_CAPABILITIES if capabilities[name]["status"] == "unavailable"]
    if not traces:
        status, errors = "failed", (no_traces,)
    elif failed_core:
        status = "failed"
        errors = tuple(f"{name}/{item['code']}: {item['detail']}" for name in failed_core for item in capabilities[name]["failures"])
    elif all(capability["status"] == "ready" for capability in capabilities.values()):
        status, errors = "ready", ()
    else:
        status, errors = "partial", ()
    checks = tuple(
        IntegrationCheck(
            name, _CHECK_STATUS[capability["status"]], "measured", "2.0", len(traces),
            fix=next((item["fix"] for item in capability["failures"]), None) if capability["status"] != "ready" else None,
        )
        for name, capability in capabilities.items()
    )
    observed = sorted({_operator_id(span) for trace in traces for span in trace.spans if not _is_return_boundary(span)})
    signatures = Counter(tuple(sorted((span.op_id, tuple(span.parent_ids)) for span in trace.spans)) for trace in traces)
    variants = tuple({"signature": repr(signature), "count": count} for signature, count in signatures.items())
    return IntegrationResult(
        "verify", status, checks=checks, capabilities=capabilities,
        observed_operator_ids=tuple(observed), topology_variants=variants, errors=errors,
    )


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


async def verify_project(root, store, policy=None, *, db_path: str | None = None) -> IntegrationResult:
    from retrieval_observatory.integrations.manifest import load_manifest
    from retrieval_observatory.store.base import TraceQuery
    if not (Path(root) / "retobs" / "integration.yaml").is_file():
        return IntegrationResult("verify", "failed", errors=("no retobs/integration.yaml: run apply first",))
    manifest = load_manifest(Path(root))
    traces = await store.list_traces(TraceQuery(service_id=manifest.service_id, pipeline_id=manifest.pipeline_id))
    result = verify_observed_traces(
        manifest, traces, db_path=db_path or getattr(store, "db_path", None), project_root=Path(root)
    )
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
