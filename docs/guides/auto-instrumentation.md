# Auto-instrumentation — tracing without per-call-site code

Every adapter documented elsewhere (LangChain callbacks, the duck-typed Haystack/DSPy/
OpenAI-Agents wrappers) still asks you to touch each call site: attach a callback, wrap a
component once. Auto-instrumentation removes even that — call one function, and every
retriever call in the process is traced from then on.

## Usage

```python
from retrieval_observatory.tracing.auto_instrument import auto_instrument, stop_auto_instrument
from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace

auto_instrument("langchain")  # opt-in, explicit -- see trade-off below

start_trace(ObserveContext(run_id="run-1", query_id="q1", query_text=query, pipeline_id="main"))
docs = retriever.invoke(query)   # no callbacks=[...] anywhere -- traced automatically
trace = finish_trace()

stop_auto_instrument()  # restores the original, untraced method
```

Today this supports **LangChain only** (`langchain_core.retrievers.BaseRetriever`) — a
proof of concept for the pattern, not a claim that every framework is covered this way.

## How it works

`auto_instrument("langchain")` monkeypatches `BaseRetriever.invoke`/`ainvoke` at the
**class** level: every retriever instance, everywhere in the process, starts emitting a
`SOURCE` `OperatorSpan` onto whatever trace is active (`sdk.observe.current_trace()`) each
time `.invoke()` is called. `stop_auto_instrument()` restores the original methods.

## The trade-off — why this is opt-in, not automatic

This is **global, process-wide mutable state**. Two consequences worth knowing before you
reach for it:

- **Surprising at a distance.** Code far from the call site (a library you didn't write,
  a retriever built before `auto_instrument()` ran) starts behaving differently — emitting
  spans — with no local signal that it's instrumented. This is exactly the kind of
  behavior the platform's Trust principle warns against: nothing should happen that the
  engineer didn't explicitly ask for.
- **Not import-time.** For that reason, `auto_instrument()` is never triggered by
  importing `retrieval_observatory` — it requires an explicit call, and the call is easy
  to grep for later ("who turned this on?").
- **Process-wide, not scoped.** If your process runs multiple retrievers for unrelated
  purposes, all of them get traced once you call this — there's no per-retriever opt-out
  short of not calling `auto_instrument()` at all, or wrapping the specific retriever
  yourself with the LangChain callback instead (see the LangChain guidance in
  `integrations/registry.py` / `describe_integration('langchain')`).

**Recommendation**: use the explicit per-call-site adapters (callbacks, `wrap_*` functions)
in production services where you want tracing scoped to specific retrievers. Reach for
`auto_instrument()` in exploratory/notebook contexts, or when you're certain every
retriever call in the process should be traced and want the lowest-friction path there.

## Extending to other frameworks

The same pattern generalizes: pick the framework's common "retrieve" entry point (a base
class method, in LangChain's case) and monkeypatch it the same way, recording a span via
`sdk.observe.current_trace()`. `tracing/auto_instrument.py` is intentionally small — the
LangChain implementation is the template for adding Haystack/DSPy/OpenAI-Agents-SDK
equivalents later, should that prove worth the added global-state surface for those
frameworks too.
