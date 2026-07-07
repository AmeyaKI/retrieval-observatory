from __future__ import annotations


from retrieval_observatory.metrics.pareto import ParetoPipelineInput, compute_pareto_frontier


def _pipeline(
    pipeline_id: str,
    ndcg10: float,
    recall10: float,
    latency_p50: float,
    latency_p95: float | None = None,
    cost_per_1k: float | None = None,
    stage_index: int = 0,
) -> ParetoPipelineInput:
    return ParetoPipelineInput(
        pipeline_id=pipeline_id,
        stage_index=stage_index,
        ndcg10=ndcg10,
        recall10=recall10,
        latency_p50=latency_p50,
        latency_p95=latency_p95 if latency_p95 is not None else latency_p50 * 1.5,
        cost_per_1k=cost_per_1k,
    )


def test_dominated_pipeline():
    result = compute_pareto_frontier(
        [
            _pipeline("fast", ndcg10=0.40, recall10=0.30, latency_p50=10.0, latency_p95=15.0),
            _pipeline("dominated", ndcg10=0.30, recall10=0.20, latency_p50=50.0, latency_p95=75.0),
            _pipeline("quality", ndcg10=0.50, recall10=0.40, latency_p50=100.0, latency_p95=150.0),
        ]
    )

    by_id = {row.pipeline_id: row for row in result.pipelines}
    assert by_id["dominated"].is_pareto_optimal is False
    assert "fast" in by_id["dominated"].dominated_by
    assert by_id["fast"].is_pareto_optimal is True
    assert by_id["quality"].is_pareto_optimal is True


def test_frontier_order_sorted_by_latency():
    result = compute_pareto_frontier(
        [
            _pipeline("slow", ndcg10=0.50, recall10=0.40, latency_p50=200.0),
            _pipeline("fast", ndcg10=0.30, recall10=0.20, latency_p50=10.0),
        ]
    )
    assert result.frontier_order == ["fast", "slow"]


def test_cost_excluded_when_any_pipeline_missing_cost():
    result = compute_pareto_frontier(
        [
            _pipeline("a", ndcg10=0.4, recall10=0.3, latency_p50=10.0, cost_per_1k=1.0),
            _pipeline("b", ndcg10=0.5, recall10=0.35, latency_p50=20.0, cost_per_1k=None),
        ]
    )
    assert result.cost_included is False
    assert result.cost_excluded_reason is not None
    assert "cost_per_1k" not in result.objectives


def test_cost_included_when_all_pipelines_have_cost():
    result = compute_pareto_frontier(
        [
            _pipeline("a", ndcg10=0.4, recall10=0.3, latency_p50=10.0, cost_per_1k=1.0),
            _pipeline("b", ndcg10=0.5, recall10=0.35, latency_p50=20.0, cost_per_1k=2.0),
        ]
    )
    assert result.cost_included is True
    assert "cost_per_1k" in result.objectives
    assert result.cost_excluded_reason is None


def test_empty_and_single_pipeline():
    empty = compute_pareto_frontier([])
    assert empty.pipelines == []
    assert empty.frontier_order == []

    single = compute_pareto_frontier(
        [_pipeline("only", ndcg10=0.4, recall10=0.3, latency_p50=10.0)]
    )
    assert single.pipelines[0].is_pareto_optimal is True
    assert single.frontier_order == ["only"]


def _pipeline_with_ci(
    pipeline_id: str,
    ndcg10: float,
    ndcg_ci: tuple[float, float],
    recall10: float = 0.30,
    latency_p50: float = 10.0,
) -> ParetoPipelineInput:
    return ParetoPipelineInput(
        pipeline_id=pipeline_id,
        stage_index=0,
        ndcg10=ndcg10,
        recall10=recall10,
        latency_p50=latency_p50,
        latency_p95=latency_p50 * 1.5,
        ndcg10_ci_low=ndcg_ci[0],
        ndcg10_ci_high=ndcg_ci[1],
    )


def test_pareto_dominance_requires_significant_quality_difference():
    # "a" has a higher point-estimate NDCG than "b", but their bootstrap CIs overlap
    # heavily — the gap could be noise, so neither should dominate the other.
    result = compute_pareto_frontier(
        [
            _pipeline_with_ci("a", ndcg10=0.42, ndcg_ci=(0.35, 0.49)),
            _pipeline_with_ci("b", ndcg10=0.40, ndcg_ci=(0.33, 0.47)),
        ]
    )
    by_id = {row.pipeline_id: row for row in result.pipelines}
    assert by_id["a"].is_pareto_optimal is True
    assert by_id["b"].is_pareto_optimal is True
    assert "a" not in by_id["b"].dominated_by


def test_pareto_dominance_when_cis_dont_overlap():
    # Non-overlapping CIs — "a" is genuinely, significantly better; it should dominate.
    result = compute_pareto_frontier(
        [
            _pipeline_with_ci("a", ndcg10=0.42, ndcg_ci=(0.38, 0.46)),
            _pipeline_with_ci("b", ndcg10=0.20, ndcg_ci=(0.16, 0.24)),
        ]
    )
    by_id = {row.pipeline_id: row for row in result.pipelines}
    assert by_id["a"].is_pareto_optimal is True
    assert by_id["b"].is_pareto_optimal is False
    assert "a" in by_id["b"].dominated_by
