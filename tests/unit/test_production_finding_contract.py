from retrieval_observatory.tracing.monitor.drift import compute_drift
from retrieval_observatory.tracing.monitor.hotspots import compute_hotspots


def _trace(index: int, *, difficulty: str = "hard", suspected: bool = True, latency: float = 10.0):
    return {
        "trace_id": f"trace-{index}",
        "predicted_difficulty": difficulty,
        "pipeline_id": "pipeline",
        "suspected_failures": ["candidate_starvation"] if suspected else [],
        "status": "OK",
        "query_text": "short query",
        "total_latency_ms": latency,
    }


def test_hotspot_includes_auditable_sample_and_trace_drilldown() -> None:
    finding = compute_hotspots([_trace(1), _trace(2), _trace(3, suspected=False)])[0]
    assert finding["evidence_class"] == "heuristic"
    assert finding["method"] == "label_free_proxy_segment_count_v1"
    assert finding["sample_size"] == 3
    assert finding["denominator"] == 3
    assert finding["supporting_trace_ids"] == ["trace-1", "trace-2"]
    assert finding["threshold"] is None


def test_drift_includes_method_threshold_sample_sizes_and_traces() -> None:
    baseline = [_trace(i, difficulty="easy", latency=10) for i in range(20)]
    recent = [_trace(100 + i, difficulty="hard", latency=100) for i in range(20)]
    findings = compute_drift(baseline, recent)
    assert findings
    for finding in findings:
        assert finding["evidence_class"] == "statistical"
        assert finding["baseline_n"] == 20
        assert finding["recent_n"] == 20
        assert finding["threshold"] is not None
        assert finding["supporting_trace_ids"]
