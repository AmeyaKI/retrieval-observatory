"""Applied instrumentation must not break an application that does not run from the project root.

A subpackage run with its own directory as the working directory (a worker, ``python -m`` from a
package dir, a test runner elsewhere) has no project root on ``sys.path``; the operator's
``CaptureSpec`` must still resolve from the root ``retobs_adapter.py``.
"""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

from retrieval_observatory.integrations.apply import apply_integration_plan
from retrieval_observatory.integrations.planner import build_integration_plan

PIPELINE = (
    "def keyword_search(query): return [{'id': 'a', 'score': 1.0}, {'id': 'b', 'score': 0.5}]\n"
    "def rerank(query, candidates): return list(reversed(candidates))\n"
    "def retrieve(query): return rerank(query, keyword_search(query))\n"
)
ADAPTER = (
    "from retrieval_observatory.tracing.capture import CaptureSpec\n"
    "rerank_capture = CaptureSpec(inputs=lambda bound: {'keyword_search': bound.arguments['candidates'][:1]})\n"
)
RUN = (
    "import json\n"
    "from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace\n"
    "import pipeline\n"
    "start_trace(ObserveContext(None, 'q1', 'widget pricing', 'pipe', 'svc'))\n"
    "returned = pipeline.retrieve('widget pricing')\n"
    "trace = finish_trace()\n"
    "span = next(span for span in trace.spans if span.op_id == 'rerank')\n"
    "print(json.dumps({'returned': returned, 'input_capture': span.input_capture,\n"
    "    'groups': {key: [c.doc_id for c in value] for key, value in span.input_groups.items()},\n"
    "    'failures': list(trace.capture_failures)}))\n"
)


def test_instrumented_subpackage_imports_and_captures_without_the_root_on_sys_path(tmp_path: Path) -> None:
    root = tmp_path / "project"
    package = root / "services" / "worker"
    package.mkdir(parents=True)
    (root / "services" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "pipeline.py").write_text(PIPELINE, encoding="utf-8")
    (root / "retobs_adapter.py").write_text(ADAPTER, encoding="utf-8")
    plan = build_integration_plan(root, db_path=str(tmp_path / "results.db"))
    reviewed = replace(plan, operators=tuple(
        replace(op, capture="retobs_adapter:rerank_capture") if op.op_id == "rerank" else op
        for op in plan.operators if op.op_id != "retrieve"
    ))
    apply_integration_plan(build_integration_plan(root, db_path=str(tmp_path / "results.db"), reviewed=reviewed))

    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    completed = subprocess.run(
        [sys.executable, "-c", RUN], cwd=package, env=env, capture_output=True, text=True, timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    observed = json.loads(completed.stdout.strip().splitlines()[-1])
    assert observed["returned"] == [{"id": "b", "score": 0.5}, {"id": "a", "score": 1.0}]
    assert observed["input_capture"] == "recorded"
    # The adapter maps only the first candidate: the default parameter capture would record both.
    assert observed["groups"] == {"keyword_search": ["a"]}
    assert observed["failures"] == []
