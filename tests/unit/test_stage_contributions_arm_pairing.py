"""Arm-vs-fused ablations pair each branch arm with the spine node it feeds, and within-pipeline
rows label layers that span a branch-only depth."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_observatory.dashboard.api import _compute_stage_contributions, create_app
from retrieval_observatory.dashboard.registry import DbRegistry

FLAGSHIP_DB = Path(
    os.environ.get(
        "RETOBS_FLAGSHIP_DB",
        Path(__file__).resolve().parents[2] / "results" / "flagship_demo" / ".retobs" / "demo.db",
    )
)

# Union layout of a small DAG: root(0) -> {a, b}(1); a -> x(2); {x, b} -> fuse(3).
PARENTS = {"dag": {"root": set(), "a": {"root"}, "b": {"root"}, "x": {"a"}, "fuse": {"x", "b"}}}
QUERIES = ("q1", "q2", "q3")


def _entry(stage: int, branch: str | None, mean: float) -> dict:
    return {"pipeline_id": "dag", "stage_index": stage, "metric_name": "recall", "k": 10, "mean": mean, "branch_id": branch}


def _rows(stage: int, branch: str | None, values: tuple) -> list[dict]:
    return [
        {"query_id": qid, "pipeline_id": "dag", "stage_index": stage, "branch_id": branch, "metric_name": "recall", "k": 10, "value": value}
        for qid, value in zip(QUERIES, values)
    ]


def _fixture() -> tuple[dict, list]:
    metrics = {
        "dag|stage0|recall@10": _entry(0, None, 0.5),
        "dag|stage1|recall@10|branch=a": _entry(1, "a", 0.4),
        "dag|stage1|recall@10|branch=b": _entry(1, "b", 0.6),
        "dag|stage2|recall@10": _entry(2, None, 0.7),
        "dag|stage3|recall@10": _entry(3, None, 0.9),
    }
    rows = (
        _rows(0, None, (0.5, 0.5, 0.5))
        + _rows(1, "a", (0.2, 0.5, 0.5))
        + _rows(1, "b", (0.6, 0.6, 0.6))
        + _rows(2, None, (0.7, 0.7, 0.7))
        + _rows(3, None, (0.9, 0.9, 0.9))
    )
    return metrics, rows


def _arm_rows(contributions: list) -> dict:
    return {c["branch_id"]: c for c in contributions if c["comparison_tier"] == "within_stage_arm"}


def test_arms_pair_with_the_fuse_they_feed_when_topology_is_known() -> None:
    metrics, rows = _fixture()
    arms = _arm_rows(_compute_stage_contributions(metrics, rows, parent_map=PARENTS))
    assert arms["a"]["to_pipeline"] == "dag:stage2:fused" and arms["a"]["fuse_stage_index"] == 2
    assert arms["b"]["to_pipeline"] == "dag:stage3:fused" and arms["b"]["fuse_stage_index"] == 3
    assert {arms["a"]["pairing_basis"], arms["b"]["pairing_basis"]} == {"topology"}
    for arm in arms.values():
        assert arm["deltas"], "an arm paired with a deeper spine stage must carry quality deltas"
        assert arm["deltas"]["recall@10"]["n_pairs"] == len(QUERIES)
    assert arms["a"]["deltas"]["recall@10"]["absolute"] == pytest.approx(0.7 - 0.4)
    assert arms["b"]["deltas"]["recall@10"]["absolute"] == pytest.approx(0.9 - 0.6)


def test_arms_fall_back_to_the_nearest_deeper_spine_without_topology() -> None:
    metrics, rows = _fixture()
    arms = _arm_rows(_compute_stage_contributions(metrics, rows))
    assert arms["a"]["fuse_stage_index"] == 2 and arms["b"]["fuse_stage_index"] == 2
    assert all(arm["pairing_basis"] == "depth_order" for arm in arms.values())
    assert all(arm["deltas"] for arm in arms.values())


def test_within_pipeline_rows_label_layers_that_span_branch_depths() -> None:
    metrics, rows = _fixture()
    within = [c for c in _compute_stage_contributions(metrics, rows, parent_map=PARENTS) if c["comparison_tier"] == "within_pipeline_stage"]
    assert [(c["from_pipeline"], c["to_pipeline"]) for c in within] == [
        ("dag:stage0", "dag:stage2"),
        ("dag:stage2", "dag:stage3"),
    ]
    assert within[0]["via_branch_depths"] == [1] and within[0]["spans_branch_layer"] is True
    assert within[1]["via_branch_depths"] == [] and within[1]["spans_branch_layer"] is False
    assert within[0]["deltas"]["recall@10"]["absolute"] == pytest.approx(0.2)


@pytest.mark.skipif(not FLAGSHIP_DB.is_file(), reason="flagship demo database not present")
def test_flagship_hybrid_dag_arms_have_deltas() -> None:
    registry = DbRegistry([str(FLAGSHIP_DB)], read_only=True)
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    body = client.get(f"/dbs/{registry.default_db_id}/runs/4b5be1ce/overview").json()
    arms = _arm_rows(body["stage_contributions"])
    for lane in ("bm25_lane", "dense_lane"):
        assert arms[lane]["deltas"], f"{lane} ablation must not be empty"
        assert arms[lane]["to_pipeline"].endswith(":stage1:fused")
        assert arms[lane]["pairing_basis"] == "topology"
    # bridge_hop2 feeds bridge_siblings (depth 4); comparison_widen feeds route_merge (depth 5).
    assert arms["bridge_hop2"]["fuse_stage_index"] == 4
    assert arms["comparison_widen"]["fuse_stage_index"] == 5
    assert all(arm["deltas"] for arm in arms.values())
    within = [c for c in body["stage_contributions"] if c["comparison_tier"] == "within_pipeline_stage"]
    spanning = next(c for c in within if c["from_pipeline"].endswith("stage2") and c["to_pipeline"].endswith("stage4"))
    assert spanning["via_branch_depths"] == [3]
