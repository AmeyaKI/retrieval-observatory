"""An agent told "wire retobs into this project" must succeed on three project shapes through
MCP integrate_project plan -> apply -> verify, then evaluate — with no setup beyond calling the
project's own entrypoint once. Each project runs in a subprocess from a pristine tmp copy."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from retrieval_observatory.mcp.server import _integrate_project

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
from integration_projects import PROJ_B_EVAL_TARGET, materialize  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

EXERCISE = {
    "proj_a": "from search.retriever import retrieve; retrieve('lexical sparse retriever', k=3)",
    "proj_b": (
        "from fastapi.testclient import TestClient\nfrom app.main import app\n"
        "with TestClient(app) as c:\n"
        "    assert c.post('/search', json={'q': 'lexical sparse retriever', 'k': 2}).status_code == 200\n"
    ),
    "proj_c": "from rag.retriever import build_retriever; build_retriever(k=3).invoke('lexical sparse retriever')",
}
EVALUATE_TARGET = {"proj_a": "search.retriever:retrieve", "proj_b": "retobs_eval.py:PIPELINE", "proj_c": "rag/eval_target.py:retriever"}
EXPECTED_PLAN = {
    "proj_a": ("python", [("retrieve", "SOURCE")], ("search/retriever.py", "retrieve")),
    "proj_b": ("fastapi", [("Searcher.search", "SOURCE"), ("Searcher.rerank", "RERANK")], ("app/main.py", "search")),
    "proj_c": ("langchain", [("KeywordRetriever._get_relevant_documents", "SOURCE")], ("rag/retriever.py", "KeywordRetriever._get_relevant_documents")),
}
REQUIRES = {"proj_a": None, "proj_b": "fastapi", "proj_c": "langchain_core"}


def _run(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    return subprocess.run([sys.executable, *argv], cwd=root, env=env, capture_output=True, text=True, timeout=180)


@pytest.mark.parametrize("name", ["proj_a", "proj_b", "proj_c"])
async def test_plan_apply_call_verify_evaluate(name: str, tmp_path: Path) -> None:
    if REQUIRES[name]:
        pytest.importorskip(REQUIRES[name])
    root = materialize(name, tmp_path)
    framework, operators, (entry_file, entry_symbol) = EXPECTED_PLAN[name]

    planned = await _integrate_project(project_root=str(root), phase="plan")
    plan = planned["plan"]
    assert planned["status"] == "planned"
    assert plan["framework"] == framework
    assert [(op["symbol"], op["op_type"]) for op in plan["operators"]] == operators
    assert plan["discovery"]["entrypoint"]["file"] == entry_file
    assert plan["discovery"]["entrypoint"]["symbol"] == entry_symbol
    assert not any(op["symbol"].startswith("test_") for op in plan["operators"])
    assert not any("test" in patch["relative_path"] for patch in plan["patches"])
    plan_path = root / "retobs" / "integration-plan.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(planned, indent=2), encoding="utf-8")

    applied = await _integrate_project(project_root=str(root), phase="apply", plan_path=str(plan_path))
    assert applied["status"] == "applied"
    assert "retobs/integration.yaml" in applied["changed_files"]
    assert "@trace_scope(" in (root / entry_file).read_text(encoding="utf-8")

    # Verify before any call names exactly what it looked for.
    empty = await _integrate_project(project_root=str(root), phase="verify")
    assert empty["status"] == "failed"
    assert f"service_id={plan['service_id']!r}" in empty["errors"][0]
    assert f"pipeline_id={plan['pipeline_id']!r}" in empty["errors"][0]
    assert str(root / ".retobs" / "results.db") in empty["errors"][0]

    exercised = _run(root, "-c", EXERCISE[name])
    assert exercised.returncode == 0, exercised.stderr
    assert "could not persist trace" not in exercised.stderr

    verified = await _integrate_project(project_root=str(root), phase="verify", plan_path=str(plan_path))
    assert verified["status"] == "ready", verified["errors"]
    assert set(verified["observed_operator_ids"]) == {op["op_id"] for op in plan["operators"]}

    if name == "proj_b":
        (root / "retobs_eval.py").write_text(PROJ_B_EVAL_TARGET, encoding="utf-8")
    evaluated = _run(
        root, "-m", "retrieval_observatory.cli", "evaluate", EVALUATE_TARGET[name],
        "--queries", "data/queries.jsonl", "--corpus", "data/corpus.jsonl", "--qrels", "data/qrels.jsonl",
        "--format", "json", "--db", ".retobs/results.db",
    )
    assert evaluated.returncode == 0, evaluated.stderr[-2000:]
    assert "Benchmarking" not in evaluated.stdout
    report = json.loads(evaluated.stdout)
    assert report["evidence_health"] == "ready"
    names = {key.split("|")[2] for key in report["metrics"]}
    assert {"ndcg@10", "recall@10"} <= names
    assert not ({"recall@1", "recall@5"} & names)
