# CI regression gating

retobs ships a pytest plugin so you can fail a build when a retrieval change causes a
**statistically significant** quality drop — the reason to use retobs over an ad-hoc script.

## pytest plugin (recommended)

The plugin auto-registers on install and provides a `retobs` fixture:

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

`assert_no_regression` uses a paired bootstrap test with Benjamini–Hochberg correction
(`advisor/regression.py`) and raises `AssertionError` only on significant drops. Restrict the
gate with `metric=` (substring match, e.g. `"ndcg"`, `"recall@10"`) and tune
`latency_regression_pct=` (default 0.20).

In real CI the baseline is a stored golden run, not a fresh run. Persist a baseline run id and
pass it as a string:

```python
def test_against_golden(retobs):
    candidate = retobs.run(my_pipeline, queries=QUERIES, corpus=CORPUS, db_path="golden.db")
    candidate.assert_no_regression("GOLDEN_RUN_ID", metric="recall@10")
```

## CLI golden gate (YAML pipelines)

For YAML-defined pipelines, use the Advisor directly — see
[`examples/ci/retrieval-ci.yml`](../examples/ci/retrieval-ci.yml) for a copy-paste GitHub Action:

```bash
retobs run --config bench.yaml --no-cache
retobs advisor check --baseline "$GOLDEN_RUN" --candidate "$CANDIDATE" --db .retobs/results.db
# non-zero exit on significant regression
```

## Where this fits

This is the value-preserving form: multi-stage runs keep per-stage contribution and
`candidate_miss` / `reranker_drop` diagnostics. If your production pipeline is a single opaque
HTTP service, start with the black-box harness in
[`examples/integrations/http_quickstart/`](../examples/integrations/http_quickstart/) (final top-K only), then graduate to
emitting per-stage snapshots (see "multi-snapshot" in the SDK docs) to recover stage-level
diagnostics.
