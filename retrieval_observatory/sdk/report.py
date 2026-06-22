from __future__ import annotations

from typing import Any, Dict, Optional

from retrieval_observatory.runner.execute import BenchmarkArtifacts


class BenchmarkReport:
    """Result of a `benchmark()` run — metrics, diagnostics, and convenience views."""

    def __init__(self, artifacts: BenchmarkArtifacts, db_path: str, experiment_name: str):
        self._artifacts = artifacts
        self.db_path = db_path
        self.experiment_name = experiment_name

    @property
    def run_id(self) -> str:
        return self._artifacts.run_id

    @property
    def metrics(self) -> Dict[str, Any]:
        """Aggregated metrics keyed by '<pipeline_id>/<metric>'."""
        return self._artifacts.aggregated

    @property
    def diagnostics(self) -> list:
        return self._artifacts.diagnostics

    @property
    def pipeline_ids(self) -> list:
        return self._artifacts.pipeline_ids

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "experiment": self.experiment_name,
            "db_path": self.db_path,
            "pipelines": self.pipeline_ids,
            "metrics": self.metrics,
        }

    def to_pandas(self):
        import pandas as pd  # optional dependency

        rows = []
        for key, vals in self.metrics.items():
            # Aggregate keys look like "pipeline_id|stageN|metric@k".
            parts = key.split("|")
            pipeline_id = parts[0]
            metric = parts[-1] if len(parts) > 1 else key
            row = {"pipeline": pipeline_id, "metric": metric}
            if isinstance(vals, dict):
                row.update(vals)
            else:
                row["value"] = vals
            rows.append(row)
        return pd.DataFrame(rows)

    def show(self) -> "BenchmarkReport":
        from retrieval_observatory.cli import _print_diagnostics_summary, _print_metrics_table

        _print_metrics_table(self.metrics, self.run_id)
        _print_diagnostics_summary(self.diagnostics)
        return self

    def serve(self, host: str = "0.0.0.0", port: int = 4000) -> None:
        """Launch the dashboard on this run's database (blocking)."""
        import uvicorn

        from retrieval_observatory.dashboard.api import create_app
        from retrieval_observatory.dashboard.registry import DbRegistry

        app = create_app(registry=DbRegistry([self.db_path]))
        display_host = "localhost" if host in ("0.0.0.0", "::") else host
        print(f"Dashboard: http://{display_host}:{port}  (run_id={self.run_id})")
        uvicorn.run(app, host=host, port=port)

    def assert_no_regression(
        self,
        baseline: "BenchmarkReport | str",
        *,
        metric: Optional[str] = None,
        latency_regression_pct: float = 0.2,
    ) -> "BenchmarkReport":
        """Raise AssertionError if this run significantly regressed vs a baseline run.

        `baseline` is another BenchmarkReport (sharing this db) or a run_id string.
        `metric` optionally restricts the check to keys containing that substring (e.g. "ndcg").
        """
        baseline_run = baseline.run_id if isinstance(baseline, BenchmarkReport) else str(baseline)
        findings = _run_sync(self._regressions(baseline_run, latency_regression_pct))
        if metric:
            findings = [f for f in findings if metric in f.metric]
        if findings:
            lines = "\n".join(
                f"  - {f.metric}: {f.before:.4f} -> {f.after:.4f} "
                f"(Δ{f.delta:+.4f}, q={f.q_value:.3f}, {f.severity})"
                for f in findings
            )
            raise AssertionError(
                f"Retrieval regression vs baseline {baseline_run} (candidate {self.run_id}):\n{lines}"
            )
        return self

    async def _regressions(self, baseline_run: str, latency_regression_pct: float):
        from retrieval_observatory.advisor.regression import detect_regressions
        from retrieval_observatory.store.sqlite import SQLiteStore

        store = SQLiteStore(db_path=self.db_path)
        return await detect_regressions(
            baseline_run, self.run_id, store, latency_regression_pct=latency_regression_pct
        )

    def compare(self, baseline: "BenchmarkReport") -> Dict[str, Any]:
        """Paired comparison of this run vs a baseline run (must share a db_path)."""
        from retrieval_observatory.metrics.comparison import paired_scores_by_query
        from retrieval_observatory.metrics.significance import benjamini_hochberg, paired_bootstrap_test
        from retrieval_observatory.store.sqlite import SQLiteStore

        from retrieval_observatory.metrics.engine import MetricsEngine

        async def _run() -> Dict[str, Any]:
            store = SQLiteStore(db_path=self.db_path)
            engine = MetricsEngine()
            agg_a = await engine.aggregate(baseline.run_id, store)
            agg_b = await engine.aggregate(self.run_id, store)
            metrics_a = await store.get_metrics(baseline.run_id)
            metrics_b = await store.get_metrics(self.run_id)
            keys = sorted(set(agg_a) | set(agg_b))
            out: Dict[str, Any] = {}
            raw_p = []
            order = []
            for key in keys:
                s1, s2, n = paired_scores_by_query(metrics_a, metrics_b, key)
                if s1 and s2:
                    p = paired_bootstrap_test(s1, s2)
                    raw_p.append(p)
                    order.append((key, n))
            q_values = benjamini_hochberg(raw_p)
            for (key, n), q in zip(order, q_values):
                out[key] = {
                    "baseline": agg_a.get(key, {}).get("mean"),
                    "candidate": agg_b.get(key, {}).get("mean"),
                    "q_value": q,
                    "n_pairs": n,
                    "significant": q < 0.05,
                }
            return out

        return _run_sync(_run())


def _run_sync(coro):
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Inside an existing loop (e.g. Jupyter): run in a dedicated thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()
