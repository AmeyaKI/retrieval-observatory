# Future work

Known limitations and deferred work in retobs, recorded deliberately. Nothing listed here prevents
the current release from being used as documented. Items verified against the current tree are
stated as fact; anything carried over from earlier reports and not re-verified is marked as such.

## Reporting and metrics

- Comparison reports and single-run reports compute latency differently; the two aggregation paths
  should be unified so a metric name means the same thing in both.
- `baseline-summary.txt` is emitted only for the baseline run, so candidate-side routing and
  operator-activity counts have no persisted artifact and must be recomputed by hand.
- Wall-clock runtime is not recorded in any report artifact; per-stage `latency_mean` rows are, but
  they are machine-dependent, so neither can be diffed meaningfully across machines.

## Integration

- `integrate --phase verify` does not import the patched module itself; an import or syntax error in
  the target project surfaces only when the entrypoint is actually called. When no trace is found,
  verify names the service, pipeline, and database it looked for.
- `integrate --phase apply` has no `--dry-run` that renders the post-patch file before writing it.
- The planner discovers class methods and skips test files, but builds no cross-file call graph:
  operators found in different files are recorded without parent edges between them, and a project
  with several entrypoints still needs manual operator mapping.
- Name-only operator matches are listed under `discovery.low_confidence_operators` and left
  un-instrumented rather than asked about.

## Query difficulty classifier (experimental since 0.6.0)

- The classifier lives under `retrieval_observatory.experimental.classifier` and its CLI is
  unregistered. Training has no label source: nothing in the current runner computes a
  `difficulty_bucket` (every diagnostics row is written as `"unknown"`), so `train_model()` only
  works on databases produced by pre-typed-diagnostics builds. Restoring it needs a bucketing rule
  in the runner, which is a design decision rather than a fix.

## Counterfactual replay

- Replay is strict: whenever a removed operator's child would have to decide on documents it never
  observed, the result is `indeterminate`. This makes some upstream removals (for example a source
  arm feeding a fusion whose top-k cut hides documents from a downstream reranker) indeterminate by
  design. The study in `results/study/` reports these counts rather than estimating around them.
- Replay tiers are assigned per operator type by the runner (`pipeline/dag.py::DEFAULT_REPLAY_POLICY`),
  not learned from the adapter; an adapter that is in fact deterministic is still OBSERVED_ABLATION
  unless the spec overrides `replay_policy`.

## Benchmarks

- `results/BENCHMARK_ANALYSIS.md` was measured on an older build and has not been rerun on the
  current version. Rerunning the sweep would let the study describe the shipping release.
- The BEIR sweep covers three CPU-oriented subsets. GPU-served encoders, multilingual corpora, and
  production-scale indexes are unmeasured.
- The Cohere rerank sweep completed 155 of 323 queries and should be rerun with `--no-cache` before
  conclusions are drawn from it.

## Dashboard and stores

- The first (cold) `/overview` on a 400-query DAG run still spends about two seconds in the paired
  sign-flip test; later requests are memoised per run.
- The PostgreSQL store changes made in the 2026-09-15 review cycle (per-pipeline status counts,
  metric-row dedup, lineage service counts) are covered by the shared contract tests against SQLite
  only; no PostgreSQL server was available locally.
- `cli.py` still defines several never-registered commands left from earlier releases (`run`,
  `validate`, `init`, `inspect`, `quickstart`, `doctor`, `diff_configs`); they are dead code, not
  reachable from `retobs --help`.

## Demo ergonomics

- `results/flagship_demo/run_demo.sh` deletes and rebuilds its ~1.2 GB SQLite database on every
  invocation. The path is correctly scoped and cannot affect version-controlled files, but a
  `--keep` flag would stop an external user from discarding a long run by accident.

## Documentation

- `.gitignore` uses a blanket `*.md` rule with an explicit allowlist, so new documentation files are
  ignored unless added to that list. A narrower ignore rule would remove the trap.
