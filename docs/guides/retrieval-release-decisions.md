# Retrieval release decisions

RetObs is a local-first evidence-control plane for retrieval changes. It evaluates recorded baseline/candidate evidence under a bounded, versioned policy and returns one of four outcomes. It does not deploy a model, score generated answers, or claim that a changed retrieval path caused a metric change.

## Define the bounded policy

Start from [`examples/ci/release-policy.yaml`](../../examples/ci/release-policy.yaml). Replace its exact canonical metric key, budgets, minimum paired sample count, and declared slices with reviewed values for your pipeline. Policies accept exact metric keys and exact top-level metadata values only—no expressions, regular expressions, SQL, or Python.

Keep the policy in version control. Its canonical digest appears in the release artifact so a policy change cannot be hidden inside a candidate comparison.

## Verify, compare, and inspect locally

```bash
retobs integrate . --phase verify --policy retobs/release-policy.yaml
retobs compare BASELINE CANDIDATE --db .retobs/results.db --policy retobs/release-policy.yaml --format html --output artifacts/retobs-release.html --fail-on hold-or-block-or-fail
retobs serve --db .retobs/results.db
```

The dashboard binds to `127.0.0.1` by default. The HTML artifact is standalone; review it before uploading because run IDs and other recorded metadata may be sensitive.

To evaluate a configured policy in the local dashboard, enter its local filesystem path in **Local release-policy path** and select **Evaluate policy**. The RetObs process reads the file locally and returns the same canonical decision used by CLI, SDK, MCP, and CI; the browser does not derive a release status.

## Interpret the decision

| Status | Bounded meaning |
|---|---|
| `PASS` | Required promotion evidence is valid and every aggregate and declared-slice paired interval proves non-inferiority within its budget. |
| `HOLD` | Promotion evidence is valid but an interval or sample size cannot prove pass or fail. |
| `BLOCK` | Policy-required evidence is absent or invalid, such as mismatched corpus identity or missing required labels. |
| `FAIL` | Valid evidence proves at least one policy-critical aggregate or declared-slice regression beyond its budget. |

`PASS` does not mean universally safe, causally explained, or automatically deployable. It means the recorded evidence supports promotion under this policy. Existing p-values and corrected q-values remain diagnostic context; promotion uses the policy’s paired non-inferiority intervals.

## Keep readiness scoped to the claim

Promotion, aggregate/slice evaluation, lineage diagnosis, lineage diff, and production trace claims have separate readiness. A comparison can pass promotion while lineage diagnosis is blocked because final outputs are sufficient for the policy but stage transitions are incomplete. Missing lineage evidence blocks promotion only when the policy explicitly requires it for promotion.

Document-level qrels do not silently become chunk-level labels. Relevant-retained or relevant-dropped outcomes require a validated qrel-to-chunk mapping; otherwise the Explorer reports unknown relevance or incomplete lineage.

When an intentional topology revision only renames equivalent operators, declare exact one-to-one `evidence.lineage_diff.equivalent_stages` entries with `baseline_op_id` and `candidate_op_id`. RetObs applies only those reviewed mappings; undeclared topology changes continue to block a stage-aligned diff.

## CI

The [example workflow](../../examples/ci/retrieval-ci.yml) evaluates the candidate, compares it with a repository-selected baseline, publishes Markdown/HTML artifacts, and exits nonzero on `HOLD`, `BLOCK`, or `FAIL`. It requires no hosted RetObs service or RetObs secret. Your dataset, model, or external provider may have separate credentials and data-handling requirements.

### Exit codes

`retobs compare --fail-on hold-or-block-or-fail` exits with the decision's own code, so CI can tell the outcomes apart; `--fail-on fail` exits nonzero only on `FAIL`, and the default `--fail-on never` exits 0 whenever a decision was produced.

| Exit | Meaning |
|---|---|
| `0` | `PASS`, or the decision is not gated by `--fail-on` |
| `1` | `FAIL` |
| `2` | `BLOCK` (also a command-line usage error such as a missing run ID, reported by the argument parser) |
| `3` | `HOLD` |
| `64` | Invalid `--fail-on` or `--format` value |
| `70` | Tool error: the comparison could not be produced (run not found, invalid policy); no decision and no artifact |

Compatibility: earlier releases exited `1` for every gated `HOLD`, `BLOCK`, or `FAIL`, `2` for an invalid option value, and `1` for a tool error. `--artifacts DIR` writes `release-audit.json` and the standalone `release-audit.html` before the exit status is chosen, so a gated run still leaves its audit behind.

RetObs complements general tracing, experiment tracking, and evaluation systems by adding this retrieval-specific policy and lineage boundary. It does not claim broader observability coverage or replace those systems.
