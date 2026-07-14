# retobs

[![PyPI](https://img.shields.io/pypi/v/retrieval-observatory)](https://pypi.org/project/retrieval-observatory/)
[![CI](https://github.com/AmeyaKI/retrieval-observatory/actions/workflows/ci.yml/badge.svg)](https://github.com/AmeyaKI/retrieval-observatory/actions/workflows/ci.yml)

**retobs is a local-first retrieval reliability layer for multi-stage RAG pipelines.** It helps ML engineers evaluate a retriever, compare a baseline and candidate, and trace a failed query to the operator and candidate transition that actually occurred.

It is not an answer evaluator or a leaderboard. Conclusions are withheld when ground truth, run identity, paired samples, or replay evidence is insufficient.

## Five-minute callable quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install "retrieval-observatory[dashboard]"
```

Create `retrieval_eval.py`:

```python
CORPUS = {
    "d1": "Hybrid retrieval combines lexical and dense search.",
    "d2": "A reranker rescores an existing candidate set.",
}
QUERIES = [
    {"query_id": "q1", "text": "What combines lexical and dense search?"},
]
QRELS = {"q1": {"d1": 1}}

def retrieve(query: str) -> list[str]:
    return ["d1", "d2"] if "lexical" in query else ["d2", "d1"]
```

Evaluate it without YAML:

```bash
retobs evaluate retrieval_eval.py:retrieve --format terminal
retobs serve --db .retobs/results.db
```

The command prints a run ID, evidence health, a conclusion, affected queries, and the next action. Open the printed Run URL to inspect recorded operator and candidate evidence. The same path is available in Python:

```python
import retrieval_observatory as ro
from retrieval_eval import CORPUS, QRELS, QUERIES, retrieve

report = ro.evaluate(retrieve, queries=QUERIES, corpus=CORPUS, qrels=QRELS)
print(report.run_id)
print(report.to_json())
```

## Baseline-to-cause workflow

Run an explicit baseline and candidate, then compare them in that order:

```bash
retobs compare BASELINE_RUN CANDIDATE_RUN --db .retobs/results.db --format markdown
retobs inspect-query CANDIDATE_RUN QUERY_ID --db .retobs/results.db
```

`compare` first validates query, corpus, qrel, and label identity. An invalid comparison has no winner. Valid comparisons use paired query alignment, Benjamini-Hochberg correction, declared effect thresholds, and power labels. The Query page then shows:

- query text, dataset, qrels, and label provenance;
- exact recorded operator spans and terminal/partial status;
- relevant documents added, promoted, demoted, or dropped;
- the first measured loss operator when reconstructable;
- replay separately labeled as exact, observed ablation, or unavailable;
- an evidence-backed next action and validation link.

Try the deterministic local story:

```bash
pip install "retrieval-observatory[demo,dashboard]"
retobs demo --db .retobs/demo/results.db --output-dir .retobs/demo
retobs serve --db .retobs/demo/results.db
```

It creates one Test Set, a healthy baseline, a regressed candidate, a post-change validation run, and sampled production traces. No API key is required.

![Query debugger showing measured relevant-document movement](https://raw.githubusercontent.com/AmeyaKI/retrieval-observatory/main/docs/assets/query-debugger.png)

[Watch the short regression-to-validation workflow](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/assets/retrieval-debugging-loop.webm).

## Core capabilities

| Task | What retobs provides |
|---|---|
| **Evaluate** | Callable-first or advanced YAML execution with per-query metrics, canonical manifests, complete/partial traces, and reports. |
| **Compare** | Explicit baseline/candidate orientation, validity gating, corrected paired statistics, config/topology differences, and affected queries. |
| **Debug** | Query-to-operator-to-candidate evidence with exact and aggregate PipelineGraphV2 views. |
| **Production** | Sampled traces, drift/hotspot methods, windows, thresholds, denominators, and supporting trace links. Quality is absent without joined ground truth. |
| **Test Sets** | Corpus-derived stress queries with dataset/query label provenance, validation coverage, exact Run links, and paginated tables. |

Primary dashboard navigation is **Home, Runs, Compare, Queries, Production, Test Sets**. Forge, TraceLens, Advisor, and Benchmarks remain internal/legacy vocabulary rather than separate products.

## Integration support

First-class paths are plain Python, HTTP, FastAPI, LangChain, and LlamaIndex. Haystack, DSPy, and OpenAI Agents are supported examples with a narrower maintenance guarantee. See the [support matrix](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/INTEGRATIONS.md) and the [agent quickstart](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/integrations/AGENT_QUICKSTART.md).

To inspect before changing a project:

```bash
retobs integrate . --plan
retobs verify --db .retobs/results.db
```

Agents can call MCP `plan_integration`, apply the returned patch, then call `verify_integration`. A result is `ready`, `partially_instrumented`, `not_verified`, or `failed`; zero observed runs is never ready.

## Trust model

- **Measured** means persisted execution, qrel, metric, or candidate-transition evidence.
- **Statistical** means a declared paired procedure with sample size, effect, correction, and power state.
- **Replayed** means a supported counterfactual under listed assumptions.
- **Heuristic** and **inferred** are visibly labeled and never promoted to causal proof.
- **Unavailable** is a first-class result; retobs does not manufacture a delta or quality score.

Wall-clock, critical-path, and operator-sum latency are distinct fields. Production proxy signals are not Recall. Generated/extractive labels are not called gold until validated. Full rules are in [Evidence and trust](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/EVIDENCE_AND_TRUST.md).

## Reports and CI

Terminal, JSON, Markdown, and standalone HTML share one report model:

```bash
retobs report RUN_ID --format html --output retobs-run.html
retobs compare BASELINE CANDIDATE \
  --format markdown --output retobs-comparison.md \
  --fail-on regression-or-no-decision
```

See the [PR workflow](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/PR_WORKFLOW.md) and [CI gating reference](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/informative/ci_gating.md).

## Local-first scope

SQLite and PostgreSQL stores are supported. The dashboard is single-tenant and has no authentication by default; do not expose it directly to an untrusted network. Query text, document identifiers/metadata, traces, and generated Test Set content may be sensitive. See [Data and privacy](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/PRIVACY.md) and [Security policy](https://github.com/AmeyaKI/retrieval-observatory/blob/main/SECURITY.md).

## Documentation

- [Start](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/START.md)
- [Golden workflow](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/WORKFLOW.md)
- [Concepts](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/CONCEPTS.md)
- [CLI/SDK/MCP reference](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/REFERENCE.md)
- [Advanced YAML guide](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/YAML_GUIDE.md)
- [Architecture](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/ARCHITECTURE.md)
- [Migration and deprecations](https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/MIGRATION.md)
- [Contributing](https://github.com/AmeyaKI/retrieval-observatory/blob/main/CONTRIBUTING.md) and [releases](https://github.com/AmeyaKI/retrieval-observatory/releases)

License: [MIT](https://github.com/AmeyaKI/retrieval-observatory/blob/main/LICENSE).
