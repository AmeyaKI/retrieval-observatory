"""Unit tests for the watch analysis: kinds by behaviour, links by data flow, wrappers, lanes,
bundles, threads, routes and unmarkable functions, on synthetic watch records."""
from __future__ import annotations

from retrieval_observatory.integrations.watch_map import build_watch_map


def docs(*ids: str, strings: bool = False) -> dict:
    return {"candidates": {"count": len(ids), "ids": list(ids), "container": "list",
                           "item_type": "str" if strings else "Hit", "ids_are_strings": strings}}


def param(name: str, *ids: str, strings: bool = False) -> dict:
    return {"param": name, **docs(*ids, strings=strings)}


def call(id: int, symbol: str, start: int, end: int, *, parent: int | None = None, path: str = "app/pipeline.py",
         inputs: tuple = (), output: dict | None = None, text: tuple[str, str] | None = None,
         scalars: tuple = (), callable: str = "function", thread: str = "MainThread") -> dict:
    head = [{"param": text[0], "text": text[1]}] if text else []
    return {"id": id, "parent": parent, "thread": thread, "symbol": symbol, "path": path, "line": 1,
            "callable": callable, "start": start, "end": end, "inputs": [*head, *inputs], "output": output,
            "error": None, "ms": 0.1, "scalar_children": list(scalars)}


def payload(*commands: list[dict]) -> dict:
    return {"schema_version": 1, "commands": [
        {"command": f"cmd{index}", "exit_code": 0, "failure": None,
         "processes": [{"schema_version": 1, "mechanism": "monitoring", "python": "3.12.0", "command": f"cmd{index}",
                        "calls": calls, "truncated": False, "notes": []}]}
        for index, calls in enumerate(commands)
    ]}


HYBRID = [
    call(2, "lexical", 2, 3, parent=1, text=("query", "q"), output=docs("a", "b", "c")),
    call(3, "dense", 4, 5, parent=1, text=("query", "q"), output=docs("b", "d")),
    call(4, "merge_lanes", 6, 7, parent=1, inputs=(param("lex_hits", "a", "b", "c"), param("dense_hits", "b", "d")),
         output=docs("a", "b", "d", "c")),
    call(5, "screen", 8, 9, parent=1, inputs=(param("items", "a", "b", "d", "c"),), output=docs("a", "d", "c")),
    call(6, "order", 10, 11, parent=1, inputs=(param("hits", "a", "d", "c"),), output=docs("d", "a", "c")),
    call(1, "retrieve", 1, 12, text=("query", "q"), output=docs("d", "a")),
]


def steps_by_symbol(watch):
    return {step.symbol: step for step in watch.steps}


def test_kinds_come_from_behaviour_and_links_from_data_flow() -> None:
    watch = build_watch_map(payload(HYBRID))
    steps = steps_by_symbol(watch)
    assert watch.entrypoint == {"file": "app/pipeline.py", "symbol": "retrieve", "kind": "function"}
    assert watch.query_parameter == "query" and watch.query_texts == ("q",)
    assert {symbol: step.op_type for symbol, step in steps.items()} == {
        "lexical": "SOURCE", "dense": "SOURCE", "merge_lanes": "FUSE", "screen": "FILTER", "order": "RERANK",
    }
    assert steps["merge_lanes"].parent_ids == ("lexical", "dense")
    assert steps["merge_lanes"].inputs_from == (("lex_hits", "lexical"), ("dense_hits", "dense"))
    assert steps["screen"].parent_ids == ("merge_lanes",)
    assert steps["order"].parent_ids == ("screen",)
    assert (steps["screen"].took, steps["screen"].returned) == (4, 3)
    assert watch.searches_seen == 1
    assert any("retrieve changed the documents itself after order (3 → 2)" in note for note in watch.notes)


def test_a_pass_through_wrapper_is_not_a_step_and_links_resolve_through_it() -> None:
    calls = [
        call(3, "lexical", 3, 4, parent=2, output=docs("a", "b")),
        call(4, "dense", 5, 6, parent=2, output=docs("b", "c")),
        call(5, "merge_lanes", 7, 8, parent=2, inputs=(param("x", "a", "b"), param("y", "b", "c")), output=docs("b", "a", "c")),
        call(2, "hybrid", 2, 9, parent=1, output=docs("b", "a", "c")),
        call(6, "screen", 10, 11, parent=1, inputs=(param("items", "b", "a", "c"),), output=docs("b", "c")),
        call(1, "retrieve", 1, 12, text=("query", "q"), output=docs("b", "c")),
    ]
    steps = steps_by_symbol(build_watch_map(payload(calls)))
    assert "hybrid" not in steps
    assert steps["screen"].parent_ids == ("merge_lanes",)


def test_a_lane_that_creates_documents_itself_folds_its_inner_steps() -> None:
    calls = [
        call(3, "trim", 3, 4, parent=2, inputs=(param("candidates", "x", "y", "z"),), output=docs("x", "y")),
        call(2, "keyword_lane", 2, 5, parent=1, text=("query", "q"), output=docs("x", "y")),
        call(1, "retrieve", 1, 6, text=("query", "q"), output=docs("x", "y")),
    ]
    watch = build_watch_map(payload(calls))
    steps = steps_by_symbol(watch)
    assert set(steps) == {"keyword_lane"}
    assert steps["keyword_lane"].op_type == "SOURCE"
    assert steps["keyword_lane"].inside == ("trim took 3 returned 2",)


def test_bundle_output_names_the_element_the_next_step_used() -> None:
    calls = [
        call(2, "lexical", 2, 3, parent=1, output=docs("a", "b", "c")),
        call(3, "screen", 4, 5, parent=1, inputs=(param("items", "a", "b", "c"),),
             output={"bundle": [{"index": 0, **docs("a", "c")}, {"index": 1, **docs("b")}]}),
        call(4, "order", 6, 7, parent=1, inputs=(param("hits", "a", "c"),), output=docs("c", "a")),
        call(1, "retrieve", 1, 8, text=("query", "q"), output=docs("c", "a")),
    ]
    steps = steps_by_symbol(build_watch_map(payload(calls)))
    assert steps["screen"].output_bundle == "index:0"
    assert steps["screen"].op_type == "FILTER"
    assert steps["order"].parent_ids == ("screen",)


def test_string_lists_count_only_when_their_ids_are_document_ids() -> None:
    calls = [
        call(2, "tokenize", 2, 3, parent=1, text=("query", "the cat"), output=docs("the", "cat", strings=True)),
        call(3, "lexical", 4, 5, parent=1, inputs=(param("terms", "the", "cat", strings=True),), output=docs("a", "b")),
        call(1, "retrieve", 1, 6, text=("query", "the cat"), output=docs("a", "b")),
    ]
    steps = steps_by_symbol(build_watch_map(payload(calls)))
    assert set(steps) == {"lexical"}
    assert steps["lexical"].op_type == "SOURCE"


def test_plain_string_ids_count_when_they_flow_between_steps() -> None:
    calls = [
        call(2, "lexical", 2, 3, parent=1, output=docs("d1", "d2", "d3", strings=True)),
        call(3, "screen", 4, 5, parent=1, inputs=(param("ids", "d1", "d2", "d3", strings=True),), output=docs("d1", "d3", strings=True)),
        call(1, "retrieve", 1, 6, text=("query", "q"), output=docs("d1", "d3", strings=True)),
    ]
    steps = steps_by_symbol(build_watch_map(payload(calls)))
    assert {symbol: step.op_type for symbol, step in steps.items()} == {"lexical": "SOURCE", "screen": "FILTER"}


def test_a_step_that_changed_nothing_has_no_behavioural_kind() -> None:
    calls = [
        call(2, "lexical", 2, 3, parent=1, output=docs("a", "b")),
        call(3, "order", 4, 5, parent=1, inputs=(param("hits", "a", "b"),), output=docs("a", "b")),
        call(1, "retrieve", 1, 6, text=("query", "q"), output=docs("a", "b")),
    ]
    steps = steps_by_symbol(build_watch_map(payload(calls)))
    assert steps["order"].op_type is None
    assert any("changed nothing" in note for note in steps["order"].notes)


def test_new_ids_make_a_transform() -> None:
    calls = [
        call(2, "find_passages", 2, 3, parent=1, output=docs("d1#1", "d1#2", "d2#1")),
        call(3, "to_documents", 4, 5, parent=1, inputs=(param("passages", "d1#1", "d1#2", "d2#1"),), output=docs("d1", "d2")),
        call(1, "retrieve", 1, 6, text=("query", "q"), output=docs("d1", "d2")),
    ]
    steps = steps_by_symbol(build_watch_map(payload(calls)))
    assert steps["to_documents"].op_type == "TRANSFORM"
    assert steps["to_documents"].parent_ids == ("find_passages",)


def test_steps_on_other_threads_inside_the_search_window_belong_to_that_search() -> None:
    calls = [
        call(2, "lane_a", 2, 3, thread="worker-0", output=docs("a", "b")),
        call(3, "lane_b", 4, 5, thread="worker-1", output=docs("b", "c")),
        call(4, "merge_lanes", 6, 7, parent=1, inputs=(param("a", "a", "b"), param("b", "b", "c")), output=docs("b", "a", "c")),
        call(1, "retrieve", 1, 8, text=("query", "q"), output=docs("b", "a", "c")),
    ]
    watch = build_watch_map(payload(calls))
    assert watch.searches_seen == 1
    assert steps_by_symbol(watch)["merge_lanes"].parent_ids == ("lane_a", "lane_b")


def test_two_paths_mark_conditional_steps_and_the_chooser() -> None:
    keyword = [
        call(2, "lexical", 2, 3, parent=1, output=docs("a", "b")),
        call(1, "retrieve", 1, 4, text=("query", "q1"), output=docs("a", "b"),
             scalars=({"symbol": "pick_route", "path": "app/route.py", "line": 1, "value": "keyword"},)),
    ]
    hybrid = [
        call(2, "lexical", 2, 3, parent=1, output=docs("a", "b")),
        call(3, "dense", 4, 5, parent=1, output=docs("b", "c")),
        call(4, "merge_lanes", 6, 7, parent=1, inputs=(param("x", "a", "b"), param("y", "b", "c")), output=docs("b", "a", "c")),
        call(1, "retrieve", 1, 8, text=("query", "q2"), output=docs("b", "a", "c"),
             scalars=({"symbol": "pick_route", "path": "app/route.py", "line": 1, "value": "hybrid"},)),
    ]
    watch = build_watch_map(payload(keyword, hybrid))
    assert set(watch.conditional) == {"dense", "merge_lanes"}
    assert watch.chooser == {"symbol": "pick_route", "relative_path": "app/route.py", "values": {"0": "keyword", "1": "hybrid"}}
    gate = steps_by_symbol(watch)["pick_route"]
    assert gate.op_type == "GATE" and gate.relative_path == "app/route.py"
    assert watch.query_texts == ("q1", "q2")


def test_nested_functions_are_listed_as_unmarkable() -> None:
    calls = [
        call(2, "retrieve.<locals>.helper", 2, 3, parent=1, callable="nested", output=docs("a", "b")),
        call(3, "screen", 4, 5, parent=1, inputs=(param("items", "a", "b"),), output=docs("a")),
        call(1, "retrieve", 1, 6, text=("query", "q"), output=docs("a")),
    ]
    watch = build_watch_map(payload(calls))
    assert set(steps_by_symbol(watch)) == {"screen"}
    assert watch.unmarkable == ({"symbol": "retrieve.<locals>.helper", "relative_path": "app/pipeline.py",
                                 "reason": "a nested function or lambda cannot carry a decorator"},)
    assert steps_by_symbol(watch)["screen"].parent_ids == ()
    assert steps_by_symbol(watch)["screen"].notes == (
        "items came from retrieve.<locals>.helper, which cannot carry a decorator; its documents enter here unlinked",
    )


def test_same_names_in_two_modules_get_distinct_op_ids() -> None:
    calls = [
        call(2, "search", 2, 3, parent=1, path="app/lanes/keyword.py", output=docs("a", "b")),
        call(3, "search", 4, 5, parent=1, path="app/lanes/vector.py", output=docs("b", "c")),
        call(4, "merge_lanes", 6, 7, parent=1, inputs=(param("x", "a", "b"), param("y", "b", "c")), output=docs("b", "a", "c")),
        call(1, "retrieve", 1, 8, text=("query", "q"), output=docs("b", "a", "c")),
    ]
    watch = build_watch_map(payload(calls))
    assert {step.op_id for step in watch.steps} == {"keyword_search", "vector_search", "merge_lanes"}
    merge = next(step for step in watch.steps if step.symbol == "merge_lanes")
    assert merge.parent_ids == ("keyword_search", "vector_search")


def test_failed_commands_and_truncation_are_noted() -> None:
    data = payload(HYBRID)
    data["commands"][0]["failure"] = "exit code 1: boom"
    data["commands"][0]["processes"][0]["truncated"] = True
    watch = build_watch_map(data)
    assert any("cmd0" in note and "boom" in note for note in watch.notes)
    assert any("stopped recording" in note for note in watch.notes)


def test_no_steps_means_no_entrypoint() -> None:
    watch = build_watch_map(payload([call(1, "main", 1, 2)]))
    assert watch.steps == () and watch.entrypoint is None and watch.searches_seen == 0


def test_a_lane_that_trims_its_own_documents_stays_a_step_when_another_lane_found_the_same_ones() -> None:
    calls = [
        call(2, "keyword_search", 2, 3, parent=1, output=docs("a", "b", "c")),
        call(4, "trim", 5, 6, parent=3, inputs=(param("candidates", "a", "c", "b"),), output=docs("a", "c")),
        call(3, "vector_search", 4, 7, parent=1, output=docs("a", "c")),
        call(5, "merge_lanes", 8, 9, parent=1, inputs=(param("x", "a", "b", "c"), param("y", "a", "c")), output=docs("a", "c", "b")),
        call(1, "retrieve", 1, 10, text=("query", "q"), output=docs("a", "c", "b")),
    ]
    steps = steps_by_symbol(build_watch_map(payload(calls)))
    assert set(steps) == {"keyword_search", "vector_search", "merge_lanes"}
    assert steps["vector_search"].op_type == "SOURCE"
    assert steps["vector_search"].inside == ("trim took 3 returned 2",)
    assert steps["merge_lanes"].parent_ids == ("keyword_search", "vector_search")


def test_lanes_running_at_the_same_time_on_two_threads_are_both_steps() -> None:
    calls = [
        call(3, "lane_b", 3, 4, thread="worker-1", output=docs("b", "c")),
        call(2, "lane_a", 2, 5, thread="worker-0", output=docs("a", "b")),
        call(4, "merge_lanes", 6, 7, parent=1, inputs=(param("a", "a", "b"), param("b", "b", "c")), output=docs("b", "a", "c")),
        call(1, "retrieve", 1, 8, text=("query", "q"), output=docs("b", "a", "c")),
    ]
    watch = build_watch_map(payload(calls))
    assert watch.searches_seen == 1
    steps = steps_by_symbol(watch)
    assert set(steps) == {"lane_a", "lane_b", "merge_lanes"}
    assert steps["merge_lanes"].parent_ids == ("lane_a", "lane_b")


def test_pool_lanes_inside_a_wrapper_keep_their_own_trims_and_feed_its_merge() -> None:
    calls = [
        call(5, "trim", 5, 6, parent=3, thread="worker-0", inputs=(param("candidates", "a", "b", "c"),), output=docs("a", "b")),
        call(6, "trim", 7, 9, parent=4, thread="worker-1", inputs=(param("candidates", "b", "a", "c"),), output=docs("b", "a")),
        call(4, "lane_vectors", 4, 10, thread="worker-1", output=docs("b", "a")),
        call(3, "lane_terms", 3, 11, thread="worker-0", output=docs("a", "b")),
        call(7, "merge_lanes", 12, 13, parent=2, inputs=(param("x", "a", "b"), param("y", "b", "a")), output=docs("a", "b")),
        call(2, "hybrid", 2, 14, parent=1, output=docs("a", "b")),
        call(8, "screen", 15, 16, parent=1, inputs=(param("items", "a", "b"),), output=docs("a")),
        call(1, "retrieve", 1, 17, text=("query", "q"), output=docs("a")),
    ]
    steps = steps_by_symbol(build_watch_map(payload(calls)))
    assert {symbol: step.op_type for symbol, step in steps.items()} == {
        "lane_terms": "SOURCE", "lane_vectors": "SOURCE", "merge_lanes": "FUSE", "screen": "FILTER",
    }
    assert steps["lane_terms"].inside == steps["lane_vectors"].inside == ("trim took 3 returned 2",)
    assert steps["merge_lanes"].parent_ids == ("lane_terms", "lane_vectors")
    assert steps["screen"].parent_ids == ("merge_lanes",)


def test_a_comprehension_is_part_of_the_function_that_holds_it() -> None:
    # Python 3.10 records the frame as "<listcomp>", 3.11 as "screen.<locals>.<listcomp>"; 3.12 inlines it.
    for symbol, kind in (("<listcomp>", "function"), ("screen.<locals>.<listcomp>", "nested")):
        calls = [
            call(2, "lexical", 2, 3, parent=1, output=docs("a", "b", "c")),
            call(4, symbol, 5, 6, parent=3, callable=kind, output=docs("a", "c")),
            call(3, "screen", 4, 7, parent=1, inputs=(param("items", "a", "b", "c"),), output=docs("a", "c")),
            call(1, "retrieve", 1, 8, text=("query", "q"), output=docs("a", "c")),
        ]
        watch = build_watch_map(payload(calls))
        steps = steps_by_symbol(watch)
        assert set(steps) == {"lexical", "screen"} and steps["screen"].op_type == "FILTER"
        assert steps["screen"].parent_ids == ("lexical",) and watch.unmarkable == ()


def test_counts_are_the_recorded_counts_not_the_ids_kept() -> None:
    def many(count: int, *ids: str) -> dict:
        summary = docs(*ids)
        summary["candidates"]["count"] = count
        return summary

    calls = [
        call(2, "lexical", 2, 3, parent=1, output=many(3000, "a", "b", "c")),
        call(3, "screen", 4, 5, parent=1, inputs=({"param": "items", **many(3000, "a", "b", "c")},), output=many(2000, "a", "b")),
        call(1, "retrieve", 1, 6, text=("query", "q"), output=many(10, "a")),
    ]
    watch = build_watch_map(payload(calls))
    screen = steps_by_symbol(watch)["screen"]
    assert (screen.took, screen.returned) == (3000, 2000)
    assert any("after screen (2000 → 10)" in note for note in watch.notes)


def test_a_loader_that_ran_before_the_search_is_not_the_entrypoint() -> None:
    calls = [
        call(1, "load_corpus", 1, 2, output=docs("a", "b", "c")),
        call(3, "lexical", 4, 5, parent=2, output=docs("a", "b")),
        call(2, "retrieve", 3, 6, text=("query", "q"), output=docs("a", "b")),
    ]
    watch = build_watch_map(payload(calls))
    assert watch.entrypoint == {"file": "app/pipeline.py", "symbol": "retrieve", "kind": "function"}
    assert watch.query_texts == ("q",)
    assert set(steps_by_symbol(watch)) == {"lexical"}


def test_documents_handled_outside_the_search_stay_out_of_the_map() -> None:
    calls = [
        call(2, "read_files", 2, 3, parent=1, path="app/corpus.py", output=docs("a", "b", "c")),
        call(3, "drop_drafts", 4, 5, parent=1, path="app/corpus.py", inputs=(param("docs", "a", "b", "c"),), output=docs("a", "b")),
        call(1, "load_corpus", 1, 6, path="app/corpus.py", output=docs("a", "b")),
        call(5, "lexical", 8, 9, parent=4, output=docs("a", "b")),
        call(4, "retrieve", 7, 10, text=("query", "q"), output=docs("a", "b")),
    ]
    watch = build_watch_map(payload(calls))
    assert watch.entrypoint == {"file": "app/pipeline.py", "symbol": "retrieve", "kind": "function"}
    assert set(steps_by_symbol(watch)) == {"lexical"} and watch.searches_seen == 1
    assert "load_corpus (app/corpus.py) handled documents outside the search (returned 2); not part of the map" in watch.notes
