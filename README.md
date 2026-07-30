# retobs

[PyPI](https://pypi.org/project/retrieval-observatory/)

retobs is a local-first reliability layer for retrieval pipelines. It helps you integrate observable retrieval stages, evaluate a callable, compare Runs under a local release policy, and inspect recorded query and candidate-lineage evidence. It is not an answer evaluator or a leaderboard: when identity, topology, candidates, telemetry, or ground truth are unavailable, retobs reports that limit instead of inferring a conclusion.

## Install

```bash
pip install "retrieval-observatory[dashboard,mcp]"
```

## Integrate an existing project

Create and review a plan before any mutation. Apply consumes that reviewed plan; verify reports readiness only after it observes the declared topology, candidate evidence, and telemetry health.

```bash
retobs integrate . --phase plan --output retobs/integration-plan.json
retobs integrate . --phase apply --plan retobs/integration-plan.json
retobs integrate . --phase verify --plan retobs/integration-plan.json
```

Unresolved required mappings or stale file hashes block apply. The apply result lists every changed file and retains reversal information in its apply record.

## Evaluate a callable

```bash
retobs evaluate mypackage.search:retrieve --queries data/queries.jsonl --qrels data/qrels.jsonl --corpus data/corpus.jsonl
```

Use the returned Run ID with `retobs report`, `retobs compare`, and `retobs inspect-query`. A comparison is valid only when its required identities align; a query diagnosis is limited to evidence actually recorded.

## Gate a retrieval release

Use a local, versioned policy to make the promotion boundary explicit:

```bash
retobs integrate . --phase verify --policy retobs/release-policy.yaml
retobs compare BASELINE CANDIDATE --db .retobs/results.db --policy retobs/release-policy.yaml --format html --output artifacts/retobs-release.html --fail-on hold-or-block-or-fail
```

`PASS` proves bounded non-inferiority under the declared policy; `HOLD` is valid but inconclusive evidence; `BLOCK` is missing or invalid required evidence; and `FAIL` is a proven policy-critical regression. Promotion readiness and lineage-diagnosis readiness remain separate. See [retrieval release decisions](docs/guides/retrieval-release-decisions.md) and the [Candidate Lineage Explorer](docs/guides/candidate-lineage-explorer.md).

## Investigate locally

```bash
retobs serve --db .retobs/results.db
```

The dashboard binds to `127.0.0.1` by default. It is unauthenticated and local-first; put it behind trusted controls before exposing it beyond loopback.

## What retobs records

- Evaluation Runs, manifests, query evidence, and complete or partial operator traces.
- Production traces scoped to a service and pipeline, including candidate transitions when instrumentation provides them.
- Instrumentation health: sampling, drops, serialization failures, retries, and permanent export failures.

These are evidence contracts, not guarantees that every integration can supply every field.

## Integration support

First-class integration paths are plain Python, HTTP, FastAPI, LangChain, and LlamaIndex. DSPy, Haystack, and OpenAI Agents are supported examples with narrower guarantees. See [integration support](docs/INTEGRATIONS.md) and the [agent runbook](docs/integrations/AGENT_QUICKSTART.md).

## Privacy and production safety

Queries, candidates, metadata, labels, and traces may be sensitive. Redaction runs before enqueue and persistence according to the integration manifest; queue capacity, overflow policy, and sampling are explicit telemetry configuration. Read [privacy](docs/PRIVACY.md) and [security](SECURITY.md) before production use.

## Documentation

- [Start](docs/START.md)
- [Workflow](docs/WORKFLOW.md)
- [Concepts](docs/CONCEPTS.md)
- [CLI, SDK, and MCP reference](docs/REFERENCE.md)
- [Retrieval release decisions](docs/guides/retrieval-release-decisions.md)
- [Candidate Lineage Explorer](docs/guides/candidate-lineage-explorer.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Releases](https://github.com/AmeyaKI/retrieval-observatory/releases)

License: [MIT](LICENSE).