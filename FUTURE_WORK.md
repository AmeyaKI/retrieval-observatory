# Future work

Known limitations and deferred work in retobs. Nothing listed here prevents the current release from
being used as documented. Items are stated as fact when verified against the current tree; anything
carried over from an earlier release and not re-verified is marked as such.

## Integration

- `retobs evaluate` scores runs it drives itself. A project's own benchmark command is not scored:
  per-question losses come from `retobs evaluate` over the same search, not from the project's report.
- `retobs evaluate` calls `module:function(query_text)`. A search exposed as a class method, or one
  that needs the benchmark's arguments (mode, depth), needs a small wrapper module; the agent runbook
  shows the pattern.
- The command line scores recall at 1, 5 and 10 and nDCG@10; other cutoffs (for example Recall@100)
  cannot be set there.
- `integrate --phase plan --watch` sees only the modes its commands run: a step that only another mode
  runs (a reranker behind a flag, for example) is planned only when that mode is watched too. Watching
  is POSIX-only, and an MCP client waits while a watch runs.
- Without `--watch`, the planner guesses steps from function names and links them only through
  plain-name calls within one file; a project with several entrypoints needs manual operator mapping.
  Name-only matches are listed under `discovery.low_confidence_operators` and left un-instrumented.
- Judgment files found by the planner are a guess; when `judgments.status` is not `resolved`, the
  benchmark's labeled split has to be exported by hand.
- `integrate --phase verify` does not import the patched modules itself: an import or syntax error in
  the target project surfaces only when the entrypoint is called.
- `integrate --phase apply` has no `--dry-run` that renders the patched files before writing them.

## Storage and dashboard

- Storage is about 1 MB per traced question at 100 candidates per step, most of it the investigation
  index; large benchmarks are best sampled with `--max-queries` or given their own database.
- The hosted demo refuses path inputs, so Audit cannot load a release policy there and reports HOLD.
- `cli.py` still defines never-registered commands left from earlier releases (`run`, `validate`,
  `init`, `inspect`, `doctor`, `diff_configs`). They are not reachable from `retobs --help`.
- Comparison reports and single-run reports aggregate latency through different paths, so a latency
  metric name may not mean the same thing in both (carried over from 0.6.x, not re-verified).

## Research study

[`results/study/STUDY.md`](results/study/STUDY.md) is published as it stands: 13 of 14 pre-registered
cells, produced by development builds between 0.6.0 and 0.7.0, with the HotpotQA cell (Q3) never run
and the Q1 headline therefore provisional. Its scripts import modules removed in 0.7.0 (loss
attribution and counterfactual replay), so it cannot be rerun on a current release. Updating it means:

- Port `scripts/study_loss_attribution.py` and `scripts/render_study.py` to the current lineage model:
  the per-step counts of correct documents found, removed and lost that back Investigate's flow view
  (`GET /dbs/{db}/investigation/runs/{run}/flow`) measure the same thing as the study's destroyed /
  surfaced / never-surfaced split.
- Decide §5 (marginal contributions by replay tier): counterfactual replay no longer exists, so
  either restore it or drop the section, through a dated amendment to `PREREGISTRATION.md` before
  any cell is rerun.
- Rerun all 14 cells on one current build, including `hotpotqa__hotpot_routed`, then re-render and
  replace the provisional headline with the pre-registered result (or report it as null or against
  expectation in the same place).

## Benchmarks

- `results/BENCHMARK_ANALYSIS.md` was measured on 0.1.0 and has not been rerun on a current release.
- The BEIR sweep covers three CPU-oriented subsets. GPU-served encoders, multilingual corpora and
  production-scale indexes are unmeasured.
- The Cohere rerank sweep completed 155 of 323 queries and should be rerun with `--no-cache` before
  conclusions are drawn from it.

## Flagship demo

- On macOS conda environments where torch and faiss each bundle an OpenMP runtime, the flagship
  demo's dense lane segfaults unless `KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1` is set;
  `results/flagship_demo/run_demo.sh` sets both by default. The root cause is the environment.
- `run_demo.sh` deletes and rebuilds its ~1.2 GB SQLite database on every invocation. The path is
  scoped to the demo, but a `--keep` flag would stop a long run from being discarded by accident.

## Repository

- `.gitignore` uses a blanket `*.md` rule with an explicit allowlist, so a new documentation file is
  ignored until it is added to that list.
