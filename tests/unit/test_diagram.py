"""P2.1/P2.2 — diagram JSON with CI overlay + standalone HTML export."""
from retrieval_observatory.dashboard.api import _build_diagram, _metric_with_ci
from retrieval_observatory.diagram.html import render_diagram_html
from retrieval_observatory.types import Document, StageSnapshot


class _Result:
    def __init__(self, pipeline_id, snapshots):
        self.pipeline_id = pipeline_id
        self.status = "OK"
        self.snapshots = snapshots


def _agg_entry(pipeline_id, stage_index, metric_name, k, mean, ci):
    return {
        "pipeline_id": pipeline_id,
        "stage_index": stage_index,
        "metric_name": metric_name,
        "k": k,
        "branch_id": None,
        "mean": mean,
        "ci_low": ci[0],
        "ci_high": ci[1],
    }


def _fixture():
    metrics = {
        "p|stage0|recall@10": _agg_entry("p", 0, "recall", 10, 0.7, (0.6, 0.8)),
        "p|stage0|ndcg@10": _agg_entry("p", 0, "ndcg", 10, 0.5, (0.4, 0.6)),
        "p|stage0|latency_p50": _agg_entry("p", 0, "latency_p50", 0, 12.0, (10.0, 14.0)),
    }
    results = [
        _Result("p", [StageSnapshot(stage_index=0, stage_id="bm25", documents=[Document(id="d", text="", score=1.0, rank=1)], latency_ms=1.0, op_type="SOURCE")])
    ]
    return metrics, results


def test_build_diagram_surfaces_ci():
    metrics, results = _fixture()
    pipelines = _build_diagram(metrics, results)
    assert len(pipelines) == 1
    node = pipelines[0]["nodes"][0]
    recall = node["metrics"]["recall"]
    assert recall["ci_low"] < recall["mean"] < recall["ci_high"]
    assert recall["k"] == 10
    assert node["metrics"]["ndcg@10"]["ci_low"] == 0.4


def test_metric_with_ci_none_safe():
    assert _metric_with_ci(None) is None


def test_render_html_is_standalone():
    metrics, results = _fixture()
    pipelines = _build_diagram(metrics, results)
    html = render_diagram_html("run123", pipelines)
    assert "<html" in html and "</html>" in html
    assert "95% CI" in html
    assert "run123" in html
    # No external network resources — fully offline artifact.
    assert "http://" not in html and "https://" not in html
