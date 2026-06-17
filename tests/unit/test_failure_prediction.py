from retrieval_observatory.metrics.diagnostics import predict_retrieval_risks


def test_predict_retrieval_risks_temporal():
    risks = predict_retrieval_risks("compare the 2022 and 2024 pricing policy")
    assert "temporal_sensitivity" in risks or "comparison_query" in risks
