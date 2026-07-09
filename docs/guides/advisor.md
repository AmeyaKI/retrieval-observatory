# The Advisor — from diagnostics to a prioritized plan

The Advisor turns retobs's diagnostics into specific, evidence-backed engineering
recommendations, ranked by expected value. It is a planning tool, not a list of platitudes.

## What a recommendation carries

Each `Recommendation` (`retrieval_observatory/advisor/types.py`) includes:

- **action** and **rationale** — what to change and why.
- **evidence** — the specific diagnostics that triggered it (e.g. "failure_label=reranker_drop
  in 18/40 rows").
- **estimated_quality_improvement** (+ CI) in a named metric like `recall@10`.
- **estimated_latency_increase_ms**, **implementation_effort** (S/M/L), **confidence**.
- **affected_query_categories** — which kinds of query benefit.
- **expected_value** — the ranking score.

When a value cannot be estimated it stays `None` and the UI shows "not estimated" rather than
inventing a number.

## How recommendations are ranked

`_prioritize` (`retrieval_observatory/advisor/recommend.py`) sorts by expected engineering
value — quality gain weighted by confidence, penalized by latency cost and effort.
Recommendations with no estimate sort into an explicit tail so they never masquerade as
high-confidence advice.

## Improvement simulation

Before you change anything, `simulate_operator_removal`
(`retrieval_observatory/advisor/simulate.py`) estimates the impact of removing an operator by
replaying the pipeline without it and re-scoring against qrels — the same counterfactual
machinery as attribution (see [counterfactual-replay.md](counterfactual-replay.md)). The
result carries its `ReplayAssumptions`, so the estimate's basis is inspectable. The goal is
informed decision-making, not perfect prediction.

## Using it

```bash
retobs advisor <run_id>
```

or read the **Recommendations** card on the run overview. Each recommendation links to the
evidence and the affected queries.
