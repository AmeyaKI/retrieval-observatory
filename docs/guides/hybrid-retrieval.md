# Hybrid retrieval: combining lexical and dense lanes

Lexical (BM25) and dense (embedding) retrieval fail on different queries: BM25 misses paraphrases,
dense retrieval misses exact terms and rare tokens. Running both and fusing recovers documents
either lane alone would miss. retobs shows, per query and per document, which lane found what
and where it was lost.

## Modeling it as an operator DAG

A hybrid pipeline is two `SOURCE` operators feeding a `FUSE` operator (for example reciprocal-rank
fusion). In the trace this is a genuine fan-in: the fusion operator has two parents. Investigate
draws the two lanes and the fan-in edge explicitly; it does not flatten them into a chain.

The `retobs demo` pipeline is a hybrid of exactly this shape (dense and lexical lanes, a recency
filter on the lexical lane, a reranker on each lane, RRF fusion, a gated expansion, and a context selector). See
[investigate your pipeline](investigate-your-pipeline.md).

## Watching a document move

Open a query in Investigate and select a relevant document. Its journey shows which lane
introduced it, whether the other lane also found it, what each lane's operators did to it, and
whether it survived fusion. In the demo, `q-refund`'s `kb:doc-policy` is removed on the lexical
lane by the recency filter and still delivered through the dense lane: a branch removal, not a
final loss. `q-outage`'s `kb:doc-guide` is found only by the lexical lane, so the same filter is
its loss boundary.

## Measuring what a lane buys you

Evaluate the pipeline with and without the second lane on the same judged queries, then audit
the two runs under a policy that guards final recall and nDCG. The audit's changed queries link
into Investigate with `compare=BASELINE`, where each gained or lost document is listed with its
path in both runs. See [retrieval release decisions](retrieval-release-decisions.md).
