"""`retobs demo`: two deterministic golden-fixture runs that audit and investigate end to end."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from typer.testing import CliRunner

import retrieval_observatory as ro
from retrieval_observatory.cli import _demo, app
from retrieval_observatory.store.sqlite import SQLiteStore


def _outcomes(run_id: str, db_path: str) -> dict[str, tuple[str, str | None]]:
    rows = ro.inspect_document(run_id, "kb:doc-guide", db_path=db_path)["rows"]
    return {row["query_id"]: (row["outcome"], row["loss_boundary"]) for row in rows}


def test_demo_audits_a_repaired_filter_and_locates_the_lost_document(tmp_path: Path) -> None:
    db_path = str(tmp_path / "results.db")
    asyncio.run(_demo(output_dir=str(tmp_path), db_path=db_path))

    manifest = json.loads((tmp_path / "demo_manifest.json").read_text(encoding="utf-8"))
    assert {"baseline_run_id", "validation_run_id", "db_path", "policy_path"} <= set(manifest)
    baseline, validation = manifest["baseline_run_id"], manifest["validation_run_id"]
    policy = Path(manifest["policy_path"])
    assert policy.is_file()

    async def _runs():
        store = SQLiteStore(db_path=db_path)
        await store.init_db()
        manifests = [await store.get_run_manifest(run_id) for run_id in (baseline, validation)]
        return await store.list_runs(), manifests, [await store.get_metrics(run_id) for run_id in (baseline, validation)]

    runs, run_manifests, metric_rows = asyncio.run(_runs())
    assert {run["run_id"] for run in runs} == {baseline, validation}
    for run_manifest in run_manifests:
        assert run_manifest["investigation_projection"]["golden-hybrid"]["status"] == "complete"
        assert run_manifest["evaluation"]["k"] == 3
        assert {record["namespace"] for record in run_manifest["judgment_records"]} == {"kb", "tickets"}
    # Metrics score documents (namespace:document_id), not chunk ids: the repair lifts q-outage's final recall.
    final_recall = [
        {row["query_id"]: row["value"] for row in rows if row["metric_name"] == "recall" and row["stage_index"] == max(r["stage_index"] for r in rows)}
        for rows in metric_rows
    ]
    assert final_recall[0] == {"q-refund": 1.0, "q-outage": 0.0, "q-invoice": 2 / 3}
    assert final_recall[1] == {"q-refund": 1.0, "q-outage": 1.0, "q-invoice": 2 / 3}
    assert run_manifests[0]["release_identity"]["deployment_revision"] != run_manifests[1]["release_identity"]["deployment_revision"]

    result = CliRunner().invoke(
        app,
        ["compare", baseline, validation, "--db", db_path, "--policy", str(policy), "--fail-on", "hold-or-block-or-fail"],
    )
    assert result.exit_code == 0, result.output
    assert "**Status:** `PASS`" in result.output

    assert _outcomes(baseline, db_path)["q-outage"] == ("relevant_excluded", "recency_filter")
    assert _outcomes(validation, db_path)["q-outage"] == ("relevant_delivered", None)
