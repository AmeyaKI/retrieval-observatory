"""``build_candidate_transition`` output ranks: first matching output row wins, as an output-order scan finds it."""

from __future__ import annotations

from retrieval_observatory.tracing.candidates import build_candidate_transition, to_candidates


class _Node:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def _ranks(transition) -> dict[str, list[int | None]]:
    ranks: dict[str, list[int | None]] = {}
    for candidates in transition.input_groups.values():
        for candidate in candidates:
            ranks.setdefault(str(candidate.candidate_id), []).append(candidate.output_rank)
    return ranks


def test_an_input_named_by_several_output_rows_takes_the_first_rows_rank() -> None:
    inputs = to_candidates([{"doc_id": "a", "candidate_id": "kb:a"}, {"doc_id": "b", "candidate_id": "kb:b"}], "src")
    outputs = [
        {"doc_id": "x", "candidate_id": "kb:x", "parent_candidate_ids": ["kb:b"], "rank": 1},  # b as a parent first
        {"doc_id": "b", "candidate_id": "kb:b", "rank": 2},  # then b itself
        {"doc_id": "a", "candidate_id": "kb:a", "rank": 3},
        {"doc_id": "a", "candidate_id": "kb:a", "rank": 4},  # duplicate output row
    ]
    transition = build_candidate_transition(input_groups={"src": inputs}, output_items=outputs, op_id="op", op_type="EXPAND")
    assert _ranks(transition) == {"kb:a": [3], "kb:b": [1]}


def test_duplicate_inputs_across_groups_share_the_first_matching_rank() -> None:
    dense = to_candidates([{"doc_id": "a", "candidate_id": "kb:a"}, {"doc_id": "b", "candidate_id": "kb:b"}], "dense")
    lexical = to_candidates([{"doc_id": "b", "candidate_id": "kb:b"}, {"doc_id": "c", "candidate_id": "kb:c"}], "lexical")
    outputs = [{"doc_id": "b", "candidate_id": "kb:b", "rank": 1}, {"doc_id": "a", "candidate_id": "kb:a", "rank": 2}]
    transition = build_candidate_transition(
        input_groups={"dense": dense, "lexical": lexical}, output_items=outputs, op_id="fuse", op_type="FUSE", decision_reasons={"kb:c": "cutoff"}
    )
    assert _ranks(transition) == {"kb:a": [2], "kb:b": [1, 1], "kb:c": [None]}
    dropped = transition.input_groups["lexical"][1]
    assert (dropped.drop_reason, dropped.decision_reason, dropped.decision_evidence) == ("cutoff", "cutoff", "recorded")


def test_doc_id_fallback_uses_the_first_identity_less_row_and_ignores_rows_with_known_ids_or_parents() -> None:
    inputs = to_candidates([{"doc_id": "a", "candidate_id": "kb:a"}, {"doc_id": "z", "candidate_id": "kb:z"}], "src")
    outputs = [
        {"doc_id": "a", "candidate_id": "kb:z", "rank": 1},  # a known input id: never a doc-id match for kb:a
        {"doc_id": "a", "parent_candidate_ids": ["kb:z"], "rank": 2},  # has parents: not a doc-id match either
        _Node(doc_id="a", score=0.5, rank=3),  # identity-less object row: the first doc-id match
        {"doc_id": "a", "rank": 4},
    ]
    transition = build_candidate_transition(input_groups={"src": inputs}, output_items=outputs, op_id="op", op_type="TRANSFORM")
    assert _ranks(transition) == {"kb:a": [3], "kb:z": [1]}


def test_node_with_score_objects_are_read_through_their_node() -> None:
    (candidate,) = to_candidates([_Node(node=_Node(node_id="n-1", metadata={}), score=0.25)], "src")
    assert (candidate.doc_id, candidate.score, candidate.rank, candidate.identity_evidence) == ("n-1", 0.25, 1, "recorded")
