# Usage

Use retobs in this order: [connect](INTEGRATIONS.md) the pipeline, [investigate](guides/investigate-your-pipeline.md)
an evaluated Run, [audit](guides/retrieval-release-decisions.md) a baseline against a candidate,
and read the limits in [evidence limitations](guides/evidence-limitations.md).

```bash
retobs integrate . --phase plan --output retobs/integration-plan.json
retobs integrate . --phase apply --plan retobs/integration-plan.json
retobs integrate . --phase verify --db .retobs/results.db
retobs evaluate app/search.py:retrieve --queries data/queries.jsonl --qrels data/qrels.jsonl --corpus data/corpus.jsonl --name search --db .retobs/results.db
retobs serve --db .retobs/results.db
retobs compare BASELINE CANDIDATE --db .retobs/results.db --policy retobs/release-policy.yaml --artifacts artifacts/ --fail-on hold-or-block-or-fail
```

Advanced YAML pipelines and remote adapters are described in [YAML_GUIDE.md](YAML_GUIDE.md)
(`retobs evaluate --config`). They do not replace the plan, review, apply, verify sequence for
instrumenting an existing project.
