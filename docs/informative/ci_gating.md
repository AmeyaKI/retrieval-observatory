# CI release gating

retobs gates a retrieval change in CI with the same release audit the CLI, SDK, MCP server, and
dashboard produce. The decision is `PASS`, `HOLD`, `BLOCK`, or `FAIL` under a policy kept in the
repository, and the exit code says which.

## CLI gate (recommended)

Copy [`examples/ci/retrieval-ci.yml`](../../examples/ci/retrieval-ci.yml). It evaluates the
candidate, compares it with a repository-selected baseline Run, always uploads the audit, and
tells a non-`PASS` decision apart from a tool error:

```bash
retobs evaluate project_eval.py:retrieve --db .retobs/results.db --format json --output artifacts/candidate.json
retobs compare "$BASELINE_RUN" "$CANDIDATE_RUN" --db .retobs/results.db \
  --policy examples/ci/release-policy-v3.yaml --artifacts artifacts/release-audit \
  --fail-on hold-or-block-or-fail
# 0 PASS · 1 FAIL · 2 BLOCK · 3 HOLD · 64 usage error · 70 tool error (no decision)
```

`--artifacts` writes `release-audit.json` and the standalone `release-audit.html` before the exit
status is decided, so a failed gate still leaves its evidence. Start the policy from
[`examples/ci/release-policy-v3.yaml`](../../examples/ci/release-policy-v3.yaml); see
[retrieval release decisions](../guides/retrieval-release-decisions.md) for what each status
means and [evidence limitations](../guides/evidence-limitations.md) for what a `PASS` does not
certify.

## pytest plugin

The plugin registers on install and provides a `retobs` fixture for tests that evaluate a
callable twice:

```python
# test_retrieval.py
CORPUS = {...}
QUERIES = [{"query_id": "q1", "text": "...", "relevant_doc_ids": ["d1"]}, ...]

def my_pipeline(query: str) -> list[str]:
    return my_search(query)          # your real retriever / hybrid pipeline

def test_no_retrieval_regression(retobs):
    baseline = retobs.run(my_pipeline, queries=QUERIES, corpus=CORPUS, k=10, name="search")
    candidate = retobs.run(my_pipeline, queries=QUERIES, corpus=CORPUS, k=10, name="search")
    retobs.assert_no_regression(candidate, baseline, metric="ndcg")
```

`assert_no_regression` reads the release audit's paired results and raises `AssertionError` when a
final-stage `ndcg`, `recall`, `mrr`, or `map` metric is proven worse, or a latency metric is proven
worse and rose by at least `latency_regression_pct` (default 0.20). Restrict it with `metric=`
(substring match, for example `"recall@10"`). It applies no policy; use the CLI gate when the
decision must follow a reviewed policy.

With a stored baseline Run, pass its ID:

```python
def test_against_baseline(retobs):
    candidate = retobs.run(my_pipeline, queries=QUERIES, corpus=CORPUS, db_path="baseline.db")
    candidate.assert_no_regression("BASELINE_RUN_ID", metric="recall@10")
```

## Final-output-only services

If the pipeline is a single opaque HTTP service, start with the black-box harness in
[`examples/integrations/http_evaluation/`](../../examples/integrations/http_evaluation/). It
evaluates the final top-K only: the audit works, but Investigate cannot show where a document
was lost until the service's operators are instrumented.
