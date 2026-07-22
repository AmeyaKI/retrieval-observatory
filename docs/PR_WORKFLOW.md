# Pull-request comparison workflow

Generate reviewable artifacts from the same comparison model used by the dashboard and SDK:

```bash
retobs compare "$BASELINE_RUN" "$CANDIDATE_RUN" \
  --db .retobs/results.db \
  --policy retobs/release-policy.yaml \
  --format markdown \
  --output artifacts/retobs-comparison.md \
  --fail-on hold-or-block-or-fail

retobs compare "$BASELINE_RUN" "$CANDIDATE_RUN" \
  --db .retobs/results.db \
  --policy retobs/release-policy.yaml \
  --format html \
  --output artifacts/retobs-comparison.html
```

The Markdown/HTML include baseline and candidate IDs, validity differences, quality/latency/cost rows when present, candidate-minus-baseline effects, corrected q-values, paired sample sizes, decision/no-decision reasons, and affected queries. HTML is standalone and works without a running dashboard; dashboard links are provided for local drill-down.

In GitHub Actions, append the Markdown to `$GITHUB_STEP_SUMMARY` and upload the HTML artifact. The artifact is intentionally separate because GitHub cannot know its final authenticated download URL while the report is rendered. See the runnable [example workflow](../examples/ci/retrieval-ci.yml).

Recommended gate policy:

- `--fail-on fail` blocks only a policy-critical proven regression.
- `--fail-on hold-or-block-or-fail` also blocks inconclusive or invalid required evidence and is safer for protected branches.
- `--fail-on never` generates evidence without deciding merge policy.

The deprecated `regression` aliases remain compatible for one release cycle, but new workflows should use the canonical terms above. See [retrieval release decisions](guides/retrieval-release-decisions.md).

Do not publish reports containing sensitive query text/document metadata without review; see [Data and privacy](PRIVACY.md).
