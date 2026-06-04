# Dashboard spot-check checklist

Use this checklist before tagging a GitHub release. Run against full publish sweep DBs (not smoke runs).

## Prerequisites

```bash
source .venv/bin/activate
pip install -e ".[demo,dashboard,dense]"
retobs serve --db .retobs/publish_sweep_nfcorpus.db \
             --db .retobs/publish_sweep_scifact.db \
             --db .retobs/publish_sweep_fiqa.db \
             --port 8000
```

Open `http://localhost:8000`. Select each DB tab and run `37d3a79c` / `49b423cf` / `0784ed30`.

## NFCorpus (`37d3a79c`)

- [ ] **Pipeline Architecture** — 4 pipelines visible: bm25, bm25__rerank, dense_only, rrf_hybrid
- [ ] **Experiment Overview** — Headline winner shown; difficulty buckets populated; classifier calibration chart renders with easy/medium/hard bars
- [ ] **Stage Attribution (VerdictCard)** — bm25 → bm25__rerank: recall@10 +16%, ndcg@10 +17%, significant q-values
- [ ] **Metrics Summary** — 4 pipeline columns; NDCG@10 ~0.264 (bm25), ~0.310 (dense/rerank)
- [ ] **Stage Recall Funnel** — Stage rows with pipeline-id legend; Recall@K buttons switch K values
- [ ] **Quality–Latency Tradeoff** — 4 points; bm25 and dense_only marked Pareto optimal (stars); bm25__rerank dominated by dense_only
- [ ] **Query Explorer** — Queries load; predicted_difficulty shown where classifier attached

## SciFact (`49b423cf`)

- [ ] **Quality–Latency Tradeoff** — dense_only has highest NDCG@10 (~0.640); bm25 may also show Pareto star (4-objective frontier includes P95)
- [ ] **Metrics Summary** — NDCG@10: bm25 ~0.544, dense ~0.640
- [ ] No classifier calibration section (SciFact sweep has no predictions)

> **Note:** The written analysis uses a 2-objective Pareto (NDCG@10 vs P50 latency). The dashboard API also considers recall@10 and P95, so bm25 can appear Pareto-optimal on SciFact when it wins on tail latency.

## FiQA (`0784ed30`)

- [ ] **Quality–Latency Tradeoff** — dense_only sole Pareto optimal; largest quality spread vs BM25
- [ ] **Metrics Summary** — NDCG@10: bm25 ~0.159, dense ~0.369 (+132% relative)
- [ ] Latency chart shows BM25 P50 ~77 ms vs dense ~9 ms

## Cross-cutting

- [ ] DB tabs switch without errors; no blank panels after load
- [ ] Tradeoff Explorer latency budget slider updates verdict card
- [ ] No console errors in browser devtools
- [ ] Screenshot assets in `results/screenshots/` match live dashboard Pareto layout

## Automated API smoke (optional)

```bash
# Pareto frontier returns 4 pipelines for NFCorpus
curl -s http://localhost:8000/dbs/publish_sweep_nfcorpus/runs/37d3a79c/pareto-frontier | python -m json.tool | head -30

# Classifier calibration present for NFCorpus
curl -s http://localhost:8000/dbs/publish_sweep_nfcorpus/runs/37d3a79c/classifier-calibration | python -m json.tool | head -20
```

## Spot-check log

| Date | DB | Run ID | Checker | Pass |
| ---- | -- | ------ | ------- | ---- |
| 2026-06-03 | publish_sweep_nfcorpus | 37d3a79c | agent (API) | partial — see notes |
| 2026-06-03 | publish_sweep_scifact | 49b423cf | agent (API) | partial |
| 2026-06-03 | publish_sweep_fiqa | 0784ed30 | agent (API) | partial |

_Notes: Automated API checks verify data integrity; visual checklist requires manual browser pass before release._
