# Trace-Native Verification Status

This matrix tracks the gap between the north star in `THREE_TRACK_PLAN.md` and the current code.
Statuses are intentionally conservative: a feature is only "built" when code, tests, and a user-facing
path all support the claim.

## Status Legend

- **Built** — implemented, tested, and reachable through the intended public path.
- **Partial** — useful implementation exists, but important plan requirements or product paths are missing.
- **Absent** — no meaningful implementation exists.
- **Legacy** — implemented for the older linear `PipelineResult` / `RetrievalTrace` model, not the trace-native DAG model.

## Core Model

| Claim | Status | Code Pointers | Verification |
| --- | --- | --- | --- |
| Per-query operator graph is represented by `RetrievalTraceV2`. | Partial | `retrieval_observatory/tracing/model_v2.py` | Model now includes request/final-operator metadata, split candidate ranks, and `TIMEOUT`; remaining gaps include stricter ingest validation and broader persisted envelope columns. |
| Benchmark `PipelineResult` can be lifted into a faithful V2 DAG. | Partial | `retrieval_observatory/tracing/lift.py`, `tests/unit/test_trace_lift.py` | Fused stages now emit source arm spans followed by a first-class FUSE span with arm provenance; remaining gaps include full fixture-wide metric equivalence and native runner emission. |
| Benchmarks and production traces use one schema. | Partial | `retrieval_observatory/runner/benchmark.py`, `retrieval_observatory/sdk/observe.py`, `retrieval_observatory/tracing/recorder.py` | V2 SDK and ingest exist, but normal benchmark dual-write is off by default and `ro.init()` still records legacy traces. |
| `PipelineResult.snapshots` is retired as persisted truth. | Absent | `retrieval_observatory/store/sqlite.py`, `retrieval_observatory/store/postgres.py`, `retrieval_observatory/metrics/engine.py` | `save_result()` / `get_results()` and snapshot metric computation remain active. |

## Attribution And Replay

| Claim | Status | Code Pointers | Verification |
| --- | --- | --- | --- |
| Operator attribution runs on fired subsets by segment. | Partial | `retrieval_observatory/tracing/attribution.py`, `retrieval_observatory/dashboard/api.py` | Engine exists, but segment grouping lacks plan parameters, qrel access is fragile, and dashboard cells omit CI/replay/low-power details. |
| Replay tiers prevent overclaiming causal effects. | Partial | `retrieval_observatory/tracing/replay.py`, `retrieval_observatory/tracing/model_v2.py` | Replay policy fields exist. BOOST/FUSE/GATE behavior does not yet enforce the plan's evidence contract. |
| Miss provenance identifies responsible operators. | Partial | `retrieval_observatory/tracing/replay.py` | Linear miss attribution exists, but DAG traversal, graph edges, and dashboard/API surfacing are missing. |
| Graph corpus edges support expansion and graph-aware misses. | Partial | `retrieval_observatory/corpus/graph.py`, `retrieval_observatory/store/sqlite.py`, `retrieval_observatory/store/postgres.py` | Edge store exists, but no end-to-end ingest/UI path and async edge checks are not wired into miss attribution. |
| Input variants such as query rewrite or context prefix are attributable. | Absent | `retrieval_observatory/tracing/model_v2.py` | `input_variant` field exists, but there is no measurement path or UI. |

## Dashboard Experience

| Claim | Status | Code Pointers | Verification |
| --- | --- | --- | --- |
| Dashboard mirrors the actual operator DAG. | Absent | `retrieval_observatory/dashboard/api.py`, `retrieval_observatory/dashboard/ui/src/components/StagePipelineFlow.tsx` | Current topology is linear/fused-stage and V2 traces are compat-flattened before display. |
| Segment operator grid exposes replay tiers, CI, and low-power caveats. | Partial | `retrieval_observatory/dashboard/ui/src/components/SegmentOperatorGrid.tsx` | Table exists but displays only raw deltas/status strings. |
| Operator inspector shows params, latency, fire rate, and before/after diffs. | Partial | `retrieval_observatory/dashboard/ui/src/components/OperatorInspector.tsx` | Component exists but is a minimal attribution-row list. |
| Provenance Sankey shows candidate flow. | Absent | `retrieval_observatory/dashboard/ui/src/components/ProvenanceSankey.tsx` | Component is a placeholder and is not wired into the dashboard. |
| Trace waterfall shows span latency and skipped branches. | Absent | `retrieval_observatory/dashboard/ui/src/components/tracelens/TraceDetail.tsx` | TraceLens detail is a legacy linear candidate-flow strip, not a V2 span waterfall. |

## Production And Deployability

| Claim | Status | Code Pointers | Verification |
| --- | --- | --- | --- |
| Decorator-based V2 instrumentation is available. | Partial | `retrieval_observatory/sdk/observe.py`, `tests/integration/test_observe_roundtrip.py` | Happy-path SOURCE round trip exists. API differs from the plan and complex DAG coverage is missing. |
| LangChain/LlamaIndex integrations produce trace-native spans. | Legacy | `retrieval_observatory/tracing/integrations/langchain.py`, `retrieval_observatory/tracing/integrations/llamaindex.py` | Integrations still build legacy snapshots. |
| Remote V2 ingest exists. | Partial | `retrieval_observatory/dashboard/api.py`, `retrieval_observatory/sdk/remote.py` | Run/results/metrics/finish endpoints exist, but no local-vs-remote parity gate and no aggregation on finish. |
| Postgres dashboard serving exists. | Partial | `retrieval_observatory/dashboard/registry.py`, `retrieval_observatory/store/postgres.py` | Registry accepts DSNs; full contract/deploy smoke remains required. |
| Docker serves the full product. | Partial | `Dockerfile`, `docker-compose.yml` | Container scaffold exists, but final UI build and smoke verification are not yet proven. |

## Required Verification Gates

| Gate | Current Status | Target Command |
| --- | --- | --- |
| Full Python suite | Pending | `pytest` |
| Trace lift parity | Partial | `pytest tests/unit/test_trace_lift.py` |
| Replay matrix | Partial | `pytest tests/unit/test_replay.py` |
| Segment attribution parity | Partial | `pytest tests/unit/test_attribution_segments.py` |
| Dashboard build | Pending | `npm run build` from `retrieval_observatory/dashboard/ui` |
| Final compile/factual/UX/CI audit | Pending | Phase 12 checklist in the revamp plan |
