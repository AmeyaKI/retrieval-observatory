# Manual Instrumentation — one trace from a class-based, multi-module pipeline

`retobs integrate` plans and applies instrumentation for you, but its planner
(`retrieval_observatory/integrations/planner.py`) builds no cross-file call graph: operators it
finds in different files are recorded without parent edges between them, and a project with
several entrypoints still needs manual operator mapping (see `FUTURE_WORK.md`, "Integration").
Use this guide when your pipeline is a `SearchService`-style class whose entrypoint calls lanes,
fusion, and reranking that live in separate modules, and you want every operator's candidates to
land in **one** trace with correct parent edges and op types. You write four
decorators by hand; no agent, no plan file, no `retobs/integration.yaml`.

Every code block below is copied from the runnable example under
`examples/integrations/manual_class_pipeline/`, and
`tests/integration/test_manual_class_pipeline.py` asserts the persisted trace has the shape this
guide describes.

## The example

```text
examples/integrations/manual_class_pipeline/
├── retrievers.py   # KeywordRetriever.search, DenseRetriever.search   → two SOURCE spans
├── fusion.py       # rrf_merge                                        → one FUSE span
├── rerank.py       # OverlapReranker.rerank                           → one RERANK span
└── pipeline.py     # SearchService.search                             → the traced entrypoint
```

Pure Python, no model downloads: a 20-document toy corpus, a token-overlap lane standing in for
BM25, a character-trigram lane standing in for an embedding index, reciprocal rank fusion, and a
phrase-bonus reranker standing in for a cross-encoder. Apply the steps below to your own code in
the same order.

## 1. Wrap the entrypoint so one call persists one trace

`@trace_scope` starts a trace before the entrypoint runs, finishes it when the entrypoint returns
(or fails, recording `status="ERROR"` and the traceback), and writes it to a SQLite database. It
takes the query text from a parameter named `query`, `q`, `question`, or `text`, so a class
method with `self` first works unchanged. From `pipeline.py`:

```python
from retrieval_observatory.sdk.observe import trace_scope

from fusion import rrf_merge
from rerank import OverlapReranker
from retrievers import DenseRetriever, KeywordRetriever

DB_PATH = os.environ.get("RETOBS_DB", ".retobs/manual_class_pipeline.db")
# The store does not create directories; a failed persist is logged as a warning, not raised.
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


class SearchService:
    def __init__(self) -> None:
        self.keyword = KeywordRetriever()
        self.dense = DenseRetriever()
        self.reranker = OverlapReranker()

    @trace_scope(service_id="manual_class_pipeline", pipeline_id="keyword_dense_rrf_rerank", db_path=DB_PATH)
    def search(self, query: str) -> list[dict]:
        keyword_hits = self.keyword.search(query, k=10)
        dense_hits = self.dense.search(query, k=10)
        fused = rrf_merge([keyword_hits, dense_hits], rrf_k=60)
        return self.reranker.rerank(query, fused, k=5)
```

`service_id` and `pipeline_id` scope the trace: the service that emitted it and the topology it
follows. The decorator is a no-op when a trace is already active (a request under
`instrument_fastapi`, or a LangChain/LlamaIndex callback), so it composes instead of nesting.

## 2. Record each operator with `@observe`

`@observe` turns the decorated function's return value into the span's output candidates. It
accepts a list of strings (doc ids), mappings, or objects; a mapping or object contributes
`doc_id` (or `id`), `score`, and optional `rank` and `metadata`. Returning the same shape from
every operator is what gives candidates lineage across stages, because downstream spans match
their inputs to their outputs by `doc_id`. From `retrievers.py`:

```python
class KeywordRetriever:
    """Token-overlap lane. ``op_id="keyword"`` is the name every downstream span refers to."""

    def __init__(self, corpus: dict[str, str] = CORPUS):
        self.corpus = corpus

    @observe("SOURCE", op_id="keyword", replay_policy="NOT_REPLAYABLE")
    def search(self, query: str, k: int = 10) -> list[dict]:
        query_tokens = tokens(query)
        hits = [
            {"doc_id": doc_id, "score": float(len(query_tokens & tokens(text))), "text": text}
            for doc_id, text in self.corpus.items()
        ]
        hits = [hit for hit in hits if hit["score"] > 0]
        hits.sort(key=lambda hit: (-hit["score"], hit["doc_id"]))
        return hits[:k]
```

The second lane is decorated the same way with `op_id="dense"`. Keyword arguments at the call site
(`k=10` above) are stored as the span's `params`; positional arguments are not. Extra keys such as
`text` ride along in the candidate and are visible in the dashboard.

## 3. Wire parent edges across modules

Parent edges are declared, not discovered. `parent_ids` names the `op_id`s whose outputs feed this
operator. `@observe` records the operator's actual arguments (snapshotted before the call) as its
input groups, keyed by those parents; when it cannot tell which argument came from which parent, it
says so in the span's `input_capture` (`positional` for a list of lanes, as here, or `inferred`
when it had to fall back to the parents' recorded outputs). A `CaptureSpec`
(`@observe(..., capture=...)`) records named inputs instead. The referenced spans may live in any
module, as long as they ran earlier in the same entrypoint call. From `fusion.py`:

```python
@observe("FUSE", op_id="rrf", parent_ids=("keyword", "dense"), deterministic=True, replay_policy="EXACT")
def rrf_merge(lanes: list[list[dict]], *, rrf_k: int = 60) -> list[dict]:
    """Merge ranked lists with ``1 / (rrf_k + rank)``.

    ``rrf_k`` is keyword-only so the call site records it as a span param.
    """
```

And from `rerank.py`, whose only parent is the fusion span:

```python
class OverlapReranker:
    """Phrase bonus plus token overlap, standing in for a cross-encoder."""

    @observe("RERANK", op_id="rerank", parent_ids=("rrf",), replay_policy="OBSERVED_ABLATION")
    def rerank(self, query: str, candidates: list[dict], *, k: int = 5) -> list[dict]:
```

A parent id that names a span which has not fired yet is silently dropped from the recorded
`parent_ids`, so call order in the entrypoint matters: lanes, then fusion, then rerank.

## 4. Declare op types

The first argument to `@observe` is the op type: `SOURCE`, `FUSE`, `RERANK`, `BOOST`, `EXPAND`,
`FILTER`, `GATE`, `TRANSFORM`, or `GENERATE`. It drives the stage labels in Investigate and
which transitions are expected at the operator: a `SOURCE` introduces candidates and has no
inputs; a `FILTER` or `RERANK` receives its parents' candidates and removes, demotes, or promotes
them.

The example also passes `replay_policy=` and `deterministic=`. Both are still accepted and
recorded on the span, but nothing in 0.7.0 reads them: counterfactual replay was retired (see
[migrating to focused retobs](migrating-to-focused-retobs.md)). New code can omit them.

## 5. Run it and open the trace

```bash
python examples/integrations/manual_class_pipeline/pipeline.py "hybrid retrieval with reranking"
retobs serve --db .retobs/manual_class_pipeline.db
```

The script prints the top five hits and `trace written to .retobs/manual_class_pipeline.db`. Set
`RETOBS_DB` to write elsewhere. This trace belongs to no evaluation Run, so it has no judgments to
state outcomes against. The server exposes it as recorded:
`GET /dbs/manual_class_pipeline/production/traces?service_id=manual_class_pipeline` lists it, and
`GET /dbs/manual_class_pipeline/production/traces/{trace_id}` returns the spans with their
`parent_ids`, `op_type`, `params`, `input_groups`, capture labels, and `outputs`.

To see where relevant documents are lost, evaluate the same entrypoint on judged queries. Inside
`retobs evaluate` a trace is already active, so `@trace_scope` steps aside and the operator spans
become the Run's trace; open the Run in Investigate (see
[investigate your pipeline](investigate-your-pipeline.md)).

To check a trace in code, read the database the way the test does. From
`tests/integration/test_manual_class_pipeline.py`:

```python
async def _read_traces(db_path: Path):
    store = SQLiteStore(db_path=str(db_path))
    await store.init_db()
    return await store.list_traces(TraceQuery(service_id="manual_class_pipeline"))
```

and assert the shape you wired:

```python
    spans = {span.op_id: span for span in trace.spans}
    assert [span.op_id for span in trace.spans] == ["keyword", "dense", "rrf", "rerank"]
    assert all(span.status == "FIRED" for span in trace.spans)
    assert all(span.outputs and all(candidate.doc_id for candidate in span.outputs) for span in trace.spans)

    assert spans["rrf"].parent_ids == ("keyword", "dense")
    assert spans["rerank"].parent_ids == ("rrf",)
```

`trace.final_op_ids` is `("rerank",)`: the only span nobody names as a parent is the pipeline's
output, which is how the dashboard and evaluation know which candidates were returned.

## Common mistakes

- **Spans without parents.** Forgetting `parent_ids` on fusion or rerank records a valid span with
  empty `input_groups`, so every candidate looks newly introduced there, drop reasons are never
  inferred, and the operator it should have named, now referenced by nobody, joins `final_op_ids`
  as a second "output". Declare parents on every non-source operator.
- **Forgetting the entrypoint scope.** `@observe` with no active trace records nothing and returns
  the function's result unchanged. If the database stays empty, the entrypoint is not wrapped in
  `@trace_scope`, or the operators are called outside it.
- **Reading the database before the write lands.** A synchronous entrypoint persists before it
  returns; an `async def` entrypoint awaits the persist; a synchronous entrypoint called from inside
  a running event loop schedules the write as a background task, so read after the loop settles.
- **A missing directory.** The store does not create `.retobs/`; a failed write is logged as
  `retobs: could not persist trace` and the entrypoint still returns. Create the directory once,
  as `pipeline.py` does.
- **`op_type` left as the wrong thing.** A reranker recorded as `SOURCE` gets no inputs and no
  removals. Pick the op type that matches what the code does to the candidate set.
- **Candidates without doc ids.** Returning bare scores or rows without `doc_id`/`id` makes
  candidates keyed by position, marks their identity evidence `partial`, and breaks lineage across
  stages. Every operator returns rows carrying the same `doc_id`.

## Routing decisions

The SDK has `observe_gate(gate_name, fired, gate_values, op_id=...)`, a context manager that records
a `GATE` span with status `FIRED` or `SKIPPED_BY_GATE`. This example leaves routing out: a gate span
declares no parents and nothing names it as a parent, so it would appear in `final_op_ids` next to
the reranker unless the lane it controls also lists the gate in its `parent_ids`. That wiring is not
covered here.
