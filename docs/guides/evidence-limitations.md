# Evidence limitations

retobs states what the recorded evidence shows and says where it stops. This page lists the
limits you will meet while investigating a Run or reading an audit, and how each one appears.
The vocabulary is the one [Investigate](investigate-your-pipeline.md) and
[Audit](retrieval-release-decisions.md) render.

## Judgments and evaluation units

- **A judgment belongs to one query and one entity.** There is no query-independent relevance:
  the same document can be relevant for one query and judged nonrelevant for another. Grades are
  stored as given; a document is relevant when its grade is at least the relevance threshold
  (default 1), and an explicit grade 0 is nonrelevant.
- **Entities are namespaced.** An entity is `namespace:id` at a unit (`document` or `chunk`).
  `kb:doc-1` and `tickets:doc-1` are two different entities. A bare id means namespace
  `default`.
- **Contradictory judgments are rejected.** A qrels file that grades the same query and document
  twice with different grades fails to load and names both lines; identical repeats collapse.
- **Document unit.** At `unit: document` a document counts as delivered when any of its chunks is
  delivered. That is a document-retrieval statement; it does not prove the passage that supports
  the answer was delivered.
- **Chunk unit.** A document's grade is never inherited by its chunks. Chunk-level relevance needs
  chunk-level judgments.

## Chunk maps

When your pipeline returns chunks and your judgments are per document, pass a chunk map so
results are scored against the judged documents:

```bash
retobs evaluate app/search.py:retrieve --queries queries.jsonl --qrels qrels.jsonl \
  --chunk-map chunk_map.jsonl --name my-pipeline --db .retobs/results.db
```

Each line is `{"chunk_id": ..., "document_id": ..., "namespace": ...}` (namespace optional). The
SDK takes the same rows as `evaluate(..., chunk_map=[(chunk_id, document_id, namespace), ...])`.
A returned chunk that is not in the map cannot be tied to a judged document; it is reported as
`unjudged`, not as nonrelevant.

## Unjudged evidence

Absent is absent. An unjudged document is never written as a zero, never counted as a false
positive, and never excluded from the table. Investigate shows it as `unjudged` and counts
unjudged inclusions separately. Ranking metrics treat it the conventional way (no gain), and a
v3 policy can state that choice explicitly (`evaluation.unjudged_metric_policy: zero_gain` or
`exclude`). Many unjudged inclusions in a query mean its metric says little about that query.

## Partial, positional, and inferred capture

Each operator records how its boundary was captured:

| Label | Meaning |
|---|---|
| input `recorded` / output `recorded` | The operator's actual arguments (snapshotted before the call) and its actual returned object. |
| input `positional` | Candidates passed positionally, such as `rrf_fusion(*lanes)`; lanes cannot be named. |
| input `inferred` | Inputs reconstructed from parent spans' outputs, or supplied by a framework callback. Labeled, never shown as recorded. |
| output `truncated` | Only part of the output was kept (a capture limit). Removals past the cut are `unknown`. |
| `unavailable` | Nothing was captured, for example a generator or an unsupported return shape. Never recorded as an empty list. |

A partial boundary does not stop investigation. Rows that cross it are marked
`insufficient_evidence` or carry `capture partial`, their exits are `unknown`, and the rest of
the query remains usable. The demo shows this on purpose: the recorder keeps only the first
output of `rerank@lexical` for `q-outage`. When the default rules cannot read a boundary, add a
`CaptureSpec` in the project's `retobs_adapter.py` (see the
[agent runbook](../integrations/AGENT_QUICKSTART.md)).

## Final-output-only integrations

A remote endpoint, or one function whose internals are not instrumented, is observed only at its
final output. Evaluation and delivered/missed outcomes still work; loss boundaries do not,
because no internal transition was recorded. The integration record Connect shows carries
`depth: final_only`. Do not read the absence of a loss boundary as "nothing was lost inside".

## Skipped branches

A gated operator that did not run for a query is `SKIPPED_BY_GATE`. It records no inputs and no
events, it is excluded from that operator's served-query denominator (the diagram says
`served 1 of 3 queries`), and its per-branch metrics are computed over the queries it served,
each with its own `n`. A skipped branch is never read as a branch that ran and scored zero.

## Capture failures

Capture never changes what your application returns or raises. When capture itself fails (an
unreadable result, a declared parent that never fired), the failure is recorded on the trace
(`capture_failures`, for example `final_output_shape_unsupported` or `producer_not_observed`)
and the call proceeds. Integration verification surfaces these as coded failures with a fix;
`strict_capture()` turns them into errors during a verification run.

## What an audit certifies

An audit (`retobs compare`, Audit in the dashboard, MCP `compare`, CI) answers one question: does
the recorded evidence support promoting the candidate under this declared policy? It does not
establish that the candidate is safe in general, that a path change caused a metric change, or
that the change is ready to deploy. Readiness is scoped per claim: promotion, aggregate or slice
evaluation, lineage diagnosis, lineage diff, and production traces are reported separately, so an
audit can be `PASS` for promotion while lineage diagnosis is blocked by partial capture.

### Semantic selectors

A v3 policy names what each check measures by meaning, not position:
`target: final_retrieval`, `target: query`, or `target: operator:<id>`, with a stable check id.
Every selector is resolved against both Runs before anything is evaluated; a selector that is
absent or ambiguous in either Run is `metric_selector_unresolved` and blocks the decision instead
of silently comparing the wrong stage. A v2 policy with positional stage keys is converted
explicitly, and a stage that cannot be mapped uniquely is reported as `policy_selector_ambiguous`.

### Statuses and precedence

| Status | Exit | Meaning |
|---|---|---|
| `BLOCK` | 2 | Required evidence is missing or the Runs are not comparable (different query inputs, judgments, corpus, evaluation unit or `k`; an unresolved selector; unknown attempt accounting). |
| `FAIL` | 1 | Valid evidence proves a regression beyond a declared tolerance, or the candidate's failure rate exceeds the cap. |
| `HOLD` | 3 | Evidence is valid but inconclusive: too few pairs, pair coverage below the minimum, an interval that crosses the tolerance, or an undeclared change to review. |
| `PASS` | 0 | Every declared check and slice interval proves non-inferiority within its tolerance and the failure rate is within budget. |

Every check result is kept, and the decision is the most severe one: `BLOCK` > `FAIL` > `HOLD` >
`PASS`. The exit codes apply when `--fail-on hold-or-block-or-fail` selects the decision.

### Pair coverage

Checks are paired by query over the expected query universe. The audit reports attempted and
paired counts for every check; when fewer than `statistics.min_pair_coverage` of attempted queries
are paired (the v3 default is 1.0: every attempted query), the check is `HOLD`, because the
queries that failed on one side are exactly the ones a mean would hide.

### Execution failure caps

`execution.max_failure_rate` caps the candidate's share of failed queries among those attempted.
Exceeding it is `FAIL` regardless of quality; a Run whose attempted count is unknown is `BLOCK`.
Baseline failures are reported, not judged.

### Exploratory re-testing

Intervals are adjusted for the checks and slices the policy declares, once. Editing the policy
after seeing a result, re-running the comparison until it passes, or adding slices that happened
to look good is exploration, not a test, and the stated confidence no longer holds. Keep the
policy in version control, change it in its own reviewed commit, and treat a `PASS` reached by
iteration as a hypothesis for a fresh comparison.
