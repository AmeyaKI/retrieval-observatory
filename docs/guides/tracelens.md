# Production — observing retrieval traces

`tracelens` is the internal package and deprecated CLI alias. The public task is `retobs production` and the dashboard page is Production.

Runs show how your pipeline behaves on a fixed evaluation set. Production shows how it is
behaving on real traffic and links those observations back to the same query debugger.

## How it works

Your production pipeline emits `RetrievalTraceV2` traces via a framework adapter (LangChain,
LlamaIndex, FastAPI, or the raw `@observe` SDK — see
[../../retrieval_observatory/integrations/registry.py] and `describe_integration`). Each trace
is the same operator-DAG structure as a benchmark trace, so every retobs view works on
production data too.

## What you get

- **Hotspots** — clusters of production queries sharing a failure pattern.
- **Query lineage** — a production query matched back to its Test Set origin and evaluation
  results, so a live failure is debugged with the full history.
- **Findings correlation** — production hotspots become evidence-scoped findings when a live
  failure pattern matches an evaluation diagnostic.

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

Production is the final step of the retobs workflow: evaluate → understand → debug → improve →
validate → **monitor**. Production traces close the loop by showing whether a fix validated
offline is also behaving as expected on live traffic.
