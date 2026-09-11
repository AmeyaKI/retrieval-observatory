# retobs

[PyPI](https://pypi.org/project/retrieval-observatory/) · [Case study](results/flagship_demo/CASE_STUDY.md)

**Hosted demo (read-only dashboard):** not deployed yet — see [deployment](docs/deployment.md) to publish a public URL.

retobs tells you which stage of your retrieval pipeline earned or destroyed your metric, with attribution you can audit.

A metrics dashboard says *recall 0.5 on query 5abccf67* and stops. retobs records every candidate through every operator, so it can say this instead:

```
bm25_lane        gold 1/2   ranks [1]
dense_lane       gold 2/2   ranks [2, 27]
hybrid_fusion    gold 1/2   !! dropped: karen_dotrice
bridge_hop2      gold 2/2   ranks [1, 45]      <- the second hop found it again
route_merge      gold 1/2   !! dropped: karen_dotrice
final_selection  gold 1/2
```

The vector lane found the missing document at rank 27. Fusion, keeping 40 candidates, dropped it. The two-hop expansion found it again at rank 45. The second merge dropped it again. The fix was one number, merge width 40 to 100, and the same tool then proved the fix held: recall@10 +0.0088, 95% CI [+0.0019, +0.0181], n=400, concentrated in the two-hop questions where a wider merge is the only thing that could help. The full story, including a change that passed every metric while making the system worse, is in the [case study](results/flagship_demo/CASE_STUDY.md).

## Install

```bash
pip install "retrieval-observatory[dashboard,mcp]"
```

## See it work first

One command, no arguments, no API keys. It builds a regression story end to end and hands you a dashboard to explore it.

```bash
retobs demo
retobs serve --db .retobs/demo/results.db
```

Everything below is the same workflow pointed at your own code.

## Integrate an existing project

Plan first, review the plan, then apply. Verify reports ready only after it has seen real traces from the instrumented pipeline.

```bash
retobs integrate . --phase plan --output retobs/integration-plan.json
retobs integrate . --phase apply --plan retobs/integration-plan.json
retobs integrate . --phase verify --plan retobs/integration-plan.json
```

Apply refuses unresolved mappings and stale file hashes, lists every changed file, and keeps reversal information. For agents, the same three phases are one MCP tool; see the [agent runbook](docs/integrations/AGENT_QUICKSTART.md).

## Evaluate a callable

```bash
retobs evaluate mypackage.search:retrieve --queries data/queries.jsonl --qrels data/qrels.jsonl --corpus data/corpus.jsonl
```

The returned Run ID feeds `retobs report`, `retobs compare`, and `retobs inspect-query`.

## Gate a release

```bash
retobs compare BASELINE CANDIDATE --db .retobs/results.db --policy retobs/release-policy.yaml --format html --output artifacts/retobs-release.html --fail-on hold-or-block-or-fail
```

The verdict is one of four words. `PASS`: bounded non-inferiority under the declared policy. `HOLD`: valid but inconclusive. `BLOCK`: required evidence is missing or the two runs are not comparable (different corpus, index, or model revision). `FAIL`: a proven regression on a policy-critical metric. Paired bootstrap confidence intervals, seeded, with multiple-comparison correction. See [retrieval release decisions](docs/guides/retrieval-release-decisions.md).

## Attribution you can audit

Two mechanisms produce the per-stage story above, and both are inspectable in the dashboard and through the SDK.

- **Candidate lineage.** Every candidate's rank and score at the input and output of every operator, recorded by the instrumentation rather than inferred afterwards. When an integration cannot supply a field, retobs reports it as unavailable instead of guessing. See the [Candidate Lineage Explorer](docs/guides/candidate-lineage-explorer.md).
- **Counterfactual replay.** For a given operator, retobs re-executes the recorded trace without it and reports the metric delta, labelled by how trustworthy that replay is: exact, observed ablation, or not replayable. See [counterfactual replay](docs/guides/counterfactual-replay.md).

## Investigate locally

```bash
retobs serve --db .retobs/results.db
```

The dashboard binds to `127.0.0.1` by default and is unauthenticated. Put it behind trusted controls before exposing it beyond loopback.

## What retobs records

Evaluation Runs with their manifests, per-query evidence, and operator traces; production traces scoped to a service and pipeline, including candidate transitions when instrumentation provides them; and instrumentation health (sampling, drops, serialization failures, export failures). A recorded field is a contract about what was observed, not a guarantee that every integration can supply it.

## Integration support

First-class: plain Python, HTTP, FastAPI, LangChain, LlamaIndex. Supported examples with narrower guarantees: DSPy, Haystack, OpenAI Agents. See [integration support](docs/INTEGRATIONS.md).

## Privacy and production safety

Queries, candidates, metadata, labels, and traces may be sensitive. Redaction runs before enqueue and persistence; queue capacity, overflow policy, and sampling are explicit configuration. Read [privacy](docs/PRIVACY.md) and [security](SECURITY.md) before production use.

## Documentation

- [Start](docs/START.md)
- [Workflow](docs/WORKFLOW.md)
- [Concepts](docs/CONCEPTS.md)
- [CLI, SDK, and MCP reference](docs/REFERENCE.md)
- [Guides](docs/guides/README.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Known limitations](FUTURE_WORK.md)
- [Releases](https://github.com/AmeyaKI/retrieval-observatory/releases)

License: [MIT](LICENSE).
