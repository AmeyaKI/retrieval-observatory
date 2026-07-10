# Forge — corpus-specific stress tests

Public benchmarks rarely match your corpus. Forge generates evaluation queries **from your own
documents**, targeting specific retrieval failure modes, so you test the pipeline against the
kinds of query it will actually face.

## What Forge produces

Forge scans a corpus and builds *scenarios* — query families designed to stress a particular
weakness (for example temporal reasoning, entity disambiguation, multi-hop evidence). Each
generated query is tied to anchor documents and an evidence summary, so its ground truth is
grounded in real corpus content rather than guessed.

## Why it matters for debugging

Because every Forge query carries its scenario type, the Advisor can report performance **by
scenario** — telling you not just "recall is low" but "recall is low on temporal queries" —
which points at a specific fix. This is the `by_type` breakdown in
`retrieval_observatory/advisor/recommend.py`.

## Reproducibility

A Forge dataset is fingerprinted and recorded in the run manifest (`forge_dataset_id`), and
the dataset content hash means two runs are only considered comparable if they used identical
generated data (see the comparability guard in Run Comparison).

## Using it

`retobs quickstart` and `retobs demo` both run Forge automatically. To generate a stress set
directly, see the Forge commands in [../USAGE.md](../USAGE.md).
