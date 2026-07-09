"""Golden-topology regression fixtures (RETOBS_FINER_PLAN_PHASE2.md, Item A step 6).

Snapshot-asserts build_pipeline_graphs' exact node/edge JSON for four representative
topology shapes (linear, hybrid fan-in, conditional gate+skip, parallel lanes without
fusion) built directly from hand-constructed traces -- no live pipeline execution needed.
This is the guard against the heuristic/trace-native topology drift that motivated
deleting `_build_diagram`/`_pipeline_topology` in the first place: if a future change to
`build_pipeline_graphs` silently changes node ids, depths, or edge kinds for any of these
shapes, one of these snapshots breaks.
"""
from __future__ import annotations

from retrieval_observatory.pipeline.graph_projection import build_pipeline_graphs
from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan, RetrievalTraceV2


def _span(op_id, op_type, parents, status="FIRED", **kw):
    return OperatorSpan(
        op_id=op_id, op_type=op_type, op_name=op_id, parent_ids=parents,
        status=status, deterministic=True, replay_policy="EXACT", latency_ms=1.0, **kw,
    )


def _graph_dict(trace: RetrievalTraceV2, pipeline_id: str) -> dict:
    graphs = build_pipeline_graphs({}, [trace])
    matches = [g for g in graphs if g.pipeline_id == pipeline_id]
    assert matches, f"no graph produced for pipeline {pipeline_id}"
    return matches[0].to_dict()


def _shape(graph: dict) -> dict:
    """Reduce a graph dict to the structural facts that matter for a topology snapshot --
    node ids/depths/branch_ids/is_merge, and edges by (source, target, kind). Metrics are
    excluded (covered by test_pipeline_graph.py's CI tests) so this file stays a pure
    topology guard."""
    return {
        "nodes": sorted(
            (n["node_id"], n["depth"], n["branch_id"], n["is_merge"], n["op_type"])
            for n in graph["nodes"]
        ),
        "edges": sorted((e["source"], e["target"], e["kind"]) for e in graph["edges"]),
    }


def test_golden_linear_chain():
    source = _span("src", "SOURCE", [], outputs=[Candidate(doc_id="d1", score=1.0, rank=1)])
    rerank = _span("rr", "RERANK", ["src"], outputs=[Candidate(doc_id="d1", score=1.0, rank=1)])
    trace = RetrievalTraceV2(
        trace_id="t", run_id="r", query_id="q", query_text="q", pipeline_id="linear",
        spans=[source, rerank], total_latency_ms=2.0, final_op_id="rr",
    )
    assert _shape(_graph_dict(trace, "linear")) == {
        "nodes": [
            ("rr", 1, None, False, "RERANK"),
            ("src", 0, None, False, "SOURCE"),
        ],
        "edges": [("src", "rr", "flow")],
    }


def test_golden_hybrid_fan_in():
    arm_a = _span("arm_a", "SOURCE", [], outputs=[Candidate(doc_id="d1", score=1.0, rank=1)])
    arm_b = _span("arm_b", "SOURCE", [], outputs=[Candidate(doc_id="d2", score=0.9, rank=1)])
    fuse = _span("fuse", "FUSE", ["arm_a", "arm_b"], outputs=[
        Candidate(doc_id="d1", score=0.5, rank=1), Candidate(doc_id="d2", score=0.4, rank=2),
    ])
    trace = RetrievalTraceV2(
        trace_id="t", run_id="r", query_id="q", query_text="q", pipeline_id="hybrid",
        spans=[arm_a, arm_b, fuse], total_latency_ms=3.0, final_op_id="fuse",
    )
    assert _shape(_graph_dict(trace, "hybrid")) == {
        "nodes": [
            ("arm_a", 0, "arm_a", False, "SOURCE"),
            ("arm_b", 0, "arm_b", False, "SOURCE"),
            ("fuse", 1, None, True, "FUSE"),
        ],
        "edges": [
            ("arm_a", "fuse", "fan_in"),
            ("arm_b", "fuse", "fan_in"),
        ],
    }


def test_golden_conditional_gate_with_skip():
    source = _span("src", "SOURCE", [], outputs=[Candidate(doc_id="d1", score=1.0, rank=1)])
    gate = _span("gate", "GATE", ["src"], gate_values={"route": "fast"},
                 outputs=[Candidate(doc_id="d1", score=1.0, rank=1)])
    # Only the taken branch is FIRED; the skipped branch is SKIPPED_BY_GATE and must still
    # appear in the graph (never silently omitted) even though it contributes no metrics.
    fast_path = _span("fast_rerank", "RERANK", ["gate"], outputs=[Candidate(doc_id="d1", score=1.0, rank=1)])
    slow_path = _span("slow_rerank", "RERANK", ["gate"], status="SKIPPED_BY_GATE", outputs=[])
    trace = RetrievalTraceV2(
        trace_id="t", run_id="r", query_id="q", query_text="q", pipeline_id="gated",
        spans=[source, gate, fast_path, slow_path], total_latency_ms=3.0, final_op_id="fast_rerank",
    )
    shape = _shape(_graph_dict(trace, "gated"))
    node_ids = {n[0] for n in shape["nodes"]}
    assert node_ids == {"src", "gate", "fast_rerank", "slow_rerank"}
    skipped = next(n for n in shape["nodes"] if n[0] == "slow_rerank")
    assert skipped[4] == "RERANK"  # present with its op_type, not dropped


def test_golden_parallel_lanes_no_fusion():
    """Two independent SOURCE lanes that never merge (e.g. two separate retrieval calls
    feeding two separate downstream consumers) -- distinct from the hybrid fan-in shape."""
    lane_a = _span("lane_a", "SOURCE", [], outputs=[Candidate(doc_id="d1", score=1.0, rank=1)])
    lane_b = _span("lane_b", "SOURCE", [], outputs=[Candidate(doc_id="d2", score=0.9, rank=1)])
    rerank_a = _span("rr_a", "RERANK", ["lane_a"], outputs=[Candidate(doc_id="d1", score=1.0, rank=1)])
    rerank_b = _span("rr_b", "RERANK", ["lane_b"], outputs=[Candidate(doc_id="d2", score=0.9, rank=1)])
    trace = RetrievalTraceV2(
        trace_id="t", run_id="r", query_id="q", query_text="q", pipeline_id="parallel",
        spans=[lane_a, lane_b, rerank_a, rerank_b], total_latency_ms=2.0, final_op_id="rr_a",
    )
    shape = _shape(_graph_dict(trace, "parallel"))
    assert shape["edges"] == [
        ("lane_a", "rr_a", "flow"),
        ("lane_b", "rr_b", "flow"),
    ]
    merge_nodes = [n for n in shape["nodes"] if n[3] is True]
    assert merge_nodes == []  # no fan-in anywhere in this shape
