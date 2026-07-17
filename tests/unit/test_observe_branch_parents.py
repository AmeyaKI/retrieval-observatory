from __future__ import annotations

from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, observe, start_trace


@observe("SOURCE", op_id="gate", parent_ids=())
def gate() -> list[dict[str, object]]:
    return [{"id": "d1", "rank": 1, "score": 1.0}]


@observe("SOURCE", op_id="optional", parent_ids=("gate", "missing_branch"))
def optional_branch() -> list[dict[str, object]]:
    return [{"id": "d1", "rank": 1, "score": 1.0}]


def test_observe_omits_unfired_branch_parent_without_changing_result() -> None:
    start_trace(ObserveContext(None, "q1", "query", "pipeline", "service"))
    gate()
    result = optional_branch()
    trace = finish_trace()

    assert result == [{"id": "d1", "rank": 1, "score": 1.0}]
    assert trace.span("optional").parent_ids == ("gate",)
    assert set(trace.span("optional").input_groups) == {"gate"}
