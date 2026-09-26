"""One release audit (schema audit-1) across the SDK, CLI, MCP, dashboard and the standalone HTML."""
from __future__ import annotations

import asyncio
import copy
import html
import json
import re

import pytest
from typer.testing import CliRunner

from retrieval_observatory.cli import app
from retrieval_observatory.mcp import server
from retrieval_observatory.sdk.report import load_comparison_report
from retrieval_observatory.store.sqlite import SQLiteStore
from tests.integration.test_release_decision_workflow import _manifest

_POLICY = """schema_version: 3
id: audit-workflow-v3
evaluation:
  unit: document
  boundary: final_retrieval
  k: 10
  relevance_threshold: 1
intervention:
  expected_changes: [deployment_revision]
statistics:
  confidence_level: 0.95
  familywise_alpha: 0.05
  resamples: 1000
  seed: 17
metrics:
  - id: final-recall
    metric: recall
    target: final_retrieval
    direction: higher_is_better
    max_regression: 0.5
    min_paired_n: 2
execution:
  max_failure_rate: 0.0
"""


async def _seed(db_path: str) -> None:
    store = SQLiteStore(db_path=db_path)
    await store.init_db()
    for run_id, deployment, values in (
        ("baseline", "deploy-a", [1.0] * 6),
        ("candidate", "deploy-b", [1.0, 0.0, 1.0, 1.0, 1.0, 0.5]),
    ):
        await store.save_run(run_id, run_id, "{}")
        await store.save_run_manifest(run_id, _manifest(deployment=deployment, embedding_model_revision="embed-v1"))
        await store.save_metrics_batch([{
            "run_id": run_id, "pipeline_id": "pipeline", "query_id": f"q-{index}",
            "stage_index": 0, "metric_name": "recall", "k": 10, "value": value,
            "branch_id": None, "query_metadata_json": {"scenario": "standard"},
        } for index, value in enumerate(values)])


@pytest.fixture
def seeded(tmp_path):
    db_path = str(tmp_path / "audit.db")
    asyncio.run(_seed(db_path))
    policy_path = tmp_path / "policy-v3.yaml"
    policy_path.write_text(_POLICY, encoding="utf-8")
    return db_path, str(policy_path)


def _dashboard_compare(db_path: str, policy_path: str) -> dict:
    from fastapi.testclient import TestClient

    from retrieval_observatory.dashboard.api import create_app
    from retrieval_observatory.dashboard.registry import DbRegistry

    registry = DbRegistry([db_path])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    response = client.post(
        f"/dbs/{registry.list_db_ids()[0]}/compare",
        json={"run_ids": ["baseline", "candidate"], "policy_path": policy_path},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _comparable(audit: dict) -> dict:
    audit = copy.deepcopy(audit)
    audit.pop("generated_at")
    for role in ("baseline", "candidate"):
        audit["sources"][role].pop("db_id")
    audit["investigation"]["scope"].pop("db_id")
    return audit


def test_sdk_cli_mcp_and_dashboard_share_one_audit(seeded):
    db_path, policy_path = seeded
    sdk = asyncio.run(load_comparison_report("baseline", "candidate", db_path, policy=policy_path)).audit
    cli = CliRunner().invoke(
        app, ["compare", "baseline", "candidate", "--db", db_path, "--policy", policy_path, "--format", "json"]
    )
    assert cli.exit_code == 0, cli.stdout
    cli_audit = json.loads(cli.stdout)["audit"]
    mcp = asyncio.run(
        server._compare_runs("baseline", "candidate", format="audit", db_path=db_path, policy_path=policy_path)
    )
    dashboard = _dashboard_compare(db_path, policy_path)["audit"]

    audits = [sdk, cli_audit, mcp, dashboard]
    for audit in audits:
        assert audit["schema_version"] == "audit-1"
        assert audit["decision"]["exit_code"] in (0, 1, 2, 3)
        assert audit["checks"][0]["id"] == "final-recall"
        assert "final-recall" in audit["coverage"]["per_check"]
        assert "compare=baseline" in audit["investigation"]["changed_queries"][0]["link"]
    assert all(_comparable(audit) == _comparable(sdk) for audit in audits)
    # The CLI names the database the way `retobs serve` does, so its links open the same page.
    assert sdk["investigation"]["changed_queries"][0]["link"] == dashboard["investigation"]["changed_queries"][0]["link"]


def test_html_report_is_standalone_and_readable_offline(seeded, tmp_path):
    db_path, policy_path = seeded
    target = tmp_path / "artifacts"
    result = CliRunner().invoke(
        app, ["compare", "baseline", "candidate", "--db", db_path, "--policy", policy_path, "--artifacts", str(target)]
    )
    assert result.exit_code == 0, result.stdout

    audit = json.loads((target / "release-audit.json").read_text(encoding="utf-8"))
    page = (target / "release-audit.html").read_text(encoding="utf-8")
    assert audit["decision"]["status"] in page
    for check in audit["checks"]:
        assert check["id"] in page
    classifications = {
        item["classification"]
        for group in ("invariants", "interventions", "consistency")
        for item in audit["compatibility"]["provenance"][group]
    }
    assert classifications
    for word in classifications:
        assert f"<td>{word}</td>" in page
    link = audit["investigation"]["changed_queries"][0]["link"]
    assert f'href="{html.escape("http://127.0.0.1:4000/" + link)}"' in page
    assert page.count("<details>") >= 2
    assert "<script src=" not in page
    assert '<link rel="stylesheet"' not in page
    assert "<link rel=" not in page
    urls = re.findall(r"https?://[^\s\"'<&]+", page)
    assert urls and all(url.startswith("http://127.0.0.1:4000") for url in urls)


class _Report:
    next_action = "Review."

    def __init__(self, verdict: str):
        self.verdict = verdict
        self.audit = {"schema_version": "audit-1", "decision": {"status": verdict, "reasons": []}}


@pytest.mark.parametrize(("verdict", "gated", "fail_only", "default"), [
    ("PASS", 0, 0, 0),
    ("FAIL", 1, 1, 0),
    ("BLOCK", 2, 0, 0),
    ("HOLD", 3, 0, 0),
])
def test_exit_codes_follow_the_decision(monkeypatch, verdict, gated, fail_only, default):
    async def fake_compare(*args, **kwargs):
        return _Report(verdict)

    monkeypatch.setattr("retrieval_observatory.cli._compare", fake_compare)
    runner = CliRunner()

    assert runner.invoke(app, ["compare", "b", "c", "--fail-on", "hold-or-block-or-fail"]).exit_code == gated
    assert runner.invoke(app, ["compare", "b", "c", "--fail-on", "fail"]).exit_code == fail_only
    assert runner.invoke(app, ["compare", "b", "c"]).exit_code == default


def test_tool_error_is_distinct_from_a_decision(seeded, tmp_path):
    db_path, policy_path = seeded
    target = tmp_path / "artifacts"
    result = CliRunner().invoke(
        app,
        ["compare", "baseline", "no-such-run", "--db", db_path, "--policy", policy_path,
         "--artifacts", str(target), "--fail-on", "hold-or-block-or-fail"],
    )

    assert result.exit_code == 70
    assert "Comparison failed" in result.stdout
    assert not target.exists()


def test_dashboard_no_longer_uses_v2_evaluators_for_v3_policies(seeded):
    db_path, policy_path = seeded
    decision = _dashboard_compare(db_path, policy_path)["release_decision"]

    guard = decision["aggregate_guards"][0]
    assert guard["check_id"] == "final-recall"
    assert guard["resolution_status"] == "resolved"
    assert decision["operational"] is not None
    assert decision["policy"]["id"] == "audit-workflow-v3"
    assert decision["investigation"]["diff_route_template"].startswith("#/investigate?db=") and "compare=" in decision["investigation"]["diff_route_template"]


def test_baseline_is_explicit(monkeypatch, seeded):
    db_path, _policy_path = seeded

    async def fake_compare(*args, **kwargs):
        raise AssertionError("a comparison must never pick a baseline on its own")

    monkeypatch.setattr("retrieval_observatory.cli._compare", fake_compare)
    result = CliRunner().invoke(app, ["compare", "candidate", "--db", db_path])

    assert result.exit_code == 2
