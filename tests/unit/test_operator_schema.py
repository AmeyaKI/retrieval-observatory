import pytest

from retrieval_observatory.config.operators import FilterSpec, FuseSpec, parse_pipeline_graph


def test_fuse_requires_two_parents() -> None:
    raw = {
        "pipeline_id": "hybrid",
        "operators": [
            {"op_id": "dense", "op_type": "SOURCE", "parents": [], "adapter": "dense"},
            {"op_id": "fuse", "op_type": "FUSE", "parents": ["dense"], "method": "rrf"},
        ],
        "final_operator_ids": ["fuse"],
    }
    with pytest.raises(ValueError, match="FUSE requires at least two parents"):
        parse_pipeline_graph(raw)


def test_filter_does_not_accept_rerank_configuration() -> None:
    raw = {
        "pipeline_id": "filtered",
        "operators": [
            {"op_id": "source", "op_type": "SOURCE", "parents": [], "adapter": "dense"},
            {"op_id": "filter", "op_type": "FILTER", "parents": ["source"], "adapter": "reranker"},
        ],
        "final_operator_ids": ["filter"],
    }
    with pytest.raises(ValueError, match="FILTER requires a predicate executor"):
        parse_pipeline_graph(raw)


def test_parser_returns_discriminated_specs() -> None:
    graph = parse_pipeline_graph(
        {
            "pipeline_id": "p",
            "operators": [
                {"op_id": "a", "op_type": "SOURCE", "parents": [], "adapter": "a"},
                {"op_id": "b", "op_type": "SOURCE", "parents": [], "adapter": "b"},
                {"op_id": "f", "op_type": "FUSE", "parents": ["a", "b"], "method": "rrf"},
                {"op_id": "x", "op_type": "FILTER", "parents": ["f"], "predicate": "acl"},
            ],
            "final_operator_ids": ["x"],
        }
    )
    assert isinstance(graph.operators[2], FuseSpec)
    assert isinstance(graph.operators[3], FilterSpec)
