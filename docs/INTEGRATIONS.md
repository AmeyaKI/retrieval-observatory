# Integration support levels

Support level is a maintenance claim, not a popularity claim.

| Path | Level | Detection/plan | Minimal patch | Verification | Live CI | Owner |
|---|---|---:|---:|---:|---:|---|
| Plain Python | First class | Yes | Yes | Yes | Yes | retobs-core |
| HTTP endpoint | First class | Yes | Yes | Yes | Yes | retobs-core |
| FastAPI | First class | Yes | Yes | Yes | Yes | retobs-core |
| LangChain | First class | Yes | Yes | Yes | Yes | retobs-core |
| LlamaIndex | First class | Yes | Yes | Yes | Yes | retobs-core |
| Haystack | Supported example | Guide | Wrapper example | Generic trace checks | Yes | community |
| DSPy | Supported example | Guide | Wrapper example | Generic trace checks | Yes | community |
| OpenAI Agents | Supported example | Guide | Wrapper example | Generic trace checks | Yes | community |

First-class means the repository owns detection, a minimal patch plan, category-level verification, a real example/fixture, and a CI path with the actual framework installed. Supported example means the adapter and example are tested but do not promise project detection or framework-specific patching.

Start with `retobs integrate . --plan`. After applying the patch and recording at least one Run/trace, use `retobs verify`. The capability matrix separately reports whether evaluation, operator debugging, candidate transitions, production investigation, and Test Set lineage are safe to use.

See [agent quickstart](integrations/AGENT_QUICKSTART.md) for the plan/patch/verify loop.
