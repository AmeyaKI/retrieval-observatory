# FastAPI Live Trace Verification Run

This is the literal transcript for the live-tracing demo path (Week 1, task 1.4).
Run this sequence to reproduce it. The commands below assume you're in the repo root
with the package installed (`pip install -e ".[demo,dashboard]"`).

## Setup

```
# Fresh DB
rm -f .retobs/fastapi_demo.db

# Start the instrumented FastAPI app
# RETOBS_LATENCY_BUDGET_MS=100 → anything over 100ms triggers latency_over_budget
RETOBS_DB=.retobs/fastapi_demo.db \
RETOBS_TRACE_SERVICE=fastapi-demo \
RETOBS_LATENCY_BUDGET_MS=100 \
python examples/fastapi_search/app.py --port 9191
```

Server output:
```
INFO:     Started server process [...]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:9191
```

## 10 Varied Requests (in a second terminal)

```bash
# Request 1: Normal query
curl -s "http://localhost:9191/search?q=hybrid+retrieval"
# {"query":"hybrid retrieval","results":[{"id":"d1","score":2.54,...},...]}

# Request 2: Normal query
curl -s "http://localhost:9191/search?q=BM25+lexical"
# {"query":"BM25 lexical","results":[{"id":"d2","score":2.04,...},...]}

# Request 3: Empty candidates — no BM25 term matches
curl -s "http://localhost:9191/search?q=xyzzy-qwerty-nonexistent"
# {"query":"xyzzy-qwerty-nonexistent","results":[]}
#   → suspected_failures: ["empty_candidates"]

# Request 4: Slow query (200ms sleep) — triggers latency_over_budget
curl -s "http://localhost:9191/search?q=dense+embeddings&slow=1"
# {"query":"dense embeddings","results":[{"id":"d3",...},...]}
#   → suspected_failures: ["latency_over_budget"]

# Request 5: Another empty query
curl -s "http://localhost:9191/search?q=frobnicator-zqxjkv"
# {"query":"frobnicator-zqxjkv","results":[]}
#   → suspected_failures: ["empty_candidates"]

# Request 6: Normal query
curl -s "http://localhost:9191/search?q=RAG+language+model"
# {"query":"RAG language model","results":[{"id":"d5",...},...]}

# Request 7: Slow query 2
curl -s "http://localhost:9191/search?q=retrieval+benchmark&slow=1"
# {"query":"retrieval benchmark","results":[{"id":"d1",...},...]}
#   → suspected_failures: ["latency_over_budget"]

# Request 8: Normal query
curl -s "http://localhost:9191/search?q=cross-encoder+reranking"
# {"query":"cross-encoder reranking","results":[{"id":"d4",...},...]}

# Request 9: Another empty query
curl -s "http://localhost:9191/search?q=9999999-unique-term"
# {"query":"9999999-unique-term","results":[]}
#   → suspected_failures: ["empty_candidates"]

# Request 10: Normal query
curl -s "http://localhost:9191/search?q=semantic+similarity+embeddings"
# {"query":"semantic similarity embeddings","results":[{"id":"d3",...},...]}
```

## Verification: All 10 Traces with Differentiated Labels

```bash
retobs serve --db .retobs/fastapi_demo.db
# → Open http://localhost:4000, navigate to TraceLens tab
```

Verified trace table (actual output from aiosqlite query):

| # | Query | suspected_failures | latency_ms |
|---|-------|--------------------|------------|
| 1 | hybrid retrieval | [] | 0 |
| 2 | BM25 lexical | [] | 0 |
| 3 | xyzzy-qwerty-nonexistent | ["empty_candidates"] | 0 |
| 4 | dense embeddings | ["latency_over_budget"] | 201 |
| 5 | frobnicator-zqxjkv | ["empty_candidates"] | 0 |
| 6 | RAG language model | [] | 0 |
| 7 | retrieval benchmark | ["latency_over_budget"] | 201 |
| 8 | cross-encoder reranking | [] | 0 |
| 9 | 9999999-unique-term | ["empty_candidates"] | 0 |
| 10 | semantic similarity embeddings | [] | 0 |

**Failure label distribution: 3× empty_candidates, 2× latency_over_budget, 5× no failures.**
All 10 traces appear live in the TraceLens tab. Labels are differentiated — not identical
across all 10.

## Notes for Demo Rehearsal

- The `?slow=1` flag adds a 200ms `asyncio.sleep` to simulate a slow retriever.
- `RETOBS_LATENCY_BUDGET_MS=100` means anything >100ms triggers `latency_over_budget`.
- Queries with no BM25 term matches return empty results → `empty_candidates`.
- `suspected_failures` are computed at ingest by `tracing/enrich.detect_suspected_failures`
  — this is a **heuristic/rule-based** classifier, not a learned model.
- The corpus has 5 docs; most real-word queries return 2–5 results.

## How suspected_failures Are Computed (Honest)

`detect_suspected_failures` in `retrieval_observatory/tracing/enrich.py` applies four
rule-based checks:
1. `empty_candidates` — `len(final_results) == 0`
2. `low_confidence` — top document score ≤ threshold (default 0.0)
3. `high_churn` — candidate drop rate ≥ 0.7 between stages
4. `latency_over_budget` — `total_latency_ms > latency_budget_ms`

These are proxy signals for production failures, not learned failure labels.
