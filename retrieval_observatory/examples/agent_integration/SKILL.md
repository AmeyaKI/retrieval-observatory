---
name: retobs-integration
description: Connect retobs (the retrieval-observatory package) to an existing retrieval or RAG pipeline in a repository and produce verified evidence of where relevant documents are lost. Use this whenever someone asks to "wire", "connect", "integrate", or "instrument" retobs or retrieval-observatory into a project, asks to run their retrieval benchmark with retobs, wants to know which stage of their retriever/reranker/fusion pipeline drops relevant documents, or mentions a document-flow investigation, even if they do not say "integration". Covers discovery, the reviewed patch plan, minimal @observe/@trace_scope edits, scenario runs, capability verification, a small labeled evaluation, and opening the investigation.
---

# Connect retobs to an existing retrieval pipeline

retobs records what each retrieval operator actually received and emitted, per query, and shows
where each relevant document was lost. Your job is to get the project from "has a pipeline" to
"has verified evidence" with the smallest reviewable change. retobs supplies the instrumentation
API, the planner, the verifier, and the investigation views; you supply the understanding of the
application: which functions are the operators, how candidates are identified, where the final
output leaves the code.

The one-sentence request this runbook serves:

> Ask your coding agent to connect retobs to this existing retrieval pipeline, run your benchmark,
> and open a document-flow investigation.

## Boundaries you keep

- **Support boundary.** Inspectable Python code: plain functions, class methods, async functions,
  FastAPI routes, LangChain retrievers, LlamaIndex retrievers. A remote HTTP endpoint that only
  returns final results supports final-output evaluation, not internal lineage. Say so rather than
  inferring internals you cannot observe.
- **Authorization boundary.** The request authorizes reading the repository, installing retobs
  into the project's environment, editing the files the plan lists, running the application's
  own retrieval function on a few queries, and running a small labeled evaluation. It does not
  authorize expensive production jobs, calls that cost money at scale, or sending data to any
  hosted service. If a scenario would do that, stop and ask.
- **Claim boundary.** "Integrated" means verify reported the capabilities; a patch that applied
  is not evidence. A final-output-only integration is useful and explicitly partial for internal
  loss debugging; report it that way.
- **Footprint.** Never create a `retobs` package or directory of Python modules inside the project
  (it would shadow the installed library). Project files retobs uses are `retobs/integration-plan.json`,
  `retobs/integration.yaml`, `.retobs/results.db`, and, only when custom extraction is needed, one
  root-level `retobs_adapter.py`.

## Workflow

Each step names the check that tells you it worked. Do not move on by assumption.

### 0. Install

```bash
pip install retrieval-observatory            # plus [langchain] or [llamaindex] when the plan says so
retobs --help
```

Check: `retobs integrate --help` prints the phases `plan | apply | verify | revert`.

### 1. Discover: read the code before planning

Find and write down, with file path and qualified symbol:

- The **entrypoint**: the function or route a query enters (`retrieve(query)`, `Searcher.search`,
  `@app.post("/search")`). Note whether it is sync or async and what it returns.
- Each **operator** the query passes through, with its type: `SOURCE` (first retrieval from an
  index), `FUSE` (merges lanes), `FILTER`, `RERANK`, `GATE` (chooses a route), `EXPAND`,
  `TRANSFORM` (changes candidate identity, e.g. chunk to document). Include custom filters and
  post-processing that change the candidate list; an operator you omit is invisible to verify
  except as an unexplained change at the next boundary.
- **Candidate identity**: which field is the stable document or chunk id (`id`, `doc_id`,
  `metadata["id"]`, `node.node_id`), whether it is a document or a chunk, and any namespace or
  corpus revision.
- **Query identity**: whether the entrypoint receives a `query_id` or only text.
- **Conditional routes**: which inputs make a gate skip a lane. Each route is a scenario.
- **Labels**: where queries, qrels, and the corpus live (JSON/JSONL), if anywhere.

Check: you can name the input and output of every operator without running the code.

### 2. Plan, then review the plan

```bash
retobs integrate . --phase plan --output retobs/integration-plan.json
```

The planner is a proposal aid: it finds operators by name and infers parents from plain-name
calls in the same file. It does not follow method calls or cross-module wiring, so a class-based
or multi-module pipeline usually comes back with missing `parent_ids` and an honest
`open_questions` list. Read the plan and fix it; that review is the part only you can do. Follow
`references/plan-review.md` for the field-by-field checklist. The fields that matter most:

| Field | What to make true |
|---|---|
| `operators[].op_type`, `parent_ids` | Exactly the operators from step 1, with their real data-flow parents |
| `operators[].input_mapping`, `output_mapping` | How the actual boundary is read (`query:<param>`, `parameter:<name>`, `positional_lanes:<name>`, `capture`, `unavailable`) |
| `operators[].capture` | `retobs_adapter:<symbol>` when the default rules cannot read an operator's inputs or outputs (see step 2b) |
| `boundary` | Where the evaluated output leaves the application |
| `identity` | Candidate id field, unit, namespace, query id source |
| `scenarios[]` | One per route, each with a runnable `command` and `route` for gated paths; keep the `representative-repeat` scenario (alignment needs the same query twice) |
| `judgments` | Paths to queries and qrels, or `unresolved` with a note |
| `unresolved` | Must be empty before apply; `open_questions` may remain and become limitations |

Re-plan from your reviewed file so the patches match the reviewed operators:

```bash
retobs integrate . --phase plan --plan retobs/integration-plan.json --output retobs/integration-plan.json
```

Check: the regenerated plan has no `unresolved` entries, every scenario has a `command`, and
`expected_capabilities` states what verify should report.

#### 2b. Custom extraction with `retobs_adapter.py`

When an operator's inputs are not a sequence argument (candidates inside a request object, a
dict of lanes, a generator) or its output is not a sequence, the default capture rules report
`unavailable`. Add a `CaptureSpec` in a root-level `retobs_adapter.py` and reference it from the
plan; see `references/retobs_adapter_example.py`. Capture is observational: it never mutates
application objects, never consumes iterators, and a failure inside it is recorded on the trace
instead of raised into the application.

### 3. Apply

```bash
retobs integrate . --phase apply --plan retobs/integration-plan.json
```

Apply edits only the files listed in `patches`: it adds `@observe(...)` to each operator,
`@trace_scope(service_id, pipeline_id, db_path=...)` to the entrypoint, one import line, and a
marker comment. It checks each file's content hash first: a file that changed since planning
refuses with `stale integration plan` (re-plan), a plan already recorded in
`retobs/integration.yaml` refuses with `already applied`, and a `capture` reference that
`retobs_adapter.py` does not define refuses before writing anything. `retobs integrate . --phase
revert` restores the pre-apply bytes of exactly those files, and refuses if any of them changed
after apply.

Check: `git diff` shows only decorators, the import, and the marker in the listed files.

### 4. Run the declared scenarios

Run every `scenario_execution` action from the plan, including the repeat. For a gated pipeline
run one scenario per route; a route no scenario exercises is reported as unobserved, not guessed.
Calling the entrypoint records and persists one trace per call to `db_path` (relative paths are
anchored at the project root). Application behavior is unchanged: return values, order, and
exceptions are preserved, and a capture problem is recorded on the trace rather than raised.

Check: the database file exists and `retobs integrate . --phase verify` no longer says
`No traces found`.

### 5. Verify

```bash
retobs integrate . --phase verify --db .retobs/results.db
```

The result has `status` (`ready | partial | failed`) and one entry per capability with
`status`, `evidence` counts, `scope`, and `failures[]` (`code`, `detail`, `fix`, `op_id`).

| Capability | Ready means | Common failure and fix |
|---|---|---|
| `topology_observed` | Every trace passes graph invariants; observed operators are declared | `parent_inputs_unrelated`, `unobserved_transition_before_return`: an operator between two observed ones is not instrumented; `undeclared_operator_observed`: add it to the plan |
| `actual_input_output_capture` | Every fired operator's inputs and outputs were read at its boundary | `missing_actual_inputs` at an operator: add a `CaptureSpec` (step 2b); `inferred_inputs`: a `*lanes` fuser matched lanes to parents by position, so add a `CaptureSpec` for an exact lane-to-parent mapping |
| `candidate_identity` | Non-empty stable ids, positive ranks, unique ids per output | `blank_candidate_ids`: set `identity.candidate_id_field` or emit ids |
| `query_identity` | Non-empty query id and text, no id reused for different text | `query_id_collision`: pass a real query id |
| `final_output_capture` | Every successful trace's final output was captured | `final_output_shape_unsupported`: return a sequence or a mapping with `documents` |
| `judgment_mapping` | Judged document ids appear among observed candidates | `judgment_ids_unmatched`: id field or namespace differs from the qrels; `judgments_unavailable`: no labels (movement inspection still works) |
| `declared_route_coverage` | Every declared scenario was observed with its expected operators | `scenario_unobserved`: run that scenario's command |
| `cross_run_entity_alignment` | The same query produced the same ids twice | `alignment_unverified`: run the repeat scenario; `unstable_candidate_ids`: use stable ids |

`failed` means no trace, or core evidence (topology, query identity, candidate identity, final
output) is unavailable. `partial` is a limitation, not a failure: the report names exactly what is
missing. Iterate on the concrete failure codes; do not re-run an unchanged plan hoping for a
different result.

Check: `status` is `ready`, or every non-ready capability has a failure you have explained to the
user as a limitation.

### 6. Run a small labeled evaluation

Use the `benchmark_setup` action from the plan, which points `retobs evaluate` at the entrypoint
and the discovered labels and names the run after the pipeline so Connect can link it:

```bash
retobs evaluate app/pipeline.py:retrieve --queries data/queries.jsonl --qrels data/qrels.jsonl \
  --corpus data/corpus.jsonl --name <pipeline_id> --db .retobs/results.db
```

Accepted judgment rows: `{"query_id", "doc_id", "relevance"}` or
`{"query_id", "relevant_doc_ids": [...]}` (graded: `{"doc": grade}`). Chunk results scored
against document labels need `--chunk-map rows.jsonl` with `{chunk_id, document_id}`. The
evaluation runs the instrumented entrypoint once per query inside a run, so the operator spans
become the run's traces; failed queries persist an error trace and count against the run.

Check: the command exits 0 and prints recall/nDCG for the pipeline; `--format json` for a
machine-readable report.

### 7. Open the investigation

```bash
retobs serve --db .retobs/results.db
```

Open `#/connect?db=<db>&integration=<service_id>:<pipeline_id>` for the verified capabilities,
the plan summary, the open questions, and the "Open the first investigation" link, which lands in
Investigate scoped to the evaluation run: queries, a query's candidates through every operator,
documents, and a document's queries. Without a browser use
`retobs inspect-query RUN QUERY --db ...` and `retobs inspect-document RUN ENTITY --db ...`, or
the MCP tools `inspect_query` and `inspect_document`.

## MCP route

The same service behind the CLI is available as MCP tools once the server is registered
(`retobs mcp`): `integrate_project(project_root, phase, plan_path=..., db_path=...)` for
`plan | apply | verify | revert` (pass `plan_path` to the plan phase to re-plan from a reviewed
file), `evaluate_file` / `evaluate` for the labeled evaluation, `verify_integration` for
run-based checks, `inspect_query` and `inspect_document` for investigations. MCP is a transport:
it grants no filesystem access of its own and does not replace source instrumentation. Edit the
plan and `retobs_adapter.py` with your own tools; the plan phase result's `discovery.runbook`
names this file's installed location.

## Reporting back

Use this shape so the user can trust exactly what happened:

```text
Instrumented: <files edited> (revert with `retobs integrate . --phase revert`)
Operators: <op_id (type) ...>; final boundary: <...>
Verify: <status>; capabilities not ready: <name: failure code, what it limits>
Evaluation: <run id>, <queries attempted/completed>, <recall@k / ndcg@k>
Investigate: <URL or command>
Not observable: <what, why, what would make it observable>
```

Do not describe a partial integration as complete, do not invent operator internals for a
final-output-only endpoint, and do not report a scenario as covered when its command never ran.

## Troubleshooting

| Symptom | Cause and action |
|---|---|
| verify: `No traces found for service_id=... in <db>` | The entrypoint was not called, or was called with a different `--db`; run a scenario command from the project root |
| apply: `stale integration plan: <file>` | The file changed after planning; re-plan |
| apply: `already applied (manifest present)` | Run verify, or `revert` and re-apply a new plan |
| apply: `capture retobs_adapter:<symbol>: ... does not define <symbol>` | Define the `CaptureSpec` at module level in root `retobs_adapter.py` |
| apply: `patch would not compile` | A hand edit broke the patch; re-plan from the reviewed plan instead of editing `patches` |
| runtime: `ModuleNotFoundError: retobs_adapter` | The project root must be importable: run scenarios as `python -c ...` or `python -m app.main` from the root, or set `PYTHONPATH=.`; `python app/main.py` does not put the root on `sys.path` |
| `output_capture_unavailable` with `iterator_output_not_captured` | The operator returns a generator; wrap it in a list inside a `CaptureSpec.outputs` mapping or return a list |
| `final_output_shape_unsupported` | The entrypoint returns an object retobs cannot read; return a sequence or a mapping with a `documents` key, or set `boundary` to the last operator's output |
