# Agent integration runbook

The human-readable counterpart of the packaged runbook `retrieval_observatory/examples/agent_integration/SKILL.md` (installed with the package; the plan phase reports its location as `discovery.runbook`, MCP `describe_integration()` as `runbook_path`). Its `references/plan-review.md` is the field-by-field review checklist and `references/retobs_adapter_example.py` a worked `CaptureSpec`. The request it serves:

> Ask your coding agent to connect retobs to this existing retrieval pipeline, run your benchmark, and open a document-flow investigation.

## Phases

| Phase | CLI (from the project root) | MCP (`retobs mcp`) |
|---|---|---|
| plan | `retobs integrate . --phase plan --watch "<command>" [--watch "<command 2>" ...] --output retobs/integration-plan.json`, one command per search path | `integrate_project(project_root, phase="plan", watch=["<command>", ...])` |
| review | edit `retobs/integration-plan.json` with your own tools (fields below) | same file |
| re-plan | `retobs integrate . --phase plan --plan retobs/integration-plan.json --output retobs/integration-plan.json` | `integrate_project(project_root, phase="plan", plan_path=...)` |
| apply | `retobs integrate . --phase apply --plan retobs/integration-plan.json` | `integrate_project(project_root, phase="apply", plan_path=...)` |
| run scenarios | every `scenario_execution` action's `command`, including the repeat | the same commands |
| verify | `retobs integrate . --phase verify --db .retobs/results.db` | `integrate_project(project_root, phase="verify", db_path=...)` |
| evaluate | the plan's `benchmark_setup` command, e.g. `retobs evaluate app/pipeline.py:retrieve --queries data/queries.jsonl --qrels data/qrels.jsonl --corpus data/corpus.jsonl --name <pipeline_id> --db .retobs/results.db` | `evaluate_file` / `evaluate` |
| investigate | `retobs serve --db .retobs/results.db`, then `#/connect?db=<db>&integration=<service_id>:<pipeline_id>`; without a browser `retobs inspect-query RUN QUERY` / `retobs inspect-document RUN ENTITY` | `inspect_query`, `inspect_document` |
| revert | `retobs integrate . --phase revert` | `integrate_project(project_root, phase="revert")` |

Install first: `pip install retrieval-observatory` (plus `[langchain]` or `[llamaindex]` when the plan's `install` action says so). MCP is a transport: it grants no filesystem access, so the plan and any adapter are edited with the agent's own tools.

## The plan is a proposal; the review is the work

Plan from what actually runs. Write one command per search path that runs one real search with the project's normal settings and exits, for example `python -c "from app.search import Searcher; Searcher().search('a real question')"`; a keyword-only path and a hybrid path are two commands. `--watch` runs each command from the project root once under an observe-only watcher (the command must start Python without `-I`, `-S` or `-E` and must not replace `PYTHONPATH`) and proposes the functions that actually handed back documents: each step's kind from what it did to them, its parents from whose documents it received, the entrypoint where the search started, and one scenario per command. Check that `discovery.method` is `watched`; `guessed` means no command ran a search that handed back documents, and `discovery.watch_fallback_reason` and the `watch:` open questions say why. `discovery.watch` holds the watched counts, `inside` (inner functions folded into a step), `conditional` steps, the proposed `chooser`, `unmarkable` functions and `notes`; name matches the watch never saw run are listed under `discovery.low_confidence_operators` with reason `not_seen_in_watch`, and those that ran folded inside a watched step with reason `folded_into_step` and that `step`. Answer the watch's open questions in this first plan (ready `CaptureSpec` lines for steps whose documents the default capture cannot read exactly, and a request for the real question when the entrypoint took no query-named argument): re-planning keeps `discovery.method`, `discovery.watch` and those entries, but not these questions. `retobs/watch.json` is a local record of the watched search. It holds hashed document ids, function names and at most the search's question text, and should not be committed.

When no search can run (it needs a service the agent may not call, or data that is not present), plan without `--watch`: the planner then finds operators by name and infers parents only from plain-name calls in the same file. A class-based or multi-module pipeline comes back with `parent_ids: []`, planner-derived ids such as `lexicallane_search`, and an honest `open_questions` list. Either way, before re-planning, make these fields true:

- `operators[]`: exactly the functions that change the candidate list, with `op_type` (`SOURCE`, `FUSE`, `FILTER`, `RERANK`, `GATE`, `EXPAND`, `TRANSFORM`), data-flow `parent_ids`, and a short stable `op_id`. Remove helpers and the entrypoint wrapper: a `retrieve(query)` that only delegates is the entrypoint (`discovery.entrypoint`), not an operator.
- `operators[].input_mapping` / `output_mapping`: how the actual boundary will be read (`query:<param>`, `parameters:<a,b>`, `parameter:<name>`, `positional_lanes:<name>`, `capture`, `default` or `unavailable`).
- `operators[].capture`: `retobs_adapter:<symbol>`, a `CaptureSpec` defined at module level in the project's root `retobs_adapter.py`, whenever the default rules cannot read a boundary: candidates inside a request object, a dict of lanes, a generator output, or lanes passed positionally (`rrf_fusion(*lanes)`), which verify otherwise reports as `inferred_inputs`. Capture is observational and never raises into the application.
- `boundary` (where the evaluated output leaves the code), `identity` (`candidate_id_field`, `unit`, `namespace`, `query_id`), `judgments` (queries, qrels, corpus paths; `status: resolved`).
- `scenarios[]`: one per route with `query_text`, `expected_operator_ids`, `route` for gated paths, and a runnable `command`; keep the repeat of one query, which is what `cross_run_entity_alignment` compares.
- `open_questions`: answer each one; a step whose documents are one element of what it returns (a `(kept, dropped, ...)` tuple) comes with a ready `CaptureSpec(outputs=...)` line for `retobs_adapter.py`.
- `unresolved` must be empty before apply; `open_questions` may remain and become reported limitations.

The re-plan takes the reviewed operators, scenarios, identity, judgments and entrypoint verbatim and regenerates the patches, actions, `expected_capabilities` and `open_questions` from them.

## What apply edits, and revert

Apply writes only the files listed in `patches`: `@observe(op_type, op_id=..., parent_ids=...)` on each operator, `@trace_scope(service_id, pipeline_id, db_path=...)` on the entrypoint, one `from retrieval_observatory.sdk.observe import ...` line, `import retobs_adapter` where a capture is referenced, and the marker comment `# retobs instrumentation: added by 'retobs integrate --phase apply'; remove with '--phase revert'`. It refuses before writing anything on a changed file (`stale integration plan: <file>`), an already-applied plan (`already applied (manifest present)`), a `capture` symbol the adapter does not define, or a patch that would not compile. The pre-apply bytes go to `retobs/integration.yaml`; `--phase revert` restores exactly those files and removes the manifest, and refuses if one of them changed after apply (`retobs/integration-plan.json` is kept).

Calling the entrypoint records one trace per call to `db_path` (relative paths are anchored at the project root). Return values, order and exceptions are unchanged; a capture problem is recorded on the trace, never raised. `trace_scope` is a no-op when a trace is already active (`instrument_fastapi`, a framework callback, `retobs evaluate`), so the operator spans join that trace instead of nesting.

## Verify: the eight capabilities

Verify reads `retobs/integration.yaml` and the traces of the manifest's `service_id`/`pipeline_id`. Each capability reports `status`, `evidence` counts, `scope` and `failures[]` (`code`, `detail`, `fix`, `op_id`). `ready` means everything checked passed; `partial` means some did and the failures name what is missing (a limitation, not a defect); `unavailable` means nothing did. The overall status is `ready` only when all eight are ready, `failed` when there is no trace or a core capability (topology, query identity, candidate identity, final output) is unavailable, and `partial` otherwise. Iterate on the failure codes; an unchanged plan re-verified gives the same answer.

| Capability | Ready means | Common failure codes |
|---|---|---|
| `topology_observed` | Every trace passes the graph invariants; observed operators are declared | `parent_inputs_unrelated`, `unobserved_transition_before_return` (an operator between two observed ones is not instrumented), `undeclared_operator_observed`, `no_traces` |
| `actual_input_output_capture` | Every fired operator's inputs and outputs were read at its own boundary | `missing_actual_inputs`, `inferred_inputs` (positional lanes or parent-span reconstruction: add a `CaptureSpec`), `output_capture_unavailable` |
| `candidate_identity` | Non-empty stable ids, positive ranks, unique ids per output | `blank_candidate_ids`, `invalid_candidate_ranks`, `duplicate_candidate_ids` |
| `query_identity` | Non-empty query id and text, one text per id, unique trace ids | `missing_query_text`, `query_id_collision`, `duplicate_trace_id` |
| `final_output_capture` | Every successful trace's final output was captured | `final_boundary_missing`, `final_output_shape_unsupported` (return a sequence or a mapping with `documents`) |
| `judgment_mapping` | Judged document ids appear among observed candidates | `judgments_unavailable` (no labels; movement inspection still works), `judgment_ids_unmatched` (id field or namespace differs from the qrels) |
| `declared_route_coverage` | Every declared scenario was observed with its expected operators and route | `scenario_unobserved` (run that scenario's command) |
| `cross_run_entity_alignment` | The same query produced the same ids twice, per operator | `alignment_unverified` (run the repeat), `unstable_candidate_ids` |

Verify also persists an `integration` record per `(service_id, pipeline_id)` in the database (status, depth, capabilities, plan summary, open questions). Connect reads it at `GET /dbs/{db}/integrations/{service_id}:{pipeline_id}` and links the evaluation run named after the pipeline as the first investigation.

## Final-output-only integrations

A remote endpoint, or a single function whose internals are not inspectable, supports evaluation and final-output capture only: no internal transition is observed, so per-stage loss attribution is out of reach. The record's `depth` is `final_only` (no operator receives another's output). Report it that way; do not infer internals the traces did not show.

## Measured support boundary

The loop is exercised against an installed wheel on the fixtures under `tests/external_projects/` (`scripts/smoke_external_project.py --wheel <wheel> --fixture all`; the release check requires every fixture to reach `ready` on all eight capabilities): a plain Python callable, a FastAPI hybrid DAG with a gate, a LangChain retriever, a LlamaIndex retriever, and a class-based multi-module hybrid pipeline with a conditional route, async fan-in and positional-lane fusion captured through `retobs_adapter.py`. Each fixture's `expected.json` carries the review as `plan_overrides`, and `tests/integration/test_agent_integration_workflow.py` runs the multi-module fixture through plan, review, re-plan, apply, the scenario commands, verify with all eight capabilities ready, `retobs evaluate`, the Connect record and revert. That inventory is the support boundary: an agent trial on an unfamiliar repository has not been recorded yet.

`retobs evaluate` exits 1 when no query completed and prints the first failure's traceback tail; `--format json` gives the machine-readable report with `evidence_health`.
