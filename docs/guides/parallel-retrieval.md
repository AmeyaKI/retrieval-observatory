# Parallel Retrieval — multiple lanes, fused

Parallel retrieval runs several retrievers concurrently and fuses their results. It is the
mechanism behind hybrid retrieval and multi-index setups.

In retobs, parallel lanes are multiple `SOURCE` operators that share a `FUSE` child. The
trace records this as a fan-in (the fusion node has two or more `parent_ids`), and the
architecture view draws the lanes side by side with explicit fan-in edges rather than
flattening them into a line.

Because reciprocal-rank fusion is `EXACT`-replayable, retobs can measure each lane's marginal
contribution precisely by re-running fusion over the remaining lanes
(see [counterfactual-replay.md](counterfactual-replay.md)). Use per-lane attribution to
decide whether a lane earns its latency, and **candidate flow** to watch a document enter from
one lane, fuse, and survive.

For the diagnostics that tell you *whether* to add a lane, and how the lanes complement each
other, see [hybrid-retrieval.md](hybrid-retrieval.md). For gated/conditional routing of lanes,
see [conditional-pipelines.md](conditional-pipelines.md).
