# Usage

Use retobs in this order: [integrate](INTEGRATIONS.md), [evaluate](START.md), [compare and inspect](WORKFLOW.md), then interpret limits through [evidence and trust](EVIDENCE_AND_TRUST.md).

```bash
retobs integrate . --phase plan --output retobs/integration-plan.json
retobs integrate . --phase apply --plan retobs/integration-plan.json
retobs integrate . --phase verify --plan retobs/integration-plan.json
retobs evaluate mypackage.search:retrieve --queries data/queries.jsonl --qrels data/qrels.jsonl --corpus data/corpus.jsonl
retobs serve --db .retobs/results.db
```

Advanced YAML and remote adapters belong in [YAML_GUIDE.md](YAML_GUIDE.md). They do not replace the plan/review/apply/verify requirement for project integration.
