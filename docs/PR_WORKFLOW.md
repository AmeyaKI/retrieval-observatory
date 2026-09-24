# Pull-request comparison workflow

Generate reviewable artifacts from the same release audit the dashboard, SDK, and MCP server use:

```bash
retobs compare "$BASELINE_RUN" "$CANDIDATE_RUN" \
  --db .retobs/results.db \
  --policy retobs/release-policy.yaml \
  --artifacts artifacts/release-audit \
  --format markdown \
  --output artifacts/retobs-comparison.md \
  --fail-on hold-or-block-or-fail
```

`--artifacts` writes `release-audit.json` and a standalone `release-audit.html` (decision and exit
code, policy identity and digest, compatibility, each check with its interval and tolerance,
slices, the failure-rate cap, and the changed queries). The Markdown is a summary suited to a
pull-request comment. Both are written before the exit status is decided.

In GitHub Actions, append the Markdown to `$GITHUB_STEP_SUMMARY` and upload `artifacts/` with
`if: always()`. See the runnable [example workflow](../examples/ci/retrieval-ci.yml), which also
separates a non-`PASS` decision (exit 1 to 3) from a tool error (64 or 70).

Gate choices:

- `--fail-on fail` fails only on a proven regression (exit 1).
- `--fail-on hold-or-block-or-fail` also fails on inconclusive (3) or missing or incompatible
  evidence (2), and is safer for protected branches.
- `--fail-on never` writes the evidence without deciding (exit 0 whenever a decision was produced).

The older `regression` and `regression-or-no-decision` spellings map to `fail` and
`hold-or-block-or-fail` with a deprecation warning. See
[retrieval release decisions](guides/retrieval-release-decisions.md).

Do not publish reports containing sensitive query text or document metadata without review; see
[Data and privacy](PRIVACY.md).
