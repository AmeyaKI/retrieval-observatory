"""A ``retobs_adapter.py`` that imports from the module it instruments.

Adapters commonly import the application's result type to map it. The decorated module is still
executing while its decorators run, so an adapter loaded then sees a partially initialized module.
The reference must resolve anyway (the application's import never fails because of it) and the
adapter's mapping must be the one applied.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ADAPTER = (
    "from retrieval_observatory.tracing.capture import CaptureSpec\n"
    "from pkg.stage import Ranked\n"
    "spec = CaptureSpec(outputs=lambda result: result.hits[:1] if isinstance(result, Ranked) else None)\n"
)
RANKED = (
    "class Ranked:\n"
    "    def __init__(self, hits): self.hits = hits\n"
)
STAGE = (
    "from retrieval_observatory.sdk.observe import observe\n"
    "@observe('RERANK', op_id='stage', capture='retobs_adapter:spec')\n"
    "def stage(query): return Ranked([{'id': 'a', 'score': 1.0}, {'id': 'b', 'score': 0.5}])\n"
)
RUN = (
    "import json, sys\n"
    "from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, start_trace\n"
    "import pkg.stage\n"
    "start_trace(ObserveContext(None, 'q1', 'widget pricing', 'pipe', 'svc'))\n"
    "returned = pkg.stage.stage('widget pricing')\n"
    "trace = finish_trace()\n"
    "span = next(span for span in trace.spans if span.op_id == 'stage')\n"
    "print(json.dumps({'type': type(returned).__name__, 'outputs': [c.doc_id for c in span.outputs],\n"
    "    'output_capture': span.output_capture, 'failures': [f['code'] for f in trace.capture_failures],\n"
    "    'stage_complete': hasattr(sys.modules['pkg.stage'], 'Ranked')}))\n"
)


@pytest.mark.parametrize("ranked", ["above", "below"])
def test_an_adapter_importing_the_instrumented_module_resolves(tmp_path: Path, ranked: str) -> None:
    root = tmp_path / "project"
    package = root / "services" / "app" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "stage.py").write_text(RANKED + STAGE if ranked == "above" else STAGE + RANKED, encoding="utf-8")
    (root / "retobs_adapter.py").write_text(ADAPTER, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    env = {**{key: value for key, value in os.environ.items() if key != "PYTHONPATH"}, "PYTHONPATH": str(root / "services" / "app")}
    completed = subprocess.run([sys.executable, "-c", RUN], cwd=elsewhere, env=env, capture_output=True, text=True, timeout=60)

    assert completed.returncode == 0, completed.stderr
    observed = json.loads(completed.stdout.strip().splitlines()[-1])
    assert observed == {"type": "Ranked", "outputs": ["a"], "output_capture": "recorded", "failures": [], "stage_complete": True}
    assert "uses default capture" not in completed.stderr
