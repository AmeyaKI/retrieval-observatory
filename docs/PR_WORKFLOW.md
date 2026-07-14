# Pull-request comparison workflow

Generate reviewable artifacts from the same comparison model used by the dashboard and SDK:

```bash
retobs compare "$BASELINE_RUN" "$CANDIDATE_RUN" \
  --db .retobs/results.db \
  --format markdown \
  --output artifacts/retobs-comparison.md \
  --fail-on regression-or-no-decision

retobs compare "$BASELINE_RUN" "$CANDIDATE_RUN" \
  --db .retobs/results.db \
  --format html \
  --output artifacts/retobs-comparison.html
```

The Markdown/HTML include baseline and candidate IDs, validity differences, quality/latency/cost rows when present, candidate-minus-baseline effects, corrected q-values, paired sample sizes, decision/no-decision reasons, and affected queries. HTML is standalone and works without a running dashboard; dashboard links are provided for local drill-down.

In GitHub Actions, append the Markdown to `$GITHUB_STEP_SUMMARY` and upload the HTML artifact. The artifact is intentionally separate because GitHub cannot know its final authenticated download URL while the report is rendered. See the runnable [example workflow](../examples/ci/retrieval-ci.yml).

Recommended gate policy:

- `--fail-on regression` blocks only a supported decision-bearing regression.
- `--fail-on regression-or-no-decision` also blocks invalid/underpowered comparisons and is safer for protected branches.
- `--fail-on never` generates evidence without deciding merge policy.

Do not publish reports containing sensitive query text/document metadata without review; see [Data and privacy](PRIVACY.md).
