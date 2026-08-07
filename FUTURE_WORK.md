# Future work

Known limitations and deferred work in retobs, recorded deliberately. Nothing listed here prevents
the current release from being used as documented. Items verified against the current tree are
stated as fact; anything carried over from earlier reports and not re-verified is marked as such.

## Reporting and metrics

- Comparison reports and single-run reports compute latency differently; the two aggregation paths
  should be unified so a metric name means the same thing in both.
- `baseline-summary.txt` is emitted only for the baseline run, so candidate-side routing and
  operator-activity counts have no persisted artifact and must be recomputed by hand.
- Wall-clock and latency figures are machine-dependent and are not recorded in any report artifact,
  so they cannot be diffed across reruns.

## Integration

- `integrate --phase verify` reports a failed integration as `Missing operators: [...]` rather than
  naming the underlying import or syntax error, which directs the user to the wrong diagnosis.
- `integrate --phase apply` has no `--dry-run` that renders the post-patch file before writing it.
- Integration reliably detects a single entrypoint. Multi-entrypoint pipelines and class-method
  retrievers still require manual operator mapping.
- The linear (non-DAG) trace path was previously reported to discard `op_type`, mislabelling which
  kind of operator lost a document on simple pipelines. *Reported earlier; not re-verified in the
  current review pass.*

## Query difficulty classifier

- `retobs classifier train` finds no labels because `difficulty_bucket` is written as `"unknown"`.
  Training currently works only by calling `train_model()` directly and pointing runs at
  `RETOBS_CLASSIFIER_MODEL`.
- The flagship demo does not exercise this path (`annotate_difficulty=False`), so the gap is not
  visible in the published results.

## Benchmarks

- `results/BENCHMARK_ANALYSIS.md` was measured on an older build and has not been rerun on the
  current version. Rerunning the sweep would let the study describe the shipping release.
- The BEIR sweep covers three CPU-oriented subsets. GPU-served encoders, multilingual corpora, and
  production-scale indexes are unmeasured.
- The Cohere rerank sweep completed 155 of 323 queries and should be rerun with `--no-cache` before
  conclusions are drawn from it.

## Demo ergonomics

- `results/flagship_demo/run_demo.sh` deletes and rebuilds its ~1.2 GB SQLite database on every
  invocation. The path is correctly scoped and cannot affect version-controlled files, but a
  `--keep` flag would stop an external user from discarding a long run by accident.

## Documentation

- `.gitignore` uses a blanket `*.md` rule with an explicit allowlist, so new documentation files are
  ignored unless added to that list. A narrower ignore rule would remove the trap.
