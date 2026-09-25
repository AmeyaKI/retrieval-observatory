# Reviewing `retobs/integration-plan.json`

The planner proposes; you decide. Work through the plan top to bottom, then re-plan from the
reviewed file (`retobs integrate . --phase plan --plan retobs/integration-plan.json --output
retobs/integration-plan.json`) so patches, actions, and `expected_capabilities` are regenerated
from what you reviewed.

## Operators

For each entry in `operators`:

- `op_id` is the stable identity the dashboard shows; keep it short and meaningful
  (`bm25`, `dense`, `rrf_fusion`, `recency_filter`, `rerank`). Renaming is fine before apply.
- `op_type` must reflect the role, not the name: a function called `filter_results` that reorders
  is a `RERANK`; a function that maps chunks to documents is a `TRANSFORM`.
- `parent_ids` are the operators whose outputs this one receives. Method calls and cross-module
  calls are not inferred, so fill them in from your reading of the code. A `SOURCE` has no parents.
- `input_mapping` is what the runtime capture rules will do with the actual arguments:
  - `query:<param>` for a source receiving the query text;
  - `parameters:<a,b>` when the operator's parameters are named exactly like its parents;
  - `parameter:<name>` for one candidate-list parameter;
  - `positional_lanes:<name>` for one argument holding one list per parent (`*lanes`): the lanes are
    read from the call but matched to parents by position, which verify reports as `inferred_inputs`
    (partial); add a `capture` spec for an exact mapping;
  - `capture` when `capture` names an adapter spec;
  - `default` or `unavailable` means the planner could not tell: either rename nothing and let
    verify report it, or add a `capture` reference now.
- `output_mapping`: `return` reads the returned sequence (or its `.documents` attribute, or a
  mapping's `documents` key); `capture` uses the adapter; `unavailable` means no return value.
- `capture`: `retobs_adapter:<symbol>` where `<symbol>` is a module-level `CaptureSpec` in the
  project's root `retobs_adapter.py` (see `retobs_adapter_example.py`).
- `symbol` / `relative_path` must exist; a missing symbol becomes `unresolved` on re-plan.

Remove entries that are not operators (helpers that build a retriever, request parsing). Add
operators the planner missed, especially custom filters and post-processing between the last
retrieval stage and the returned result.

## Boundary and identity

- `boundary.kind`: `entrypoint_return` (the entrypoint's returned value is what is evaluated),
  `operator_output` (the last operator's output is; set `op_id`), or `unresolved`.
- `identity.candidate_id_field`: the attribute or key that holds the stable id.
- `identity.unit`: `document` or `chunk`; with chunk results and document labels, plan for
  `--chunk-map` at evaluation time.
- `identity.query_id`: `argument:<name>` when the entrypoint receives a query id, otherwise
  `hash:query_text` (the trace's query id is a hash of the text).

## Scenarios

One scenario per declared route, each with:

- `query_text`: a real query that takes that route;
- `expected_operator_ids`: the operators that fire on that route (a skipped lane is absent);
- `route`: the gate's `selected_route` value when the pipeline has a gate;
- `command`: the exact command that calls the entrypoint with that query from the project root.

Keep `representative` and `representative-repeat` (same query twice): the repeat is what
`cross_run_entity_alignment` is verified against.

## Judgments

`judgments.queries`, `judgments.qrels`, `judgments.corpus` are project-relative paths. Set
`status: resolved` when queries and qrels are present. Without labels, verify reports
`judgment_mapping: unavailable` and candidate movement inspection still works.

## Example: a reviewed operator with parents and an adapter capture

```json
{
  "op_id": "rerank",
  "op_type": "RERANK",
  "symbol": "Reranker.rerank",
  "relative_path": "app/rerank.py",
  "parent_ids": ["rrf_fusion"],
  "confidence": 1.0,
  "input_mapping": "capture",
  "output_mapping": "capture",
  "capture": "retobs_adapter:rerank_capture",
  "invocation": "sync"
}
```
