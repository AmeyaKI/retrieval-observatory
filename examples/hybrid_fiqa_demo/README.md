# Hybrid DAG demo (BEIR FiQA · SciFact · NFCorpus)

Showcases retobs on a **real hybrid retrieval DAG** at laptop-friendly scale:

```
            ┌─ BM25 ─────────────┐
  query ────┤                    ├─ RRF fuse ── cross-encoder rerank ── output
            └─ MiniLM bi-encoder ┘
```

Ablation prefix chain (from `combinations.ablations: true`):

- `hybrid` · `hybrid__rerank` · plus standalone `bm25_only` and `dense_only`

## Quick start

Requires the `[dense]` extra (`sentence-transformers`, `faiss-cpu`):

```bash
pip install -e ".[dense,dashboard]"
chmod +x examples/hybrid_fiqa_demo/run_demo.sh
./examples/hybrid_fiqa_demo/run_demo.sh
retobs serve --db .retobs/hybrid_fiqa_demo.db
```

Each config defaults to `max_queries: 50` for a ~2–15 minute smoke run (FiQA dense indexing dominates first run). Remove or raise `max_queries` for full BEIR test splits.

## What to inspect in the dashboard

1. **Architecture** — SVG DAG with MERGE node on RRF; CIs on every node.
2. **Tradeoffs** — scatter uses **end-to-end P50** latency (not reranker-only).
3. **Verdict** — CI-aware ranking medals; stage ablation attribution for `hybrid → hybrid__rerank`.

## Agent path (MCP)

```text
describe_config → validate_config → benchmark_config (config_fiqa.yaml as JSON)
→ verify_integration → get_pipeline_diagram / get_pareto_frontier
```

See `docs/integrations/AGENT_QUICKSTART.md`.

## Configs

| File | Dataset | DB output |
|------|---------|-----------|
| `config_fiqa.yaml` | beir/fiqa | `.retobs/hybrid_fiqa_demo.db` |
| `config_scifact.yaml` | beir/scifact | `.retobs/hybrid_scifact_demo.db` |
| `config_nfcorpus.yaml` | beir/nfcorpus | `.retobs/hybrid_nfcorpus_demo.db` |

Expected headline pattern (50-query smoke, approximate): hybrid RRF beats single-channel baselines; rerank adds quality at higher end-to-end latency. Exact numbers vary by machine — compare CIs in the dashboard, not point estimates alone.

## Screenshots

After running the demo, regenerate dashboard screenshots with:

```bash
retobs serve --db .retobs/hybrid_fiqa_demo.db
python scripts/generate_dashboard_screenshots.py  # if configured for your run id
```

Pre-REVAMP screenshots in `results/screenshots/` used final-stage latency on the tradeoff chart — re-capture after this branch for accurate e2e-latency plots.

## Scope note

This demo uses a **single RRF merge point** (no recency-boost tail) because BEIR corpora lack per-doc timestamps. For the full bm25 → hybrid → rerank → boost chain see `examples/complex_rag_demo/`.
