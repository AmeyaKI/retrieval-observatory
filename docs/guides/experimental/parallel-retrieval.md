# Parallel retrieval: multiple lanes, fused

Parallel retrieval runs several retrievers and fuses their results. It is the mechanism behind
hybrid retrieval and multi-index setups.

In retobs, parallel lanes are multiple `SOURCE` operators that share a `FUSE` child. The trace
records a fan-in (the fusion operator has two or more `parent_ids`), and Investigate draws the
lanes side by side with explicit fan-in edges rather than flattening them into a line.

To see what a lane contributes, open a query in [Investigate](../investigate-your-pipeline.md)
and follow a relevant document: which lane introduced it, whether another lane also found it,
and whether it survived fusion. A removal on one lane is not a final loss when another lane still
carries the document. When fusion receives lanes positionally (`rrf(*lanes)`), capture a named
input per lane with a `CaptureSpec`; otherwise the inputs are labeled `positional` or `inferred`
(see [evidence limitations](../evidence-limitations.md)).

For the fusion pattern itself, see [hybrid-retrieval.md](../hybrid-retrieval.md). For gated
routing of lanes, see [conditional-pipelines.md](conditional-pipelines.md).
