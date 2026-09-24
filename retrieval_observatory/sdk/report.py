from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from retrieval_observatory.runner.execute import BenchmarkArtifacts

if TYPE_CHECKING:
    from retrieval_observatory.release.policy import ReleasePolicy, ReleasePolicyV3


@dataclass
class ReportModel:
    """Deterministic, renderer-neutral evaluation report contract."""

    kind: str
    run_id: str
    title: str
    verdict: str
    conclusion: str
    evidence_health: str
    evidence_reasons: list[str]
    metrics: Dict[str, Any]
    dominant_issue: Optional[Dict[str, Any]]
    affected_queries: list[Dict[str, Any]]
    provenance: Dict[str, Any]
    next_action: str
    reproduce: str
    dashboard_url: str
    schema_version: int = 1
    comparison: Optional[Dict[str, Any]] = None
    #: The release audit (schema ``audit-1``) of a comparison report; None for a run report.
    audit: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True, default=str) + "\n"

    def to_markdown(self) -> str:
        if self.kind == "comparison" and self.comparison:
            return self._comparison_markdown()
        lines = [
            f"# {self.title}",
            "",
            f"**Verdict:** `{self.verdict}`  ",
            f"**Evidence:** `{self.evidence_health}`  ",
            f"**Run:** `{self.run_id}`",
            "",
            self.conclusion,
            "",
        ]
        if self.evidence_reasons:
            lines.extend(["## Evidence health", ""])
            lines.extend(f"- {reason}" for reason in self.evidence_reasons)
            lines.append("")
        if self.dominant_issue:
            lines.extend([
                "## Dominant issue",
                "",
                f"`{self.dominant_issue['label']}` affects {self.dominant_issue['query_count']} evaluated query records.",
                "",
            ])
        lines.extend(["## Headline metrics", "", "| Metric | Mean | 95% CI |", "|---|---:|---:|"])
        # Insertion order is decision order (see _headline_metrics); sorting alphabetically
        # here would put latency above the quality numbers the reader came for.
        for key, value in self.metrics.items():
            if isinstance(value, dict):
                mean = _format_number(value.get("mean"))
                ci = f"{_format_number(value.get('ci_low'))} to {_format_number(value.get('ci_high'))}"
            else:
                mean, ci = _format_number(value), "unavailable"
            lines.append(f"| `{key}` | {mean} | {ci} |")
        lines.append("")
        if self.affected_queries:
            lines.extend(["## Affected queries", "", "| Query | Pipeline | Findings |", "|---|---|---|"])
            for query in self.affected_queries:
                findings = ", ".join(query.get("failure_labels", [])) or "none"
                lines.append(f"| `{query.get('query_id')}` | `{query.get('pipeline_id')}` | {findings} |")
            lines.append("")
        lines.extend([
            "## Next action",
            "",
            self.next_action,
            "",
            "## Reproduce and inspect",
            "",
            f"- `{self.reproduce}`",
            f"- Dashboard: {self.dashboard_url}",
            "",
        ])
        return "\n".join(lines)

    def _comparison_markdown(self) -> str:
        comparison = self.comparison or {}
        validity = comparison.get("validity", {})
        decision = comparison.get("release_decision", {})
        baseline = comparison.get("baseline_run_id", "unavailable")
        candidate = comparison.get("candidate_run_id", "unavailable")
        lines = [
            f"# {self.title}",
            "",
            f"**Verdict:** `{self.verdict}`  ",
            f"**Validity:** `{validity.get('outcome', 'unavailable')}`  ",
            f"**Baseline:** `{baseline}`  ",
            f"**Candidate:** `{candidate}`",
            "",
            self.conclusion,
            "",
        ]
        if decision:
            policy = decision.get("policy", {})
            lines.extend([
                "## Release decision",
                "",
                f"Artifact schema: `{decision.get('schema_version', 'unavailable')}`  ",
                f"**Status:** `{decision.get('status', 'HOLD')}`  ",
                f"**Policy:** `{policy.get('id') or 'not configured'}`  ",
                f"**Policy schema:** `{policy.get('schema_version') or 'unavailable'}`  ",
                f"**Policy digest:** `{policy.get('digest') or 'unavailable'}`",
                "",
                "### Claim readiness",
                "",
                "| Scope | Status | Findings |",
                "|---|---|---:|",
            ])
            for scope, readiness in decision.get("readiness", {}).items():
                lines.append(
                    f"| `{scope}` | `{readiness.get('status', 'BLOCK')}` | "
                    f"{len(readiness.get('findings', []))} |"
                )
            lines.append("")
            findings = [
                finding
                for readiness in decision.get("readiness", {}).values()
                for finding in readiness.get("findings", [])
            ]
            if findings:
                lines.extend(["### Evidence findings", ""])
                lines.extend(
                    f"- `{finding.get('scope')}/{finding.get('code')}` — {finding.get('detail')} "
                    f"Next: {finding.get('next_action')}"
                    for finding in findings
                )
                lines.append("")
            guards = decision.get("aggregate_guards", [])
            if guards:
                lines.extend([
                    "### Policy guard intervals",
                    "",
                    "| Metric | Status | Effect | Interval | Paired n | Adjusted confidence |",
                    "|---|---|---:|---:|---:|---:|",
                ])
                for guard in guards:
                    interval = (
                        f"{_format_number(guard.get('ci_low'))} to {_format_number(guard.get('ci_high'))}"
                    )
                    lines.append(
                        f"| `{guard.get('metric')}` | `{guard.get('status')}` | "
                        f"{_format_number(guard.get('effect'))} | {interval} | "
                        f"{guard.get('paired_n', 0)} | "
                        f"{_format_number(guard.get('adjusted_confidence_level'))} |"
                    )
                lines.append("")
            slices = decision.get("slices", [])
            if slices:
                lines.extend(["### Declared slices", ""])
                lines.extend(
                    f"- `{item.get('id')}` (`{item.get('field')}={item.get('value')!r}`): "
                    f"`{item.get('status')}`, paired n={item.get('paired_n', 0)}, "
                    f"label coverage={_format_number(item.get('label_coverage'))}"
                    for item in slices
                )
                lines.append("")
            if self.affected_queries:
                lines.extend(["### Investigation references", ""])
                lines.extend(
                    f"- `{item.get('query_id')}` — `{item.get('diff_route')}`"
                    for item in self.affected_queries
                )
                lines.append("")
            lines.extend([
                "## Next action",
                "",
                self.next_action,
                "",
                "## Reproduce and inspect",
                "",
                f"- `{self.reproduce}`",
                f"- Dashboard: {self.dashboard_url}",
                "",
            ])
        release_provenance = comparison.get("release_provenance", {})
        if release_provenance:
            lines.extend(["## Provenance", ""])
            for role in ("baseline", "candidate"):
                value = release_provenance.get(role, {})
                identity = json.dumps(value.get("release_identity") or {}, sort_keys=True)
                lines.append(
                    f"- **{role.title()}:** run `{value.get('run_id')}`, "
                    f"manifest schema `{value.get('manifest_schema_version') or 'unavailable'}`, "
                    f"release identity `{identity}`"
                )
            lines.append("")
        differences = validity.get("differences", [])
        if differences:
            lines.extend(["## Validity evidence", ""])
            lines.extend(f"- `{item.get('axis')}`: {item.get('detail')}" for item in differences)
            lines.append("")
        lines.extend([
            "## Paired results",
            "",
            "| Metric | Baseline | Candidate | Effect | q-value | n | Decision |",
            "|---|---:|---:|---:|---:|---:|---|",
        ])
        for key, result in sorted(comparison.get("results", {}).items()):
            lines.append(
                f"| `{key}` | {_format_number(result.get('baseline_mean'))} | "
                f"{_format_number(result.get('candidate_mean'))} | {_format_number(result.get('effect'))} | "
                f"{_format_number(result.get('q_value'))} | {result.get('paired_n', 0)} | "
                f"{result.get('decision', 'no_decision')} |"
            )
        lines.append("")
        if self.affected_queries:
            metric = comparison.get("query_diff_metric", "metric")
            lines.extend([
                "## Most affected queries",
                "",
                f"Candidate minus baseline for `{metric}`.",
                "",
                "| Query | Baseline | Candidate | Delta |",
                "|---|---:|---:|---:|",
            ])
            for query in self.affected_queries:
                lines.append(
                    f"| `{query.get('query_id')}` | {_format_number(query.get('baseline'))} | "
                    f"{_format_number(query.get('candidate'))} | {_format_number(query.get('delta'))} |"
                )
            lines.append("")
        return "\n".join(lines)

    def to_html(self) -> str:
        if self.audit:
            from retrieval_observatory.release.audit import render_audit_html

            return render_audit_html(self.audit)
        markdown = self.to_markdown()
        payload = self.to_json(indent=2)
        return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>
body{{font:15px/1.55 system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#172033}}
pre{{white-space:pre-wrap;background:#f5f7fa;border:1px solid #d7dde8;border-radius:8px;padding:1rem}}
details{{margin-top:2rem}}code{{font-family:ui-monospace,monospace}}
</style></head><body><pre>{markdown}</pre><details><summary>Machine-readable report</summary><pre>{payload}</pre></details></body></html>
""".format(
            title=html.escape(self.title),
            markdown=html.escape(markdown),
            payload=html.escape(payload),
        )

    def write(self, path: str | Path, *, format: Optional[str] = None) -> Path:
        target = Path(path)
        selected = (format or target.suffix.lstrip(".") or "json").lower()
        renderers = {
            "json": self.to_json,
            "md": self.to_markdown,
            "markdown": self.to_markdown,
            "html": self.to_html,
        }
        if selected not in renderers:
            raise ValueError("Report format must be json, markdown/md, or html.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(renderers[selected](), encoding="utf-8")
        return target


def _format_number(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, (int, float)):
        return f"{value:.4f}"
    return str(value)


#: Retrieval quality, best first. An allow-list rather than "anything that isn't latency":
#: the negative test let operational counters (dropout_count, failure_rate, timeout_rate)
#: pass as quality and fill the headline with zeros.
_QUALITY_METRICS = ("ndcg", "recall", "mrr", "map", "precision")
_QUALITY_ROWS_PER_PIPELINE = 3
_QUALITY_ROWS_TOTAL = 6
#: Metric-name prefixes `BenchmarkReport.assert_no_regression` treats as retrieval quality.
_REGRESSION_QUALITY_METRICS = ("ndcg", "recall", "mrr", "map")


def _headline_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Pick the few numbers that answer "did retrieval work, and what did it cost?".

    Quality is reported at each pipeline's terminal stage — the result the caller actually
    ships. Selecting on ``stage-1`` instead (as this once did) could never surface recall or
    ndcg on a multi-stage pipeline: stage -1 carries only run-level operational rows, and
    quality is recorded per stage because recall is a property of a point in the funnel.
    Single-stage pipelines emit no stage -1 rows at all, which is why the gap stayed hidden.

    One row per metric name (the largest ``k``): three ``recall@k`` rows for one pipeline used
    to fill the whole headline and push ndcg out.
    """
    from retrieval_observatory.metrics.comparison import parse_metric_key

    parsed: Dict[str, tuple[str, int, str, int, Any]] = {}
    for key in metrics:
        try:
            parsed[key] = parse_metric_key(key)
        except (TypeError, ValueError, IndexError):
            continue

    quality: list[str] = []
    pipelines = sorted({pipeline for pipeline, _s, name, _k, _b in parsed.values() if name in _QUALITY_METRICS})
    for pipeline in pipelines:
        candidates = [
            key for key, (pid, _s, name, _k, _b) in parsed.items() if pid == pipeline and name in _QUALITY_METRICS
        ]
        # Prefer the spine (a stage with one operator) over per-branch rows, which cover only
        # the queries routed down that branch (a gate-skipped span emits no rows), so their
        # `n` is the served count and their mean is not comparable to the spine's.
        spine = [key for key in candidates if parsed[key][4] is None] or candidates
        final_stage = max(parsed[key][1] for key in spine)
        best_by_name: Dict[str, str] = {}
        for key in spine:
            _pid, stage_index, name, k, _branch = parsed[key]
            if stage_index == final_stage and (name not in best_by_name or k > parsed[best_by_name[name]][3]):
                best_by_name[name] = key
        ordered = sorted(best_by_name.values(), key=lambda key: _QUALITY_METRICS.index(parsed[key][2]))
        quality.extend(ordered[:_QUALITY_ROWS_PER_PIPELINE])
    quality = quality[:_QUALITY_ROWS_TOTAL]

    # Classify on the parsed metric NAME, never the full key: a pipeline called
    # `cost_aware_bm25` would otherwise turn its recall into an operational row.
    operational = sorted(
        (key for key, (_p, _s, name, _k, _b) in parsed.items() if name.startswith(("latency", "cost"))),
        key=lambda key: (parsed[key][1] != -1, key),
    )

    keys = quality + operational[:2]
    return {key: metrics[key] for key in keys} if keys else dict(list(metrics.items())[:5])


def build_run_report(
    *,
    run_id: str,
    experiment_name: str,
    db_path: str,
    metrics: Dict[str, Any],
    diagnostics: list[Dict[str, Any]],
    manifest: Optional[Dict[str, Any]],
) -> ReportModel:
    manifest = manifest or {}
    counts = manifest.get("counts", {})
    attempted = counts.get("attempted")
    completed = counts.get("completed")
    failures = Counter(
        label
        for row in diagnostics
        for label in row.get("failure_labels", [])
    )
    dominant = None
    if failures:
        label, count = failures.most_common(1)[0]
        dominant = {"label": label, "query_count": count}

    evidence_reasons = []
    dataset = manifest.get("dataset", {})
    for key in ("query_hash", "corpus_hash", "qrel_hash"):
        if not dataset.get(key):
            evidence_reasons.append(f"Dataset {key} is unavailable.")
    if not manifest.get("labeling", {}).get("method"):
        evidence_reasons.append("Label provenance is unavailable.")
    if attempted is None or completed is None:
        evidence_reasons.append("Attempted/completed query counts are unavailable.")
    elif completed == 0:
        evidence_reasons.append(f"0/{attempted} queries completed; every query failed, so no metric was computed.")
    elif completed < attempted:
        evidence_reasons.append(f"{completed}/{attempted} queries completed; metrics cover only the completed queries.")
    if attempted is not None and completed == 0:
        evidence_health = "failed"
    else:
        evidence_health = "ready" if not evidence_reasons else "limited"

    if attempted is not None and completed is not None and completed < attempted:
        verdict = "partial"
        conclusion = f"{completed}/{attempted} queries completed; inspect terminal partial traces before drawing a run-level conclusion."
    elif dominant:
        verdict = "needs_attention"
        conclusion = f"The dominant diagnosed issue is {dominant['label']}, affecting {dominant['query_count']} evaluated query records."
    else:
        verdict = "no_diagnosed_failures"
        conclusion = "No retrieval failure label was diagnosed in the evaluated queries; this is not a claim about answer quality."

    affected = [
        {
            "query_id": row.get("query_id"),
            "pipeline_id": row.get("pipeline_id"),
            "failure_labels": sorted(row.get("failure_labels", [])),
        }
        for row in diagnostics
        if row.get("failure_labels")
    ]
    affected.sort(key=lambda row: (str(row["query_id"]), str(row["pipeline_id"])))
    affected = affected[:20]
    next_action = (
        f"Open an affected query and locate the first operator where `{dominant['label']}` appears."
        if dominant else
        "Compare this run with an explicit baseline before accepting a retrieval change."
    )
    return ReportModel(
        kind="run",
        run_id=run_id,
        title=f"retobs evaluation — {experiment_name}",
        verdict=verdict,
        conclusion=conclusion,
        evidence_health=evidence_health,
        evidence_reasons=evidence_reasons,
        metrics=_headline_metrics(metrics),
        dominant_issue=dominant,
        affected_queries=affected,
        provenance={
            "manifest_schema_version": manifest.get("schema_version"),
            "dataset": dataset,
            "labeling": manifest.get("labeling"),
            "models": manifest.get("models"),
            "git_commit": manifest.get("git_commit"),
            "git_dirty": manifest.get("git_dirty"),
        },
        next_action=next_action,
        reproduce=f"retobs report {run_id} --db {db_path}",
        dashboard_url=f"http://127.0.0.1:4000/#/runs/{run_id}/overview",
    )


async def load_run_report(run_id: str, db_path: str) -> ReportModel:
    from retrieval_observatory.metrics.engine import MetricsEngine
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    runs = await store.list_runs()
    run = next((item for item in runs if item["run_id"] == run_id), None)
    if run is None:
        raise ValueError(f"Run not found: {run_id}")
    return build_run_report(
        run_id=run_id,
        experiment_name=run.get("experiment_name", run_id),
        db_path=db_path,
        metrics=await MetricsEngine().aggregate(run_id, store),
        diagnostics=await store.get_query_diagnostics(run_id),
        manifest=await store.get_run_manifest(run_id),
    )


async def load_comparison_report(
    baseline_run_id: str,
    candidate_run_id: str,
    db_path: str,
    *,
    policy: str | Path | ReleasePolicy | ReleasePolicyV3 | None = None,
) -> ReportModel:
    """Build one validity-gated report for CLI, SDK, MCP, CI, and HTML artifacts."""
    from retrieval_observatory.dashboard.registry import _slugify
    from retrieval_observatory.release.audit import build_release_audit
    from retrieval_observatory.store.sqlite import SQLiteStore

    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    # The id `retobs serve --db <db_path>` gives this database, so audit links open it.
    db_id = _slugify(Path(db_path).stem)
    report, _audit = await build_release_audit(
        store,
        store,
        baseline_run_id,
        candidate_run_id,
        policy=policy,
        baseline_db_id=db_id,
        candidate_db_id=db_id,
        db_path=db_path,
    )
    return report


class BenchmarkReport:
    """Result of a callable or config evaluation."""

    def __init__(self, artifacts: BenchmarkArtifacts, db_path: str, experiment_name: str):
        self._artifacts = artifacts
        self.db_path = db_path
        self.experiment_name = experiment_name
        self._report_model: Optional[ReportModel] = None

    @property
    def run_id(self) -> str:
        return self._artifacts.run_id

    @property
    def metrics(self) -> Dict[str, Any]:
        return self._artifacts.aggregated

    @property
    def diagnostics(self) -> list:
        return self._artifacts.diagnostics

    @property
    def pipeline_ids(self) -> list:
        return self._artifacts.pipeline_ids

    @property
    def error_tracebacks(self) -> list[str]:
        """Distinct full tracebacks of failed queries, in first-seen order."""
        seen: list[str] = []
        for results in self._artifacts.results_by_pipeline.values():
            for result in results:
                trace = getattr(result, "error_traceback", None)
                if trace and trace not in seen:
                    seen.append(trace)
        return seen

    @property
    def report(self) -> ReportModel:
        if self._report_model is None:
            self._report_model = _run_sync(load_run_report(self.run_id, self.db_path))
        return self._report_model

    @property
    def manifest(self) -> Dict[str, Any]:
        from retrieval_observatory.store.sqlite import SQLiteStore

        async def _load() -> Dict[str, Any]:
            store = SQLiteStore(db_path=self.db_path)
            return await store.get_run_manifest(self.run_id) or {}

        return _run_sync(_load())

    def to_dict(self) -> Dict[str, Any]:
        return self.report.to_dict()

    def to_json(self) -> str:
        return self.report.to_json()

    def to_markdown(self) -> str:
        return self.report.to_markdown()

    def to_html(self) -> str:
        return self.report.to_html()

    def write(self, path: str | Path, *, format: Optional[str] = None) -> Path:
        return self.report.write(path, format=format)

    def export_config(self, path: str | Path) -> Path:
        import yaml

        target = Path(path)
        normalized = self.manifest.get("normalized_config")
        if not normalized:
            raise ValueError("This run does not include a normalized configuration.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(normalized, sort_keys=False), encoding="utf-8")
        return target

    def to_pandas(self):
        import pandas as pd

        rows = []
        for key, values in self.metrics.items():
            parts = key.split("|")
            row = {"pipeline": parts[0], "metric": parts[-1] if len(parts) > 1 else key}
            row.update(values if isinstance(values, dict) else {"value": values})
            rows.append(row)
        return pd.DataFrame(rows)

    def show(self) -> "BenchmarkReport":
        print(self.to_markdown())
        return self

    def serve(self, host: str = "0.0.0.0", port: int = 4000) -> None:
        import uvicorn

        from retrieval_observatory.dashboard.api import create_app
        from retrieval_observatory.dashboard.registry import DbRegistry

        app = create_app(registry=DbRegistry([self.db_path]))
        display_host = "localhost" if host in ("0.0.0.0", "::") else host
        print(f"Dashboard: http://{display_host}:{port}/#/runs/{self.run_id}/overview")
        uvicorn.run(app, host=host, port=port)

    def assert_no_regression(
        self,
        baseline: "BenchmarkReport | str",
        *,
        metric: Optional[str] = None,
        latency_regression_pct: float = 0.2,
    ) -> "BenchmarkReport":
        """Raise when the audit's paired results prove a quality drop or a latency rise.

        Quality: a spine ``ndcg``/``recall``/``mrr``/``map`` metric whose paired decision is
        ``candidate_worse``. Latency: a ``latency*`` metric that is ``candidate_worse`` and whose
        mean rose by at least ``latency_regression_pct``.
        """
        from retrieval_observatory.metrics.comparison import parse_metric_key

        baseline_run = baseline.run_id if isinstance(baseline, BenchmarkReport) else str(baseline)
        report = _run_sync(load_comparison_report(baseline_run, self.run_id, self.db_path))
        findings = []
        for key, result in sorted(((report.audit or {}).get("metrics") or {}).items()):
            if result.get("decision") != "candidate_worse" or (metric and metric not in key):
                continue
            _pipeline, _stage, name, _k, branch = parse_metric_key(key)
            before, after = result.get("baseline_mean"), result.get("candidate_mean")
            if name.startswith("latency"):
                if not before or after is None or (after - before) / before < latency_regression_pct:
                    continue
            elif branch or not name.startswith(_REGRESSION_QUALITY_METRICS):
                continue
            findings.append(
                f"  - {key}: {_format_number(before)} -> {_format_number(after)} "
                f"(effect {_format_number(result.get('effect'))}, q={_format_number(result.get('q_value'))}, "
                f"n={result.get('paired_n')})"
            )
        if findings:
            lines = "\n".join(findings)
            raise AssertionError(
                f"Retrieval regression vs baseline {baseline_run} (candidate {self.run_id}):\n{lines}"
            )
        return self

    def compare(
        self,
        baseline: "BenchmarkReport",
        *,
        policy: str | Path | ReleasePolicy | ReleasePolicyV3 | None = None,
    ) -> Dict[str, Any]:
        """Return the canonical comparison artifact, with the release audit under ``audit``."""
        report = _run_sync(
            load_comparison_report(
                baseline.run_id,
                self.run_id,
                self.db_path,
                policy=policy,
            )
        )
        return {**(report.comparison or {}), "audit": report.audit}


def _run_sync(coro):
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()
