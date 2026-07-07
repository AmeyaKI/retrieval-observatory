# Self-correcting RAG demo

Demonstrates a retrieve → critique → retry topology: a first-pass keyword retriever,
followed by a critique stage that inspects the first pass's confidence (normalized top
score) and, only when it's low, expands the query with synonyms and re-queries the corpus,
merging in anything newly found.

This is the pattern the project's vision doc calls out as the whole point of a DAG-native
tool: pipelines that aren't static linear chains. It's a bounded, two-pass version rather
than a true unbounded loop (the pipeline engine executes a fixed stage list, not a cyclic
graph) — but the retry is a real second retrieval call gated on a real quality judgment, not
a cosmetic rerank.

## Run it

```bash
pip install -e ".[demo]"
python examples/advanced/self_correcting_rag_demo/generate_data.py
PYTHONPATH=examples/advanced/self_correcting_rag_demo retobs run --config examples/advanced/self_correcting_rag_demo/config.yaml
```

## What to look at

Check the `critique_retried` profiling field on the final stage snapshot for each query —
it's `1.0` exactly when the first pass's confidence was below `confidence_threshold` (0.15)
and a real second retrieval call ran.
