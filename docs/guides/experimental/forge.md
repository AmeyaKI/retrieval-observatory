# Test Sets — corpus-specific stress tests

`forge` is the internal engine and deprecated CLI alias. The public task is `retobs testsets`.

Public datasets rarely match your corpus. Test Sets generate evaluation queries **from your own
documents**, targeting specific retrieval failure modes, so you test the pipeline against the
kinds of query it will actually face.

## What Test Sets produce

The generator scans a corpus and builds *scenarios* — query families designed to stress a particular
weakness (for example temporal reasoning, entity disambiguation, multi-hop evidence). Each
generated query is tied to anchor documents, label provenance, and an evidence summary. Extractive
or generated labels remain explicitly unvalidated until a human or trusted process validates them.

## Why it matters for debugging

Because every Test Set query carries its scenario type, Findings can report performance **by
scenario** — telling you not just "recall is low" but "recall is low on temporal queries" —
which points at a specific fix. This is the `by_type` breakdown in
`retrieval_observatory/advisor/recommend.py`.

## Reproducibility

A Test Set is fingerprinted and recorded in the run manifest (`forge_dataset_id` is the legacy
storage key), and
the dataset content hash means two runs are only considered comparable if they used identical
generated data (see the comparability guard in Run Comparison).

## Using it

`retobs demo` builds a Test Set automatically. To generate one directly, run
`retobs testsets generate --corpus corpus.jsonl --output testset/`.
