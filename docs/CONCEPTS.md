# Product concepts

## Run

A Run is one reproducible evaluation attempt: manifest, queries, qrels, per-query metrics, diagnostics, and complete/partial traces. The manifest records dataset hashes, labeling method, execution settings, models, packages, and source state when available.

## Query lineage

`query_id` connects Test Set origin, run evidence, production matches, findings, and validation history. Every evidence request is explicitly scoped to a database and Run before lineage is joined.

## Operator and candidate transition

A retrieval pipeline is a DAG of typed operators: source, fusion, transform, filter, rerank, boost, and gate. Candidate origin is immutable. Each transition records inputs/outputs, ranks, scores, add/drop reasons, fired/skipped status, cache status, and parent relationships when available.

## Aggregate and exact graph

The aggregate PipelineGraphV2 is the union of observed nodes and real edges across a Run. An exact graph projects one trace and its status. Neither projection invents an edge from topological proximity.

## Comparison validity

Required axes are query hash, corpus hash, qrel hash, and labeling identity. Optional execution/model/source differences remain visible warnings. Statistics use paired query alignment, BH correction, effect thresholds, and a minimum-power state.

## Test Set

A Test Set has one versioned summary and per-query provenance. Rule-based, extractive, LLM-generated, judge-labeled, and human-validated evidence remain distinct. Generated qrels are not gold by default.

## Production finding

A production hotspot or drift finding states method, sample, denominator, time window, baseline, threshold, evidence class, and supporting trace IDs. Without explicit ground-truth joining it is a proxy signal, not retrieval quality.
