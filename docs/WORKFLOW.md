# Golden retrieval workflow

## 1. Evaluate

Evaluate the baseline and candidate on the same query, corpus, qrel, and label identities. Each started query persists a complete or partial V2 trace.

## 2. Compare

```bash
retobs compare BASELINE CANDIDATE --format markdown
```

The first positional run is always the baseline; the second is always the candidate. Required identity differences or missing identity make the comparison invalid. Invalid and underpowered results do not produce a winner.

## 3. Find affected queries

Open the largest paired query delta. The query workbench begins with query text, dataset, qrels, and provenance, then shows measured candidate movement through recorded operators.

## 4. Locate the first divergence

For each relevant document, inspect source output, fusion, filtering, and reranking transitions. “First loss operator” is reported only when inputs/outputs reconstruct it. Counterfactual replay is separate and may be unavailable.

## 5. Change and validate

Make the smallest retrieval change supported by the evidence, rerun the same Test Set, and compare the regressed candidate with the validation run. Preserve the Markdown report and standalone HTML as CI artifacts.

The deterministic `retobs demo` executes this whole sequence with a source-depth regression and post-change validation run.
