# Counterfactual replay (retired)

Counterfactual replay (re-scoring a recorded trace with one operator removed) and the per-operator
marginal attribution built on it were retired in 0.7.0, along with the attribution grid, miss
attribution, and change simulation.

What remains is descriptive: Investigate shows each candidate's recorded transitions and the
last recorded removal on its path (the loss boundary), labeled recorded or inferred. That is a
fact about the trace, not an estimate of what the metric would have been without an operator.
See [investigate your pipeline](investigate-your-pipeline.md) and
[evidence limitations](evidence-limitations.md).

`@observe(..., replay_policy=...)` is still accepted and recorded on the span; nothing reads it.

Replacements and removed routes: [migrating to focused retobs](migrating-to-focused-retobs.md).
To reproduce published attribution numbers, pin `retrieval-observatory==0.6.0` (repository
revision `29c67b8`).
