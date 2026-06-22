"""pytest plugin for retrieval regression gating.

Enabled automatically once `retrieval-observatory` is installed (entry point `pytest11`).
Use the `retobs` fixture in a test to benchmark a pipeline and fail on a significant drop:

    def test_retrieval_quality(retobs):
        report = retobs.run(my_pipeline, queries=QUERIES, corpus=CORPUS)
        retobs.assert_no_regression(report, baseline="golden-run-id", metric="ndcg")
"""
from __future__ import annotations

from typing import Any, Optional

import pytest

from retrieval_observatory.sdk.api import benchmark
from retrieval_observatory.sdk.report import BenchmarkReport


class RetobsFixture:
    """Per-test handle for running benchmarks and asserting no regression.

    All runs default to a single per-test SQLite db so a candidate can be compared against a
    baseline run created in the same test.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def run(self, pipeline: Any, **kwargs: Any) -> BenchmarkReport:
        kwargs.setdefault("db_path", self.db_path)
        return benchmark(pipeline, **kwargs)

    def assert_no_regression(
        self,
        report: BenchmarkReport,
        baseline: "BenchmarkReport | str",
        *,
        metric: Optional[str] = None,
        latency_regression_pct: float = 0.2,
    ) -> BenchmarkReport:
        return report.assert_no_regression(
            baseline, metric=metric, latency_regression_pct=latency_regression_pct
        )


@pytest.fixture
def retobs(tmp_path) -> RetobsFixture:
    return RetobsFixture(db_path=str(tmp_path / "retobs_gate.db"))
