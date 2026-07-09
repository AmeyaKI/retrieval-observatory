# Conditional & Parallel Pipelines — gates, routing, and lanes

Production retrieval is rarely a straight line. Queries get routed by difficulty or type;
some branches are skipped; multiple retrieval lanes run in parallel and fuse. retobs models
these as a real operator DAG (`RetrievalTraceV2`), not a flat stage list, so it can trace and
attribute them accurately.

## Gates and skipped branches

A `GATE` operator routes a query down one branch or another based on `gate_values` recorded in
the trace. When a branch is not taken, its operators are recorded with status
`SKIPPED_BY_GATE` — **and rendered as visibly skipped in the architecture diagram, not
omitted.** Hiding a skipped branch would misrepresent the pipeline you actually wrote.

Attribution is computed per **segment** (`segment_key` in
`retrieval_observatory/tracing/attribution.py`): queries are grouped by their gate values so
you compare like with like, rather than averaging across incomparable routes.

## Parallel retrieval lanes

Multiple `SOURCE` operators feeding a `FUSE` operator are parallel lanes. The trace records
each lane as a separate span with the fusion node as a fan-in (two or more parents). The
architecture view draws the lanes side by side with explicit fan-in edges; per-lane
attribution tells you what each lane contributes (see
[hybrid-retrieval.md](hybrid-retrieval.md)).

## Why trace-native topology matters

The pipeline diagram is built from actual execution traces
(`build_pipeline_graphs` in `retrieval_observatory/pipeline/graph_projection.py`), derived
from each span's `parent_ids` — the true DAG. retobs never infers topology heuristically when
real execution traces exist, so branching, fusion, and skipped nodes are shown as they truly
ran.

## Difficulty-based routing

If hard queries fail disproportionately, the Advisor suggests routing them to a stronger
pipeline. The Query Explorer's predicted-difficulty column and the diagnostics' hard-query
failure rate are the evidence behind that recommendation.
