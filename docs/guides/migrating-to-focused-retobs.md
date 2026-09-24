# Migrating to focused retobs (0.7.0)

0.7.0 narrows retobs to three workflows over one dashboard: **Connect** a pipeline,
**Investigate** where relevant documents were lost, and **Audit** a baseline against a candidate
under a declared policy. Several subsystems were removed. retobs is pre-1.0, so these are breaking
changes; this page lists each one with its replacement, or says there is none.

To keep using a removed feature, pin the last release that shipped it:

```bash
pip install retrieval-observatory==0.6.0
# or, from a clone of the repository
git checkout 29c67b8
```

Databases written by 0.6.0 stay readable (see [Storage](#storage)).

## Python API

| 0.6.0 | 0.7.0 |
|---|---|
| `TestSet`, `generate_testset(...)` | Removed, no replacement. Evaluate against a prepared benchmark: JSONL queries, corpus and qrels, or a BEIR dataset. |
| `Run.assert_no_regression(baseline, metric=..., latency_regression_pct=...)` and the pytest fixture's `retobs.assert_no_regression(...)` | Same signature. It now reads the release audit's paired results: it raises when a final-stage `ndcg`/`recall`/`mrr`/`map` metric is proven worse (`candidate_worse`), or a latency metric is proven worse and rose by at least `latency_regression_pct`. The removed regression module is no longer imported. |
| `evaluate(callable, ...)` | Unchanged, plus `provenance={...}` (release identity: `service_id`, `deployment_revision`, `corpus_revision`, `index_build_id`, `chunking_revision`, `embedding_model_revision`, `reranker_model_revision`; unknown keys are rejected) and `chunk_map=[(chunk_id, document_id, namespace), ...]`. An instrumented callable's own `@observe` spans become the Run's trace. The CLI flags are `--provenance KEY=VALUE` and `--chunk-map PATH`. |
| `inspect_query(...)` | Unchanged name; its document embeds the investigation envelope for the query. `findings` is empty with `availability.findings = "unavailable"`. |
| (new) | `inspect_document(run_id, "namespace:id", db_path=...)`: one document's journey across every query of a Run. |

The top-level exports are now `Comparison`, `Document`, `IntegrationOptions`, `Query`,
`QueryEvidence`, `RetrievalTrace`, `Run`, `TraceRecorder`, `compare`, `evaluate`, `init`,
`inspect_document`, and `inspect_query`.

`@observe(..., replay_policy=..., deterministic=...)` still accepts both arguments and records them
on the span, but nothing in 0.7.0 replays a trace.

## Release policies: v2 to v3

`load_release_policy(path)` (in `retrieval_observatory.release.policy`) loads either
`schema_version: 2` or `3`, and `retobs compare --policy` accepts both. A v3 policy names each
check by meaning (`target: final_retrieval | query | operator:<id>`) instead of a positional
`pipeline|stageN|metric@k` key; see [`examples/ci/release-policy-v3.yaml`](../../examples/ci/release-policy-v3.yaml)
and [evidence limitations](evidence-limitations.md#semantic-selectors).

A v2 policy is converted per comparison by `convert_v2_policy` (in
`retrieval_observatory.release.resolution`), and the result is reported, not applied silently.
Run the comparison once with your v2 file and read the conversion:

```bash
retobs compare BASELINE CANDIDATE --db .retobs/results.db --policy retobs/release-policy.yaml --format json \
  > compare.json
# comparison.release_decision.policy_conversion = {"policy": {...v3...} | null, "unresolved": [...], "findings": [...]}
```

When every guard converts, `policy` is the equivalent v3 policy: save it as your new policy file
and review it. A positional stage that maps to no operator, or to more than one, is listed in
`unresolved` with a `policy_selector_ambiguous` finding, and the decision is `BLOCK` until you
declare that guard with a v3 selector.

## Command line

| 0.6.0 | 0.7.0 |
|---|---|
| `retobs testsets scan \| generate \| list` | Removed, no replacement. |
| `retobs production demo \| stats \| purge` | Removed. Traces pushed with `push_traces` or recorded by `@trace_scope` are still stored; investigate them through an evaluated Run. |
| `retobs demo` (synthetic test set and production traces) | Two deterministic runs of a golden hybrid pipeline and a v3 policy that passes. `--n-traces` is accepted and ignored. |
| (new) | `retobs inspect-document RUN ENTITY`, `retobs storage migrate`, `retobs storage index`. |
| `retobs compare --fail-on hold-or-block-or-fail` exited `1` for `HOLD`, `BLOCK`, or `FAIL` | Exits with the decision's own code: `FAIL` 1, `BLOCK` 2, `HOLD` 3, `PASS` 0. |
| Invalid `--fail-on`/`--format` exited `2` | Exits `64` (usage). |
| A comparison that could not be produced exited `1` | Exits `70` (tool error, no decision). |
| (new) | `retobs compare --artifacts DIR` writes `release-audit.json` and `release-audit.html` before the exit status is decided. |

The `--fail-on regression` and `regression-or-no-decision` spellings still map to `fail` and
`hold-or-block-or-fail` with a deprecation warning. CI that tested `exit != 0` keeps working; CI
that tested `exit == 2` for a bad option must test `64`. The full table is in
[retrieval release decisions](retrieval-release-decisions.md#exit-codes).

## Extras

The `classifier` extra (`scikit-learn`, `joblib`) is removed with the learned difficulty
classifier. `pip install "retrieval-observatory[classifier]"` no longer installs anything extra.

## Dashboard links

The dashboard has three workflows plus Help. Links from 0.6.0 that map to one of them without
losing meaning are redirected for one release; the database (`db=`) is carried over.

| Old link | Redirects to |
|---|---|
| `#/runs/RUN` | `#/investigate?run=RUN` |
| `#/runs/RUN/queries` | `#/investigate?run=RUN&view=queries` |
| `#/runs/RUN/queries/Q` | `#/investigate?run=RUN&view=queries&query=Q` |
| `#/runs/RUN/queries/Q/candidates/DOC` | `#/investigate?run=RUN&view=queries&query=Q&entity=DOC` |
| `#/runs/RUN/documents` | `#/investigate?run=RUN&view=documents` |
| `#/benchmarks/run/RUN/...` | as `#/runs/RUN/...` |
| `#/compare` | `#/audit` |
| `#/glossary` | `#/help` |

These destinations were retired. They show a migration notice that links here instead of content:

| Old link | Use instead |
|---|---|
| `#/home` | Investigate (the selected run), or Connect when no run exists |
| `#/queries` | Investigate, inside one run |
| `#/production` | Investigate, for traces recorded by an evaluated run |
| `#/test-sets` | Connect, then evaluate a prepared benchmark |
| `#/runs/RUN/attribution`, `/quality`, `/architecture`, `/analysis` | Investigate |
| `#/runs/RUN/tradeoffs`, `#/runs/RUN/queries/Q/diff` | Audit, then "Open in Investigate" for a changed query (`#/investigate?...&compare=BASELINE`) |

The current link shapes are
`#/investigate?db=&run=&pipeline=&view=queries|documents&query=&trace=&entity=&stage=&outcome=&compare=`,
`#/connect?db=&integration=`, and `#/audit?db=&baseline=&candidate=&policy=`.

## HTTP routes

Routes for removed features answer `410 Gone` with a pointer to the replacement workflow, for
example:

```json
{"detail": {"code": "retired", "detail": "Counterfactual replay and operator attribution were retired. Investigate shows each candidate's recorded transitions and loss boundary per query.", "replacement": "#/investigate"}}
```

This applies, with and without the `/dbs/{db}` prefix, to `/forge/*` and `/advisor/*`; to
`/runs/{run}/query-labels`, `classifier-calibration`, `pareto-frontier`, `operator-attribution`,
`traces/{trace}/miss-attribution`, `traces/{trace}/operator/{op}/diff`, and
`queries/{query}/candidates/{candidate}`; to `/production/summary`, `distribution`, `drift`,
`hotspots`, and `clusters`; and to `/dbs/{db}/analysis/cohorts` and `corpus-health`. The new
read routes are `GET /dbs/{db}/investigation/runs/{run}/queries[/{query}]`,
`.../documents[/{entity}]`, `.../compare?against=BASELINE`, and
`GET /dbs/{db}/integrations[/{service}:{pipeline}]`. `POST /compare` returns the release audit
under `audit`.

## Storage

0.7.0 adds three investigation tables (schema v3). Nothing is dropped: the test-set, reliability
and diagnostics tables written by 0.6.0 stay as historical data. A read-only v2 database opens,
but its investigation views are empty until you migrate it and index its runs:

```bash
retobs storage migrate --db .retobs/results.db             # additive; backs the file up first (--no-backup to skip)
retobs storage index RUN_ID --db .retobs/results.db        # --pipeline when the run has several
```

Runs evaluated by 0.7.0 are indexed when they finish.

## Retired features

Removed with no replacement in 0.7.0; use 0.6.0 / `29c67b8` to reproduce them:

- synthetic test-set generation and stress suites;
- the learned pre-retrieval difficulty classifier;
- recommendations, regression detection, reliability snapshots, and change simulation;
- counterfactual replay and per-operator marginal attribution;
- production monitoring: drift, hotspots, clusters, distributions, cohorts, corpus health;
- Pareto and tradeoff views;
- the static HTML pipeline diagram.

What each removed module was, and the reproduction commands, are in
[retired subsystems](experimental/README.md). Published results under `results/` were produced
with those releases and are not regenerated.
