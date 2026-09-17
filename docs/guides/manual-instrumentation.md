# Manual Instrumentation — one trace from a class-based, multi-module pipeline

`retobs integrate` plans and applies instrumentation for you, but its planner
(`retrieval_observatory/integrations/planner.py`) builds no cross-file call graph: operators it
finds in different files are recorded without parent edges between them, and a project with
several entrypoints still needs manual operator mapping (see `FUTURE_WORK.md`, "Integration").
Use this guide when your pipeline is a `SearchService`-style class whose entrypoint calls lanes,
fusion, and reranking that live in separate modules, and you want every operator's candidates to
land in **one** trace with correct parent edges, op types, and replay tiers. You write four
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

`service_id` is what the dashboard's Production page groups traces by; `pipeline_id` names the
topology. The decorator is a no-op when a trace is already active (a request under
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
operator; when the span is built, `@observe` looks those ids up in the active trace and copies
their outputs in as the span's `input_groups`. The referenced spans may live in any module, as long
as they ran earlier in the same entrypoint call. From `fusion.py`:

```python
@observe("FUSE", op_id="rrf", parent_ids=("keyword", "dense"), deterministic=True, replay_policy="EXACT")
def rrf_merge(lanes: list[list[dict]], *, rrf_k: int = 60) -> list[dict]:
    """Merge ranked lists with ``1 / (rrf_k + rank)``, the formula counterfactual replay re-runs.

    ``rrf_k`` is keyword-only so the call site records it as a span param; replay reads
    ``params["rrf_k"]`` when it recomputes this fusion without one of its lanes.
    """
```

And from `rerank.py`, whose only parent is the fusion span:

```python
class OverlapReranker:
    """Phrase bonus plus token overlap. A real model is not deterministic, so the replay tier is
    OBSERVED_ABLATION: replay reuses the scores recorded here instead of calling the model again."""

    @observe("RERANK", op_id="rerank", parent_ids=("rrf",), replay_policy="OBSERVED_ABLATION")
    def rerank(self, query: str, candidates: list[dict], *, k: int = 5) -> list[dict]:
```

A parent id that names a span which has not fired yet is silently dropped from the recorded
`parent_ids`, so call order in the entrypoint matters: lanes, then fusion, then rerank.

## 4. Declare op types and replay tiers

The first argument to `@observe` is the op type: `SOURCE`, `FUSE`, `RERANK`, `BOOST`, `EXPAND`,
`FILTER`, `GATE`, `TRANSFORM`, or `GENERATE`. It drives the dashboard's stage labels, the inferred
drop reasons (`reranked_out`, `filtered`, `truncated`), and which counterfactual replay applies.

`replay_policy` defaults to `NOT_REPLAYABLE` for a hand-recorded span, so declare it. The tiers
the DAG runner assigns by op type (`retrieval_observatory/pipeline/dag.py::DEFAULT_REPLAY_POLICY`)
are the ones to copy:

| Tier | Op types | Meaning |
|---|---|---|
| `EXACT` | `FUSE`, `FILTER`, `BOOST` | Replay recomputes the operator from its recorded inputs. |
| `OBSERVED_ABLATION` | `RERANK`, `EXPAND`, `GATE`, `TRANSFORM` | Replay reuses observed scores; the delta is an estimate. |
| `NOT_REPLAYABLE` | `SOURCE`, `GENERATE` | The counterfactual cannot be constructed; attribution reports `indeterminate`. |

Only claim `EXACT` for a fusion whose formula replay actually re-runs: reciprocal rank fusion as
`1 / (rrf_k + rank)` with 1-based ranks, reading the constant from `params["rrf_k"]`. That is why
`rrf_merge` takes `rrf_k` keyword-only and the entrypoint passes it explicitly. See
[counterfactual-replay.md](counterfactual-replay.md) for what each tier promises.

## 5. Run it and open the trace

```bash
python examples/integrations/manual_class_pipeline/pipeline.py "hybrid retrieval with reranking"
retobs serve --db .retobs/manual_class_pipeline.db
```

The script prints the top five hits and `trace written to .retobs/manual_class_pipeline.db`. Set
`RETOBS_DB` to write elsewhere. Open `http://localhost:4000`, go to **Production**, and pick the
`manual_class_pipeline` service (`#/production/manual_class_pipeline`):

- **Overview** counts one trace for the service.
- **Live Traces** lists the query `hybrid retrieval with reranking` with status `OK` and pipeline
  `keyword_dense_rrf_rerank`. Opening it shows four stages, `keyword` and `dense` feeding `rrf`
  feeding `rerank`, each labelled with its op type and candidate count, and the capture summary
  reports `lineage_evidence: recorded`.

The same facts are available without the UI: `GET /production/services` lists the service,
`GET /production/traces?service_id=manual_class_pipeline` lists the trace, and
`GET /production/traces/{trace_id}` returns the spans with their `parent_ids`, `op_type`,
`replay_policy`, `params`, `input_groups`, and `outputs`.

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
- **`op_type` left as the wrong thing.** A reranker recorded as `SOURCE` gets no inputs, no
  `reranked_out` drop reasons, and the wrong replay tier. Pick the op type that matches what the
  code does to the candidate set.
- **Candidates without doc ids.** Returning bare scores or rows without `doc_id`/`id` makes
  candidates keyed by position, marks their identity evidence `partial`, and breaks lineage across
  stages. Every operator returns rows carrying the same `doc_id`.
- **A `k` keyword on the fusion call.** Replay reads the RRF constant from `params["rrf_k"]`, falling
  back to `params["k"]`; a fusion whose top-n limit is passed as `k=` would be replayed with the
  wrong constant. Truncate downstream, or name the limit something else.

## Routing decisions

The SDK has `observe_gate(gate_name, fired, gate_values, op_id=...)`, a context manager that records
a `GATE` span with status `FIRED` or `SKIPPED_BY_GATE`. This example leaves routing out: a gate span
declares no parents and nothing names it as a parent, so it would appear in `final_op_ids` next to
the reranker unless the lane it controls also lists the gate in its `parent_ids`. That wiring is not
covered here.
