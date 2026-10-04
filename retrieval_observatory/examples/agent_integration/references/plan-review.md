# Reviewing `retobs/integration-plan.json`

The planner proposes; you decide. Work through the plan top to bottom, then re-plan from the
reviewed file (`retobs integrate . --phase plan --plan retobs/integration-plan.json --output
retobs/integration-plan.json`) so patches, actions, and `expected_capabilities` are regenerated
from what you reviewed.

## Watched or guessed

`discovery.method` says where the operators came from:

- `watched`: `retobs integrate . --phase plan --watch "<command>"` ran each command once and
  proposed the functions that actually handed back documents. Each step's kind comes from what it
  did to the documents, its `parent_ids` from whose documents it received, the entrypoint from
  where the search started, and the scenarios from the commands. `discovery.watch` holds what was
  watched: `commands`, `searches_seen`, `steps` (each with `took`, `returned`, `inside` for inner
  functions folded into it, and `notes`), `conditional` (steps only some commands ran), `chooser`
  (the function proposed as the `GATE`), `unmarkable` (lambdas and nested functions that cannot
  carry a decorator) and `notes` (for example a change the entrypoint made itself, such as a
  `results[:k]` cut). Each operator's `notes` repeat its watched counts and which parameter each
  parent fed.
- `guessed`: the operators are name matches, as described below.
  `discovery.watch_fallback_reason` says why a watch fell back to guessing.

Re-planning keeps `method`, `watch`, `watch_fallback_reason` and the `not_seen_in_watch` and
`folded_into_step` entries, but not the watch's open questions: answer those from the first plan.
A step whose documents are one element of what it returns (a `(kept, dropped, ...)` tuple) comes
with a ready line for `retobs_adapter.py`, such as
`screen_capture = CaptureSpec(outputs=lambda result: result[0])`, and the `capture` value to set.
So does a step whose parents' documents arrive in parameters not named after them, or inside one
tuple or dict argument, with an `inputs` mapping keyed by parent, such as
`inputs=lambda bound: {"keyword_search": bound.arguments["keyword_hits"], ...}`. A step that needs
both gets one `CaptureSpec(inputs=..., outputs=...)`. Until those lines are in place,
`expected_capabilities.actual_input_output_capture` is `partial`. When the watched entrypoint took
no query-named argument, the scenarios carry the placeholder query text and an open question asks
for the real one.

## Operators

For each entry in `operators`:

- `op_id` is the stable identity the dashboard shows; keep it short and meaningful
  (`bm25`, `dense`, `rrf_fusion`, `recency_filter`, `rerank`). Renaming is fine before apply.
- `op_type` must reflect the role, not the name: a function called `filter_results` that reorders
  is a `RERANK`; a function that maps chunks to documents is a `TRANSFORM`.
- `parent_ids` are the operators whose outputs this one receives. A watched plan takes them from
  the documents that flowed; a guessed plan infers no method calls or cross-module calls, so fill
  them in from your reading of the code. A `SOURCE` has no parents.
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
  Each side says `capture` only when the referenced `CaptureSpec` maps it: a spec with only
  `inputs` leaves `output_mapping: return` (outputs come from the default return-value capture).
- `notes` (on the plan and on each operator): free text for your rationale and answers to open
  questions; re-planning keeps it verbatim.
- `capture`: `retobs_adapter:<symbol>` where `<symbol>` is a module-level `CaptureSpec` in the
  project's root `retobs_adapter.py` (see `retobs_adapter_example.py`).
- `symbol` / `relative_path` must exist; a missing symbol becomes `unresolved` on re-plan.

Remove entries that are not operators (helpers that build a retriever, request parsing). Add
operators the planner missed, especially custom filters and post-processing between the last
retrieval stage and the returned result.

Name matches the planner left out are in `discovery.low_confidence_operators`, each with a
`reason`: `not_seen_in_watch` (a watched plan: the watched searches never ran it),
`folded_into_step` (a watched plan: it ran inside the watched step named in `step`, on documents
that step made itself, and is listed in that step's `inside`),
`unreachable_from_entrypoint` (no import path from the entrypoint reaches the file),
`non_runtime_dir` (under a bench, eval, report, script, notebook, fixture, example or experiment
directory), `not_operator_shape` (a predicate, factory or formatter: `is_`/`get_`/`format_`...
prefixes, scalar or boolean returns, or a gate without a query or candidates); no reason means only
the name matched. Move a real operator from there into `operators`. When no discovered operator
is reachable from the entrypoint, the plan proposes none and lists that under `unresolved`: set
`discovery.entrypoint` to the function that runs the pipeline, or list the operators yourself.
Operators sharing a symbol name in different modules get module-qualified `op_id`s
(`<module>__<symbol>`); apply refuses a plan with duplicate `op_id`s.

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
  A generated command puts the entrypoint's import root on `sys.path` first when its package does
  not sit at the project root (`import sys; sys.path.insert(0, 'services/search'); ...`). In a
  layout with no `__init__.py` (a directory on `PYTHONPATH`), that root comes from the entrypoint's
  own absolute imports: `apps/py/ticket_rag/pipeline.py` importing `ticket_rag.fusion` has root `apps/py`.

Generated scenarios use the first query of the judgments' queries file; without one that loads,
`query_text` is a placeholder and `open_questions` asks for a real query.

Keep `representative` and `representative-repeat` (same query twice): the repeat is what
`cross_run_entity_alignment` is verified against.

## Judgments

`judgments.queries`, `judgments.qrels`, `judgments.corpus` are project-relative paths. The planner
prefers a directory holding both queries and qrels and loads them the way `retobs evaluate` does:
`resolved` means they load, some qrels query ids are queries, and every judged doc id is in a
non-empty corpus; `candidate` means files were found but a check failed (`notes` says which);
`unresolved` means queries or qrels are missing. Anything but `resolved` adds an open question;
after fixing the paths, set `status: resolved` yourself (re-planning keeps `judgments` as written).
Without labels, verify reports `judgment_mapping: unavailable` and candidate movement inspection
still works.

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
