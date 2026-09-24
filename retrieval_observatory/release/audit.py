"""One release audit artifact shared by the SDK, CLI, MCP, dashboard and CI.

``build_release_audit`` evaluates a baseline/candidate pair under an optional release policy and
returns the comparison ``ReportModel`` together with the audit dictionary (schema ``audit-1``).
``render_audit_html`` renders that dictionary as a standalone page that needs no server.
"""
from __future__ import annotations

import html
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict
from urllib.parse import quote

if TYPE_CHECKING:
    from retrieval_observatory.release.assessment import EvidenceAssessment
    from retrieval_observatory.release.policy import ReleasePolicy, ReleasePolicyV3
    from retrieval_observatory.release.resolution import RunEvidence
    from retrieval_observatory.sdk.report import ReportModel
    from retrieval_observatory.store.base import BaseStore


AUDIT_SCHEMA_VERSION = "audit-1"
#: Process exit status per decision; tool errors use 70 and usage errors 64 (see the CLI).
EXIT_CODES = {"PASS": 0, "FAIL": 1, "BLOCK": 2, "HOLD": 3}
DASHBOARD_BASE_URL = "http://127.0.0.1:4000"
#: encodeURIComponent leaves these unescaped; quote() must match it byte for byte.
_URI_COMPONENT_SAFE = "!*'()"

_CONCLUSIONS = {
    "PASS": "The recorded evidence proves non-inferiority for every declared policy guard.",
    "HOLD": "The recorded evidence is valid but does not prove pass or fail for every declared guard.",
    "BLOCK": "Required promotion evidence is missing or invalid; metric deltas are not decision-bearing.",
    "FAIL": "Valid promotion evidence proves at least one policy-critical regression beyond its budget.",
}
_EVALUATION_FIELDS = ("unit", "boundary", "k", "relevance_threshold", "comparison_scope")
_STATISTICS_FIELDS = ("confidence_level", "familywise_alpha", "resamples", "seed")


def _resolve_release_policy(
    policy: str | Path | ReleasePolicy | ReleasePolicyV3 | None,
) -> tuple[ReleasePolicy | ReleasePolicyV3 | None, str | None]:
    from retrieval_observatory.release.policy import ReleasePolicy, ReleasePolicyV3, load_release_policy

    if policy is None:
        return None, None
    if isinstance(policy, (ReleasePolicy, ReleasePolicyV3)):
        return policy, None
    policy_path = Path(policy)
    return load_release_policy(policy_path), str(policy_path)


async def _run_evidence(
    store: BaseStore,
    run_id: str,
    manifest: Dict[str, Any],
    rows: list[Dict[str, Any]],
    *,
    load_traces: bool,
) -> RunEvidence:
    from retrieval_observatory.release.resolution import (
        RunEvidence,
        operator_depths_from_traces,
        operator_ids_from_traces,
    )
    from retrieval_observatory.store.base import TraceQuery

    depths = operator_ids = None
    if load_traces:
        traces = await store.list_traces(TraceQuery(run_id=run_id))
        depths, operator_ids = operator_depths_from_traces(traces), operator_ids_from_traces(traces)
    return RunEvidence(run_id=run_id, manifest=manifest, metric_rows=rows, operator_depths=depths, operator_ids=operator_ids)


async def _expected_query_ids(*runs: tuple[BaseStore, str]) -> set[str] | None:
    """Every query either run attempted, bounded to the ones the metrics engine could score.

    ``run_queries`` lists every attempted query; the engine writes rows (including the failure
    indicators) only for queries whose qrels hold a relevant document, so an unlabeled query is
    not a lost pair. None when no run recorded its queries: the rows then define the universe.
    """
    attempted = {str(row["query_id"]) for store, run_id in runs for row in await store.get_run_queries(run_id)}
    if not attempted:
        return None
    labeled: set[str] = set()
    for store, run_id in runs:
        for query_id, judgments in (await store.get_qrels(run_id) or {}).items():
            positive = any(grade > 0 for grade in judgments.values()) if isinstance(judgments, dict) else bool(judgments)
            if positive:
                labeled.add(str(query_id))
    return attempted & labeled if labeled else attempted


def _with_resolution_findings(assessment: EvidenceAssessment, findings: tuple[Dict[str, Any], ...]) -> EvidenceAssessment:
    """Add selector-resolution findings to the aggregate scope so an unbound check BLOCKs the decision."""
    from retrieval_observatory.release.readiness import ClaimReadiness, EvidenceFinding

    scope = "aggregate_or_slice_evaluation"
    merged = list(assessment.readiness[scope].findings) + [
        EvidenceFinding(
            code=finding["code"],
            scope=scope,
            status=finding["status"],
            observed={"check_id": finding["check_id"]},
            required="one stored metric key per run for every declared check",
            detail=finding["detail"],
            next_action=finding["next_action"],
        )
        for finding in findings
    ]
    # Same precedence as assessment._readiness.
    status = "BLOCK" if any(item.status == "BLOCK" for item in merged) else "HOLD" if merged else "READY"
    readiness = {**assessment.readiness, scope: ClaimReadiness(scope=scope, status=status, findings=merged)}
    return assessment.model_copy(update={"readiness": readiness})


def investigate_link(*, db_id: str | None, run_id: str, pipeline_id: str | None, query_id: str, compare: str) -> str:
    """The dashboard's Investigate link (``investigateLink`` in ``focusedRoutes.ts``), encoded alike."""
    pairs = [("db", db_id), ("run", run_id), ("pipeline", pipeline_id), ("view", "queries"), ("query", query_id), ("compare", compare)]
    return "#/investigate?" + "&".join(f"{key}={quote(str(value), safe=_URI_COMPONENT_SAFE)}" for key, value in pairs if value)


async def build_release_audit(
    baseline_store: BaseStore,
    candidate_store: BaseStore,
    baseline_run_id: str,
    candidate_run_id: str,
    *,
    policy: str | Path | ReleasePolicy | ReleasePolicyV3 | None = None,
    policy_source: str | None = None,
    baseline_db_id: str | None = None,
    candidate_db_id: str | None = None,
    db_path: str | None = None,
) -> tuple[ReportModel, Dict[str, Any]]:
    """Build the validity-gated comparison report and its audit for CLI, SDK, MCP, CI and the dashboard."""
    from retrieval_observatory.metrics.comparison import (
        _scores_for,
        collapse_latency_render_keys,
        compare_paired_metrics,
        comparison_validity,
        parse_metric_key,
    )
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.release.assessment import assess_evidence
    from retrieval_observatory.release.decision import decide_release, decide_release_v3
    from retrieval_observatory.release.policy import ReleasePolicyV3
    from retrieval_observatory.release.resolution import (
        adjusted_confidence,
        convert_v2_policy,
        evidence_only_v2_policy,
        family_size,
        resolve_policy,
        selectors_need_traces,
    )
    from retrieval_observatory.release.slices import evaluate_declared_slices, evaluate_resolved_slices
    from retrieval_observatory.release.statistics import (
        adjusted_confidence_level,
        evaluate_execution,
        evaluate_metric_guards,
        evaluate_resolved_checks,
    )
    from retrieval_observatory.sdk.report import ReportModel

    run_records: list[Dict[str, Any]] = []  # baseline, candidate (the same run id may live in two databases)
    missing = []
    for store, run_id in ((baseline_store, baseline_run_id), (candidate_store, candidate_run_id)):
        record = next((item for item in await store.list_runs() if item["run_id"] == run_id), None)
        if record is None:
            missing.append(run_id)
        run_records.append(record or {})
    if missing:
        raise ValueError(f"Run not found: {', '.join(missing)}")

    baseline_manifest = await baseline_store.get_run_manifest(baseline_run_id)
    candidate_manifest = await candidate_store.get_run_manifest(candidate_run_id)
    validity = comparison_validity([baseline_manifest, candidate_manifest])
    baseline_rows = await baseline_store.get_metrics(baseline_run_id)
    candidate_rows = await candidate_store.get_metrics(candidate_run_id)
    resolved_policy, loaded_source = _resolve_release_policy(policy)
    policy_source = policy_source or loaded_source
    is_v3 = isinstance(resolved_policy, ReleasePolicyV3)

    # Bind the policy's selectors to the keys both runs record. A v3 policy is evaluated from the
    # resolved structure, each run at its own key; a v2 policy runs unchanged and carries its
    # explicit v3 conversion as information.
    resolution = conversion = None
    assessed_policy = resolved_policy  # the evidence/intervention view assess_evidence consumes
    if resolved_policy is not None:
        load_traces = selectors_need_traces(resolved_policy)
        evidence = (
            await _run_evidence(baseline_store, baseline_run_id, baseline_manifest or {}, baseline_rows, load_traces=load_traces),
            await _run_evidence(candidate_store, candidate_run_id, candidate_manifest or {}, candidate_rows, load_traces=load_traces),
        )
        resolution = resolve_policy(resolved_policy, *evidence)
        if is_v3:
            assessed_policy = evidence_only_v2_policy(resolution)
        else:
            conversion = convert_v2_policy(resolved_policy, *evidence)

    assessment = assess_evidence(
        assessed_policy,
        baseline_manifest or {},
        candidate_manifest or {},
    )
    expected_query_ids = await _expected_query_ids((baseline_store, baseline_run_id), (candidate_store, candidate_run_id))
    if resolution is not None and is_v3:
        assessment = _with_resolution_findings(assessment, resolution.findings)
        aggregate_guards = evaluate_resolved_checks(resolution, *evidence, expected_query_ids=expected_query_ids)
        slice_results = evaluate_resolved_slices(resolution, *evidence, expected_query_ids=expected_query_ids)
        operational = evaluate_execution(resolution, *evidence)
        decision = decide_release_v3(resolution, assessment, aggregate_guards, slice_results, operational)
    else:
        aggregate_guards = (
            evaluate_metric_guards(resolved_policy, baseline_rows, candidate_rows)
            if resolved_policy is not None
            else []
        )
        slice_results = (
            evaluate_declared_slices(resolved_policy, baseline_rows, candidate_rows)
            if resolved_policy is not None
            else []
        )
        decision = decide_release(resolved_policy, assessment, aggregate_guards, slice_results)
    engine = MetricsEngine()
    baseline_aggregate = await engine.aggregate(baseline_run_id, baseline_store)
    candidate_aggregate = await engine.aggregate(candidate_run_id, candidate_store)
    keys = collapse_latency_render_keys(sorted(set(baseline_aggregate) | set(candidate_aggregate)))
    results = compare_paired_metrics(baseline_rows, candidate_rows, keys, validity)

    regressions = [result for result in results.values() if result.decision == "candidate_worse"]
    improvements = [result for result in results.values() if result.decision == "candidate_better"]

    selected = (regressions or improvements or list(results.values()))[:1]
    affected_queries: list[Dict[str, Any]] = []
    query_diff_metric = None
    if validity.decision_allowed and selected:
        query_diff_metric = selected[0].metric
        pipeline_id, stage_index, metric_name, k, branch_id = parse_metric_key(query_diff_metric)
        baseline_scores = _scores_for(baseline_rows, pipeline_id, stage_index, metric_name, k, branch_id=branch_id)
        candidate_scores = _scores_for(candidate_rows, pipeline_id, stage_index, metric_name, k, branch_id=branch_id)
        for query_id in set(baseline_scores) & set(candidate_scores):
            encoded_query_id = quote(str(query_id), safe="")
            encoded_baseline = quote(str(baseline_run_id), safe="")
            encoded_candidate = quote(str(candidate_run_id), safe="")
            affected_queries.append({
                "query_id": query_id,
                "baseline": baseline_scores[query_id],
                "candidate": candidate_scores[query_id],
                "delta": candidate_scores[query_id] - baseline_scores[query_id],
                "investigation_route": f"#/runs/{encoded_candidate}/queries/{encoded_query_id}",
                "diff_route": (
                    f"#/runs/{encoded_candidate}/queries/{encoded_query_id}/diff?against={encoded_baseline}"
                ),
            })
        affected_queries.sort(key=lambda row: (-abs(row["delta"]), str(row["query_id"])))
        affected_queries = affected_queries[:20]

    results_dict = {key: value.to_dict() for key, value in results.items()}
    validity_dict = validity.to_dict()
    decision_payload = {
        "schema_version": 1,
        **decision.model_dump(mode="json"),
        "provenance_assessment": assessment.provenance.model_dump(mode="json"),
        "policy_resolution": resolution.to_dict() if resolution is not None else None,
        "investigation": {
            "affected_query_ids": [row["query_id"] for row in affected_queries],
            "query_route_template": f"#/runs/{quote(str(candidate_run_id), safe='')}/queries/{{query_id}}",
            "diff_route_template": (
                f"#/runs/{quote(str(candidate_run_id), safe='')}/queries/{{query_id}}/diff?against="
                f"{quote(str(baseline_run_id), safe='')}"
                + (
                    f"&policy_path={quote(policy_source, safe='')}"
                    if policy_source
                    else ""
                )
            ),
        },
    }
    if conversion is not None:
        decision_payload["policy_conversion"] = conversion.to_dict()
    policy_argument = (
        f" --policy {policy_source}"
        if policy_source is not None
        else " --policy <policy-path>"
        if resolved_policy is not None
        else ""
    )

    # ------------------------------------------------------------------ the audit artifact
    def _check_entry(check) -> dict:
        return {
            **check.model_dump(mode="json"),
            "id": getattr(check, "check_id", None) or check.metric,
            "tolerance": check.max_regression,
            "boundary": -check.max_regression if check.direction == "higher_is_better" else check.max_regression,
        }

    checks = [_check_entry(check) for check in decision.aggregate_guards]
    slices = [
        {**item.model_dump(mode="json"), "guards": [_check_entry(guard) for guard in item.guards]}
        for item in decision.slices
    ]
    evaluation_source = (resolution.evaluation if resolution is not None else None) or (candidate_manifest or {}).get("evaluation") or {}
    statistics: Dict[str, Any] = {name: None for name in (*_STATISTICS_FIELDS, "interval_method", "family_size", "adjusted_confidence_level")}
    if resolution is not None:
        statistics.update({name: resolution.statistics.get(name) for name in _STATISTICS_FIELDS})
        statistics["interval_method"] = checks[0]["interval_method"] if checks else "paired_percentile_bootstrap"
        if is_v3:
            statistics["family_size"] = family_size(resolved_policy)
            statistics["adjusted_confidence_level"] = adjusted_confidence(resolved_policy)
        else:
            statistics["family_size"] = len(resolved_policy.metrics) * (1 + len(resolved_policy.slices))
            statistics["adjusted_confidence_level"] = adjusted_confidence_level(resolved_policy)
    investigation_pipeline = parse_metric_key(query_diff_metric)[0] if query_diff_metric else None
    promotion = assessment.readiness["promotion"]
    audit = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": {"retrieval_observatory": _package_version(), "python": platform.python_version()},
        "decision": {
            "status": decision.status,
            "reasons": list(decision.reasons),
            "next_action": decision.next_action,
            "exit_code": EXIT_CODES[decision.status],
        },
        "sources": {
            "baseline": _source_run(baseline_db_id, baseline_run_id, run_records[0], baseline_manifest),
            "candidate": _source_run(candidate_db_id, candidate_run_id, run_records[1], candidate_manifest),
        },
        "policy": {
            "configured": decision.policy.configured,
            "id": decision.policy.id,
            "schema_version": decision.policy.schema_version,
            "digest": decision.policy.digest,
            "source": policy_source,
            "resolution": resolution.to_dict() if resolution is not None else None,
            "conversion": conversion.to_dict() if conversion is not None else None,
        },
        "evaluation": {name: evaluation_source.get(name) for name in _EVALUATION_FIELDS},
        "compatibility": {
            "status": promotion.status,
            "findings": [finding.model_dump(mode="json") for finding in promotion.findings],
            "provenance": assessment.provenance.model_dump(mode="json"),
            "validity": validity_dict,
        },
        "readiness": decision_payload["readiness"],
        "coverage": {
            "expected_query_count": len(expected_query_ids) if expected_query_ids is not None else None,
            "min_pair_coverage": (
                checks[0]["min_pair_coverage"]
                if checks
                else resolution.statistics.get("min_pair_coverage") if resolution is not None else None
            ),
            "per_check": {
                check["id"]: {
                    "attempted_n": check["attempted_n"],
                    "paired_n": check["paired_n"],
                    "pair_coverage": check["pair_coverage"],
                }
                for check in checks
            },
        },
        "checks": checks,
        "slices": slices,
        "operational": decision_payload["operational"],
        "statistics": statistics,
        "investigation": {
            "scope": {
                "db_id": candidate_db_id,
                "baseline_run_id": baseline_run_id,
                "candidate_run_id": candidate_run_id,
                "pipeline_id": investigation_pipeline,
            },
            "changed_queries": [
                {
                    "query_id": row["query_id"],
                    "metric": query_diff_metric,
                    "baseline": row["baseline"],
                    "candidate": row["candidate"],
                    "delta": row["delta"],
                    "link": investigate_link(
                        db_id=candidate_db_id,
                        run_id=candidate_run_id,
                        pipeline_id=investigation_pipeline,
                        query_id=str(row["query_id"]),
                        compare=baseline_run_id,
                    ),
                }
                for row in affected_queries
            ],
            "dashboard_base_url": DASHBOARD_BASE_URL,
            "requires_local_dashboard": True,
        },
        "metrics": results_dict,
    }
    # One JSON-native shape for every transport (tuples become lists; NaN/inf become null).
    audit = json.loads(json.dumps(audit, default=str), parse_constant=lambda _constant: None)

    report = ReportModel(
        kind="comparison",
        run_id=f"{baseline_run_id}..{candidate_run_id}",
        title="Run Comparison",
        verdict=decision.status,
        conclusion=_CONCLUSIONS[decision.status],
        evidence_health=promotion.status.lower(),
        evidence_reasons=decision.reasons,
        metrics=results_dict,
        dominant_issue={"label": regressions[0].metric, "query_count": len(affected_queries)} if regressions else None,
        affected_queries=affected_queries,
        provenance={"baseline_manifest": baseline_manifest, "candidate_manifest": candidate_manifest},
        next_action=decision.next_action,
        reproduce=(
            f"retobs compare {baseline_run_id} {candidate_run_id} --db {db_path or '<db-path>'}{policy_argument}"
        ),
        dashboard_url=f"{DASHBOARD_BASE_URL}/#/compare",
        comparison={
            "baseline_run_id": baseline_run_id,
            "candidate_run_id": candidate_run_id,
            "effect_orientation": "candidate_minus_baseline",
            "validity": validity_dict,
            "results": results_dict,
            "query_diff_metric": query_diff_metric,
            "release_provenance": {
                "baseline": {
                    "run_id": baseline_run_id,
                    "manifest_schema_version": (baseline_manifest or {}).get("schema_version"),
                    "release_identity": (baseline_manifest or {}).get("release_identity"),
                },
                "candidate": {
                    "run_id": candidate_run_id,
                    "manifest_schema_version": (candidate_manifest or {}).get("schema_version"),
                    "release_identity": (candidate_manifest or {}).get("release_identity"),
                },
            },
            "release_decision": decision_payload,
        },
        audit=audit,
    )
    return report, audit


def _package_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("retrieval-observatory")
    except PackageNotFoundError:
        return "0+unknown"


def _source_run(
    db_id: str | None,
    run_id: str,
    record: Dict[str, Any],
    manifest: Dict[str, Any] | None,
) -> Dict[str, Any]:
    manifest = manifest or {}
    dataset = manifest.get("dataset") or {}
    return {
        "db_id": db_id,
        "run_id": run_id,
        "experiment_name": record.get("experiment_name"),
        "manifest_schema_version": manifest.get("schema_version"),
        "dataset": {
            key: dataset.get(key)
            for key in ("name", "query_hash", "corpus_hash", "qrel_hash")
            if key != "name" or "name" in dataset
        },
        "judgment_digest": manifest.get("judgment_digest") or dataset.get("judgment_digest"),
        "release_identity": manifest.get("release_identity"),
        "evaluation": manifest.get("evaluation"),
        "counts": manifest.get("counts"),
    }


# --------------------------------------------------------------------------- standalone HTML


_CSS = """
body{font:15px/1.5 system-ui,sans-serif;max-width:1040px;margin:2rem auto;padding:0 1rem;color:#172033;background:#fff}
h1{font-size:1.4rem;margin:0 0 .25rem}h2{font-size:1.1rem;margin:2rem 0 .5rem;border-bottom:1px solid #d7dde8;padding-bottom:.25rem}
table{border-collapse:collapse;width:100%;font-size:13px;margin:.5rem 0}th,td{border:1px solid #d7dde8;padding:.35rem .5rem;text-align:left;vertical-align:top}
th{background:#f5f7fa}code,pre{font-family:ui-monospace,monospace;font-size:12px}
pre{white-space:pre-wrap;word-break:break-all;background:#f5f7fa;border:1px solid #d7dde8;border-radius:6px;padding:.75rem}
.banner{border-radius:8px;padding:1rem 1.25rem;margin:1rem 0;border:2px solid}
.banner .status{font-size:1.6rem;font-weight:700;letter-spacing:.04em}
.PASS{border-color:#1a7f37;background:#eaf7ee}.FAIL{border-color:#c62828;background:#fdecec}
.BLOCK{border-color:#6e40c9;background:#f3eefc}.HOLD{border-color:#b26a00;background:#fff6e5}
.note{color:#5a6475;font-size:13px}details{margin-top:1rem}summary{cursor:pointer;font-weight:600}
"""


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return '<p class="note">None.</p>'
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(_cell(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _interval(item: Dict[str, Any]) -> str | None:
    if item.get("ci_low") is None or item.get("ci_high") is None:
        return None
    return f"[{item['ci_low']:.4g}, {item['ci_high']:.4g}]"


def render_audit_html(audit: Dict[str, Any]) -> str:
    """A standalone page (inline CSS, no scripts, no external resources) for one release audit."""
    decision = audit.get("decision") or {}
    status = str(decision.get("status", "HOLD"))
    sources = audit.get("sources") or {}
    policy = audit.get("policy") or {}
    compatibility = audit.get("compatibility") or {}
    provenance = compatibility.get("provenance") or {}
    statistics = audit.get("statistics") or {}
    investigation = audit.get("investigation") or {}
    base_url = investigation.get("dashboard_base_url") or DASHBOARD_BASE_URL
    esc = html.escape
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>Release audit — {esc(status)}</title><style>{_CSS}</style></head><body>",
        "<h1>Release audit</h1>",
        f'<p class="note">Schema {esc(str(audit.get("schema_version")))} · generated {esc(str(audit.get("generated_at")))} · '
        f'retrieval-observatory {esc(str((audit.get("tool") or {}).get("retrieval_observatory")))}</p>',
        f'<section class="banner {esc(status)}" aria-label="Decision"><div class="status">{esc(status)}</div>',
        f"<p>Exit code {esc(str(decision.get('exit_code')))}. {esc(str(decision.get('next_action', '')))}</p><ul>",
        "".join(f"<li>{esc(str(reason))}</li>" for reason in decision.get("reasons") or []),
        "</ul></section>",
        "<h2>Sources</h2>",
        _table(
            ["Role", "Database", "Run", "Experiment", "Dataset", "Judgment digest", "Counts"],
            [
                [
                    role,
                    source.get("db_id"),
                    source.get("run_id"),
                    source.get("experiment_name"),
                    source.get("dataset"),
                    source.get("judgment_digest"),
                    source.get("counts"),
                ]
                for role, source in ((role, sources.get(role) or {}) for role in ("baseline", "candidate"))
            ],
        ),
        "<h2>Evaluation and policy</h2>",
        _table(["Field", "Value"], [[key, value] for key, value in (audit.get("evaluation") or {}).items()]),
        _table(
            ["Policy", "Schema", "Digest", "Source"],
            [[policy.get("id") or "not configured", policy.get("schema_version"), policy.get("digest"), policy.get("source")]],
        ),
        "<h2>Compatibility</h2>",
        f"<p>Promotion evidence: <strong>{esc(str(compatibility.get('status')))}</strong>; "
        f"comparison validity: <strong>{esc(str((compatibility.get('validity') or {}).get('outcome')))}</strong>.</p>",
        _table(
            ["Field", "Baseline", "Candidate", "Classification"],
            [
                [item.get("field"), item.get("baseline"), item.get("candidate"), item.get("classification")]
                for group in ("invariants", "interventions", "consistency")
                for item in provenance.get(group) or []
            ],
        ),
        _table(
            ["Finding", "Status", "Detail", "Next action"],
            [
                [finding.get("code"), finding.get("status"), finding.get("detail"), finding.get("next_action")]
                for finding in compatibility.get("findings") or []
            ],
        ),
        "<h2>Checks</h2>",
        _table(
            ["Check", "Target", "Effect", "Interval", "Tolerance", "Status", "Paired / attempted"],
            [
                [
                    check.get("id"),
                    check.get("target") or check.get("metric"),
                    check.get("effect"),
                    _interval(check),
                    check.get("tolerance"),
                    check.get("status"),
                    f"{check.get('paired_n')} / {check.get('attempted_n')}",
                ]
                for check in audit.get("checks") or []
            ],
        ),
        "<h2>Slices</h2>",
        _table(
            ["Slice", "Selector", "Status", "Paired n", "Label coverage", "Limitation"],
            [
                [item.get("id"), f"{item.get('field')}={_cell(item.get('value'))}", item.get("status"),
                 item.get("paired_n"), item.get("label_coverage"), item.get("sample_limitation")]
                for item in audit.get("slices") or []
            ],
        ),
        "<h2>Execution</h2>",
        _operational_html(audit.get("operational")),
        "<h2>Changed queries</h2>",
        '<p class="note">Links open the local dashboard (<code>retobs serve</code>) at '
        f"{esc(base_url)}; they need the local dashboard running on the same database.</p>",
        _changed_queries_html(investigation.get("changed_queries") or [], base_url),
        "<details><summary>Statistics</summary>",
        _table(
            ["Setting", "Value"],
            [
                ["confidence level", statistics.get("confidence_level")],
                ["adjusted confidence level", statistics.get("adjusted_confidence_level")],
                ["familywise alpha", statistics.get("familywise_alpha")],
                ["resamples", statistics.get("resamples")],
                ["seed", statistics.get("seed")],
                ["interval method", statistics.get("interval_method")],
                ["family size", statistics.get("family_size")],
            ],
        ),
        "</details>",
        "<details><summary>Machine-readable audit</summary>",
        f"<pre>{esc(json.dumps(audit, indent=2, sort_keys=True))}</pre></details>",
        "</body></html>\n",
    ]
    return "\n".join(parts)


def _operational_html(operational: Dict[str, Any] | None) -> str:
    if not operational:
        return '<p class="note">No execution accounting (no v3 policy).</p>'
    return _table(
        ["Status", "Code", "Max failure rate", "Baseline failure rate", "Candidate failure rate", "Detail"],
        [[
            operational.get("status"),
            operational.get("code"),
            operational.get("max_failure_rate"),
            (operational.get("baseline") or {}).get("failure_rate"),
            (operational.get("candidate") or {}).get("failure_rate"),
            operational.get("detail"),
        ]],
    )


def _changed_queries_html(rows: list[Dict[str, Any]], base_url: str) -> str:
    if not rows:
        return '<p class="note">None.</p>'
    body = "".join(
        "<tr>"
        + "".join(f"<td>{html.escape(_cell(row.get(key)))}</td>" for key in ("query_id", "metric", "baseline", "candidate", "delta"))
        + f'<td><a href="{html.escape(base_url + "/" + str(row.get("link", "")))}">Investigate</a></td></tr>'
        for row in rows
    )
    head = "".join(f"<th>{name}</th>" for name in ("Query", "Metric", "Baseline", "Candidate", "Delta", "Link"))
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
