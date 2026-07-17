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
retobs integrate . --phase verify --plan retobs/integration-plan.json
```

Review the plan before apply. Required unresolved mappings and stale precondition hashes block mutation. Ready is evidence-backed, not a declaration that a patch command finished. See the [agent runbook](integrations/AGENT_QUICKSTART.md).
