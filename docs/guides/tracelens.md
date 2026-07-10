# TraceLens — observing production retrieval

Benchmarks tell you how your pipeline does on a fixed eval set. TraceLens tells you how it is
doing **in production**, on real traffic — and links production behavior back to the same
query-centric debugging tools.

## How it works

Your production pipeline emits `RetrievalTraceV2` traces via a framework adapter (LangChain,
LlamaIndex, FastAPI, or the raw `@observe` SDK — see
[../../retrieval_observatory/integrations/registry.py] and `describe_integration`). Each trace
is the same operator-DAG structure as a benchmark trace, so every retobs view works on
production data too.

## What you get

- **Hotspots** — clusters of production queries sharing a failure pattern.
- **Query lineage** — a production query matched back to its Forge origin and benchmark
  results, so a live failure is debugged with the full history.
- **Advisor correlation** — production hotspots feed the Advisor, which flags when a live
  failure pattern matches a benchmark diagnostic.

## Verifying the integration

After wiring an adapter, run:

```bash
retobs doctor
```

`doctor` runs the integration checklist — traces present, metadata completeness, unsupported
operators, error/timeout rate, sampling signal — so you know instrumentation is healthy
*before* you rely on the data (`verify_integration` in
`retrieval_observatory/integrations/verify.py`).

## Monitoring as the end of the loop

TraceLens is the final step of the retobs workflow: run → understand → debug → improve →
validate → **monitor**. Production traces close the loop by telling you whether a fix that
worked on the benchmark is actually working live.
