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
chmod +x examples/advanced/hybrid_fiqa_demo/run_demo.sh
./examples/advanced/hybrid_fiqa_demo/run_demo.sh
# or one dataset:
# retobs evaluate --config examples/advanced/hybrid_fiqa_demo/config_scifact.yaml
retobs serve --db .retobs/hybrid_scifact_demo.db
```


Each config defaults to `max_queries: 50` for a ~2–15 minute smoke run (FiQA dense indexing dominates first run). Remove or raise `max_queries` for full BEIR test splits.

## What to inspect in the dashboard

1. **Investigate** (`#/investigate`, choose the run and a pipeline) — the executed DAG with the
   RRF fan-in, per-operator served/received/removed counts, and for each query the relevant
   documents that each lane found and where they were lost.
2. **Audit** (`#/audit`) — compare two runs (for example `hybrid` before and after a change)
   under a v3 policy; changed queries open in Investigate.

## Agent path (MCP)

```text
describe_config → validate_config → evaluate_file (config_fiqa.yaml)
→ get_report / get_pipeline_graph → inspect_query / inspect_document
```

See `docs/integrations/AGENT_QUICKSTART.md`.

## Configs

| File | Dataset | DB output |
|------|---------|-----------|
| `config_fiqa.yaml` | beir/fiqa | `.retobs/hybrid_fiqa_demo.db` |
| `config_scifact.yaml` | beir/scifact | `.retobs/hybrid_scifact_demo.db` |
| `config_nfcorpus.yaml` | beir/nfcorpus | `.retobs/hybrid_nfcorpus_demo.db` |
| `config_scifact_graph.yaml` | beir/scifact | `.retobs/hybrid_scifact_graph_demo.db` |

Expected headline pattern (50-query smoke, approximate): hybrid RRF beats single-channel baselines; rerank adds quality at higher end-to-end latency. Exact numbers vary by machine — compare CIs in the dashboard, not point estimates alone.

### `config_scifact_graph.yaml` — the declarative DAG runner, two merge points

The three configs above use the pre-existing `adapter.rrf` shape: one fusion stage nested inside
a single pipeline entry. `config_scifact_graph.yaml` instead uses the `graphs:` block
(`pipeline/dag.py::DAGPipeline`) to declare a genuinely reconvergent DAG — `bm25` feeds **two**
downstream consumers, and the graph has **two** real merge points:

```
  bm25   ──────────────┬───────────────────────────────────┐
                        ├─ fuse_hybrid (RRF) ── rerank ─────┼─ fuse_final (RRF) ── output
  dense  ──────────────┘                                    │
  bm25   ─────────────────────────────────────────────────────┘  (safety-net re-fusion)
```

`fuse_final` re-injects the raw BM25 arm alongside the reranked candidates, recovering relevant
docs the cross-encoder may have dropped. Run it and open the run in Investigate to see both
`fuse_hybrid` and `fuse_final` as fan-in nodes with `bm25` feeding both:

```bash
retobs evaluate --config examples/advanced/hybrid_fiqa_demo/config_scifact_graph.yaml
retobs serve --db .retobs/hybrid_scifact_graph_demo.db
```

Historical check with 0.6.0 on a real 50-query SciFact run (run id `fdc717bd`, 2026-07-05): the
pipeline-graph projection returned `bm25 → fuse_hybrid` and `bm25 → fuse_final` as `fan_in`
edges (both merge nodes marked `is_merge: true`), and the end-to-end P50 was ~1219ms against the
reranker's stage-local ~33ms. Per-node NDCG@10 with 95% CIs: bm25 0.670 [0.547, 0.787], dense 0.736
[0.631, 0.834], fuse_hybrid 0.785 [0.682, 0.876], rerank 0.741 [0.640, 0.837], fuse_final 0.752
[0.648, 0.857].

## Scope note

The `adapter.rrf`-based configs (`config_fiqa.yaml`, `config_scifact.yaml`, `config_nfcorpus.yaml`)
use a **single RRF merge point** and no recency-boost tail, since BEIR corpora lack per-doc
timestamps. `config_scifact_graph.yaml` demonstrates a genuine **two-merge-point** DAG using the
declarative `graphs:` runner instead. For a small deterministic hybrid pipeline with a recency
filter and a gated expansion, run `retobs demo`.
