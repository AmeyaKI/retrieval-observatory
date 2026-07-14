# Start with retobs

Use retobs when you have a retrieval callable or service and need to know whether a change regressed retrieval, which queries moved, and where candidates were lost.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install "retrieval-observatory[dashboard]"
```

Extras are task-specific:

| Need | Extra |
|---|---|
| Dashboard/API server | `dashboard` |
| Deterministic demo and local BM25 | `demo` |
| MCP server | `mcp` |
| LangChain callback types | `langchain` |
| LlamaIndex callback types | `llamaindex` |
| PostgreSQL result store | `postgres` |

## Evaluate a callable

Put `QUERIES`, `CORPUS`, and optional `QRELS` next to a retriever function, then run:

```bash
retobs evaluate path/to/eval.py:retrieve
```

JSON/JSONL inputs can instead be supplied with `--queries`, `--corpus`, and `--qrels`. Use `--max-queries` for a bounded smoke run. Use `--config` only for advanced adapter/DAG configuration:

```bash
retobs evaluate --config retobs/config.yaml
```

## Inspect the result

```bash
retobs report RUN_ID --format json
retobs inspect-query RUN_ID QUERY_ID
retobs serve --db .retobs/results.db
```

An evaluation is not automatically a pass. Read its evidence health and limitations, then compare it with an explicit baseline. Continue with the [golden workflow](WORKFLOW.md).
