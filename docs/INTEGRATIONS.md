# Integration support

Support levels are release claims. The first-class and supported-example paths below exactly match `contracts/public_surface.json`.

| Path | Level | Owner | Tested versions | Capability limit |
|---|---|---|---|---|
| Plain Python | First class | retobs-core | Python 3.10–3.12 | Callable/source discovery depends on inspectable project code. |
| HTTP | First class | retobs-core | HTTP/JSON contract | Final top-K responses are observable; internal operator transitions require emitted snapshots. |
| FastAPI | First class | retobs-core | FastAPI >=0.111; current wheel-only CI resolution | Route and declared topology are verified; readiness still needs observed traffic. |
| LangChain | First class | retobs-core | langchain-core >=0.2; current wheel-only CI resolution | Callback visibility depends on the chain/retriever path used by the application. |
| LlamaIndex | First class | retobs-core | llama-index-core >=0.10; current wheel-only CI resolution | Callback visibility depends on the query-engine path used by the application. |
| DSPy | Supported example | community | Current wheel-only CI resolution | No framework-specific detection or exact project patch guarantee. |
| Haystack | Supported example | community | Current wheel-only CI resolution | No framework-specific detection or exact project patch guarantee. |
| OpenAI Agents | Supported example | community | Current wheel-only CI resolution | No framework-specific detection or exact project patch guarantee. |

A first-class path has detection, an exact patch plan, apply, verification, a real framework wheel-only CI fixture, an owner, a tested version boundary, and documented limits. A supported example has a maintained example only; it does not promise project detection or framework-specific patching.

```bash
retobs integrate . --phase plan --output retobs/integration-plan.json
retobs integrate . --phase apply --plan retobs/integration-plan.json
retobs integrate . --phase verify --policy retobs/release-policy.yaml
```

Review the plan before apply. Required unresolved mappings and stale precondition hashes block mutation. Ready is evidence-backed, not a declaration that a patch command finished. See the [agent runbook](integrations/AGENT_QUICKSTART.md).

## Release-evidence preflight

`integrate --phase verify --policy PATH` reads an explicit local policy and reports promotion readiness separately from lineage-diagnosis readiness. Verification can establish stable candidate identity, stage input/output groups, recorded exits, topology edges, and the latest local telemetry-health snapshot. It cannot establish paired release metrics, so promotion remains `HOLD` until a baseline/candidate comparison is run. Required labels or capture evidence that is unavailable remains `BLOCK`; verification never converts missing evidence into `PASS`.

## OpenTelemetry attribute boundary

`retrieval_observatory.tracing.adapters.otel.normalize_otel_retrieval_trace` maps an already-exported retrieval span without importing an OpenTelemetry SDK. Raw query text and candidate metadata are omitted unless the producer explicitly supplies them. The adapter recognizes these RetObs lineage extension attributes:

| Attribute | Meaning |
|---|---|
| `service.name` or `retobs.service_id` | Trace service identity. |
| `retobs.run_id`, `retobs.query_id`, `retobs.pipeline_id` | RetObs trace scope. |
| `retobs.query_text` | Optional local query text; omit it under redacted capture. |
| `retobs.operator.id`, `retobs.operator.type` | Required stable operator identity and canonical type. |
| `retobs.operator.parent_ids` | Declared operator parents; a standalone span cannot prove these edges and remains partial. |
| `retobs.operator.status`, `retobs.operator.latency_ms` | Optional observed operator status and latency. |
| `retobs.candidates.inputs`, `retobs.candidates.outputs` | JSON objects/arrays of explicitly captured candidates. |
| `retobs.trace.final_op_ids`, `retobs.trace.schema_version` | Optional trace-envelope fields. |
| `retobs.capture.sample_rate`, `retobs.capture.sampled` | Optional capture-health declarations. |

Candidate objects may provide `candidate_id`, `logical_chunk_id`, `doc_id`, `score`, `rank`, `parent_candidate_ids`, `decision_reason`, and `decision_evidence`. Missing stable identity, derived-candidate parents, or recorded removal reasons sets lineage evidence to `partial`; the mapper does not infer transitions or exits. Use the reviewed plan/apply/verify wiring path when standalone standards telemetry does not contain the full retrieval DAG.
