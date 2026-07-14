from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from retrieval_observatory.integrations.detect import DetectionResult, detect_project
from retrieval_observatory.integrations.registry import SUPPORT_LEVELS, describe_integration
from retrieval_observatory.integrations.verify import dashboard_base_url, verify_integration

DEFAULT_DB_PATH = ".retobs/results.db"
DEFAULT_SERVE_PORT = 4000

RETRIEVER_STUB = '''"""Custom retriever factory for retobs adapter.import.

Replace KeywordOverlapRetriever with your production retriever class.
Factory signature: (corpus, stage_cfg, **kwargs) -> (adapter, k)
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from retrieval_observatory.types import Document, Query, RetrievalResult


class KeywordOverlapRetriever:
    def __init__(self, corpus: Dict[str, str], retriever_id: str = "my_retriever"):
        self.retriever_id = retriever_id
        self._corpus = corpus

    def retrieve(self, query: Query) -> RetrievalResult:
        q_tokens = set(query.text.lower().split())
        scored = [
            (doc_id, len(q_tokens & set(text.lower().split())))
            for doc_id, text in self._corpus.items()
            if q_tokens & set(text.lower().split())
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[: query.k]
        documents = [
            Document(id=doc_id, text=self._corpus[doc_id], score=float(score), rank=rank)
            for rank, (doc_id, score) in enumerate(top, start=1)
        ]
        return RetrievalResult(documents=documents, latency_ms=0.0, retriever_id=self.retriever_id)


def build_retriever(
    corpus: Optional[Dict[str, str]],
    stage_cfg: dict,
    **kwargs,
) -> Tuple[KeywordOverlapRetriever, int]:
    if corpus is None:
        raise ValueError("build_retriever requires a corpus from the dataset loader.")
    cfg = stage_cfg.get("config", {})
    k = int(cfg.get("k", 10))
    retriever_id = stage_cfg.get("retriever_id", "my_retriever")
    return KeywordOverlapRetriever(corpus, retriever_id=retriever_id), k
'''

INSTRUMENT_STUB = '''"""retobs instrumentation stub — wire into your RAG pipeline."""
from __future__ import annotations

import retrieval_observatory as ro
from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, observe, start_trace

recorder = ro.init(service="my-rag", db=".retobs/prod.db")


@observe(op_type="SOURCE", op_id="my_retriever")
def retrieve(query: str):
    """Replace with your retrieval logic."""
    raise NotImplementedError("Wire your retriever here")


def traced_query(run_id: str, query_id: str, query_text: str) -> None:
    start_trace(
        ObserveContext(
            run_id=run_id,
            query_id=query_id,
            query_text=query_text,
            pipeline_id="main",
        )
    )
    retrieve(query_text)
    finish_trace()
'''

SAMPLE_QUERIES = (
    '{"query_id":"q1","text":"What is hybrid retrieval?","relevant_doc_ids":{"d1":2},"tags":["sample"]}\n'
)
SAMPLE_CORPUS = (
    '{"id":"d1","title":"Hybrid retrieval","text":"Hybrid retrieval combines lexical and dense search.","timestamp":"2024-01-01T00:00:00","source":"sample"}\n'
    '{"id":"d2","title":"Reranking","text":"Rerankers rescore candidate documents for a query.","timestamp":"2024-01-02T00:00:00","source":"sample"}\n'
)
SAMPLE_QRELS = '{"q1":{"d1":2}}\n'

CURSOR_RULE = '''---
description: retobs is wired in this project — use manifest and RETOS.md for commands
globs:
alwaysApply: true
---

# retobs integration

This project has retobs wired. Read `.retobs/manifest.yaml` and `RETOS.md` before running evaluations or traces.

- Initial wiring: MCP `wire_project(project_root)` then `wire_project(phase="verify")`
- Evaluate: `retobs evaluate --config retobs/config.yaml` or MCP `evaluate_file`
- Dashboard: `retobs serve --db .retobs/results.db`
'''


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("retrieval-observatory")
    except Exception:
        return "unknown"


def bootstrap_config_yaml(experiment_name: str, factory: str) -> str:
    return f"""experiment:
  name: {experiment_name}

dataset:
  type: custom
  name: custom
  queries_path: queries.jsonl
  corpus_path: corpus.jsonl
  qrels_path: qrels.jsonl

pipelines:
  - id: main
    stages:
      - type: adapter.import
        retriever_id: my_retriever
        config:
          factory: {factory}
          k: 10

metrics:
  recall_at_k: [5, 10]
  ndcg_at_k: [10]

output:
  store: sqlite
  db_path: .retobs/results.db
"""


def post_wiring_commands(project_root: Path, config_path: Path) -> Dict[str, str]:
    rel_config = config_path.relative_to(project_root) if config_path.is_relative_to(project_root) else config_path
    return {
        "evaluate": f"retobs evaluate --config {rel_config}",
        "serve": f"retobs serve --db {DEFAULT_DB_PATH}",
        "verify_cli": "retobs verify .",
        "smoke_evaluate_mcp": f"evaluate_file(config_path='{config_path}')",
        "verify": "wire_project(phase='verify')",
    }


def build_wiring_brief(
    project_root: Path,
    framework: str,
    detection: DetectionResult,
    retriever_entrypoint: Optional[str] = None,
) -> Dict[str, Any]:
    entrypoints = [
        {
            "file": e.file,
            "symbol": e.symbol,
            "line_hint": e.line_hint,
            "kind": e.kind,
        }
        for e in detection.entrypoints
    ]
    primary = detection.entrypoints[0] if detection.entrypoints else None
    expected_stages = ["my_retriever"]
    patches: List[Dict[str, Any]] = []
    guide = describe_integration(framework)

    if framework == "python" and primary:
        patches.append(
            {
                "file": primary.file,
                "action": "wrap_or_delegate",
                "description": f"Delegate retrieval to retobs/retriever.py or add @observe to {primary.symbol}",
                "snippet": guide.get("snippet", ""),
            }
        )
        patches.append(
            {
                "file": "retobs/retriever.py",
                "action": "implement_factory",
                "description": "Connect build_retriever() to your production retriever",
                "snippet": f"Factory entrypoint: {retriever_entrypoint or 'retriever.build_retriever'}",
            }
        )
    elif framework == "langchain" and primary:
        patches.append(
            {
                "file": primary.file,
                "action": "add_callback",
                "description": "Pass RetobsLangChainCallbackV2 in retriever.invoke callbacks",
                "snippet": guide.get("snippet", ""),
            }
        )
    elif framework == "llamaindex" and primary:
        patches.append(
            {
                "file": primary.file,
                "action": "add_callback",
                "description": "Attach RetobsLlamaIndexCallbackV2 to query engine CallbackManager",
                "snippet": guide.get("snippet", ""),
            }
        )
    elif framework == "fastapi" and primary:
        patches.append(
            {
                "file": primary.file,
                "action": "instrument_app",
                "description": "Call instrument_fastapi() and record stages in routes",
                "snippet": guide.get("snippet", ""),
            }
        )
    elif framework == "http" and detection.http_routes:
        route = detection.http_routes[0]
        patches.append(
            {
                "file": "retobs/config.yaml",
                "action": "configure_http_adapter",
                "description": "adapter.http stage already scaffolded; set url to your running service",
                "snippet": f"url: http://localhost:8000{route['path']}",
            }
        )
        expected_stages = ["my_service"]

    return {
        "entrypoints": entrypoints,
        "patches": patches,
        "expected_stages": expected_stages,
        "integration_snippet": guide.get("snippet", ""),
    }


def _write_sample_dataset(retobs_dir: Path, written: List[str]) -> None:
    for name, content in [
        ("queries.jsonl", SAMPLE_QUERIES),
        ("corpus.jsonl", SAMPLE_CORPUS),
        ("qrels.jsonl", SAMPLE_QRELS),
    ]:
        path = retobs_dir / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            written.append(str(path))


def _write_retos_md(project_root: Path, manifest: Dict[str, Any], commands: Dict[str, str]) -> Path:
    path = project_root / "RETOS.md"
    lines = [
        "# retobs — wired project",
        "",
        "retobs is set up in this repo. See `.retobs/manifest.yaml` for integration state.",
        "",
        "## Post-wiring commands (human)",
        "",
            f"- Evaluate: `{commands['evaluate']}`",
            f"- Dashboard: `{commands['serve']}`",
            f"- Verify: `{commands['verify_cli']}`",
        "",
        "## Agent prompts",
        "",
            '- "Run a smoke evaluation" → MCP `evaluate_file` on `retobs/config.yaml`',
        '- "Compare this run to the baseline" → MCP `compare` with explicit baseline/candidate IDs',
        '- "Verify tracing" → MCP `wire_project(phase=\\"verify\\")`',
        "",
        "## Replace sample eval data",
        "",
        "Swap `retobs/queries.jsonl`, `corpus.jsonl`, `qrels.jsonl` with your production eval set,",
        "or change `dataset.name` in `retobs/config.yaml` to a BEIR id (e.g. `beir/nfcorpus`).",
        "",
        f"Framework: **{manifest.get('framework')}** · Status: **{manifest.get('status')}**",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_manifest(project_root: Path, data: Dict[str, Any]) -> Path:
    manifest_dir = project_root / ".retobs"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / "manifest.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def load_manifest(project_root: str | Path) -> Optional[Dict[str, Any]]:
    path = Path(project_root).resolve() / ".retobs" / "manifest.yaml"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def plan_project(
    project_root: str | Path,
    framework: Optional[str] = None,
    retriever_entrypoint: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a read-only, minimal integration plan with explicit verification criteria."""
    root = Path(project_root).resolve()
    detection = detect_project(root, framework=framework)
    chosen = (framework or detection.framework).lower().strip()
    guide = describe_integration(chosen)
    if guide.get("error"):
        return {"status": "failed", **guide, "project_root": str(root), "files_written": []}
    brief = build_wiring_brief(
        root,
        chosen,
        detection,
        retriever_entrypoint=retriever_entrypoint,
    )
    scores = detection.framework_scores
    chosen_score = scores.get(chosen, 0)
    total_score = sum(max(score, 0) for score in scores.values())
    confidence = round(chosen_score / total_score, 3) if total_score else 0.0
    dependencies = []
    if guide.get("install_extra"):
        dependencies.append(f"retrieval-observatory[{guide['install_extra']}]")
    data_flow = {
        "storage": "local SQLite by default",
        "outbound": chosen == "http",
        "detail": (
            "Evaluation queries are sent to the configured HTTP endpoint."
            if chosen == "http"
            else "No retobs-managed outbound transport is required; traces remain in the configured local store."
        ),
    }
    return {
        "status": "planned",
        "project_root": str(root),
        "framework": chosen,
        "support": SUPPORT_LEVELS[chosen],
        "detection": {
            "confidence": confidence,
            "scores": scores,
            "entrypoints": brief["entrypoints"],
            "http_routes": detection.http_routes,
        },
        "proposed_patches": brief["patches"],
        "dependencies": dependencies,
        "credentials": guide.get("env_vars", []),
        "data_flow": data_flow,
        "expected_operators": brief["expected_stages"],
        "verification_criteria": [
            "At least one representative V2 trace is observed.",
            "Stable trace/run/query/pipeline/operator/document identities pass.",
            "Operator parents form an acyclic graph with an explicit final output.",
            "Wall-clock, critical-path, and operator-sum timing fields are valid.",
            "Candidate ranks, scores, origins, and non-source inputs are preserved.",
            "Required errors block readiness; warnings name limited capabilities.",
        ],
        "files_written": [],
        "next": "Review the proposed patch, then run wire_project(phase='apply') or apply it idiomatically.",
    }


def setup_project(
    project_root: str | Path,
    framework: Optional[str] = None,
    retriever_entrypoint: Optional[str] = None,
    experiment_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Scaffold retobs in an external project and return a wiring brief for the agent."""
    root = Path(project_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    detection = detect_project(root, framework=framework)
    fw = framework or detection.framework
    retobs_dir = root / "retobs"
    retobs_dir.mkdir(parents=True, exist_ok=True)

    exp_name = experiment_name or root.name or "my-rag"
    factory = retriever_entrypoint or "retriever.build_retriever"
    written: List[str] = []

    config_path = retobs_dir / "config.yaml"
    if not config_path.exists():
        config_path.write_text(bootstrap_config_yaml(exp_name, factory), encoding="utf-8")
        written.append(str(config_path))

    mcp_path = root / "retobs-mcp.yaml"
    if not mcp_path.exists():
        mcp_path.write_text(
            f"db_path: {DEFAULT_DB_PATH}\nmax_queries: 50\nbaseline_run_id: null\n",
            encoding="utf-8",
        )
        written.append(str(mcp_path))

    _write_sample_dataset(retobs_dir, written)

    if fw == "python":
        retriever_path = retobs_dir / "retriever.py"
        if not retriever_path.exists():
            retriever_path.write_text(RETRIEVER_STUB, encoding="utf-8")
            written.append(str(retriever_path))
        instrument_path = retobs_dir / "instrument.py"
        if not instrument_path.exists():
            instrument_path.write_text(INSTRUMENT_STUB, encoding="utf-8")
            written.append(str(instrument_path))

    wiring_brief = build_wiring_brief(root, fw, detection, retriever_entrypoint=factory)
    commands = post_wiring_commands(root, config_path)

    entrypoints_manifest = [
        {"file": e["file"], "symbol": e["symbol"]}
        for e in wiring_brief.get("entrypoints", [])[:3]
    ]
    manifest = {
        "retobs_version": _package_version(),
        "wired_at": datetime.now(timezone.utc).isoformat(),
        "framework": fw,
        "entrypoints": entrypoints_manifest,
        "config_path": str(config_path.relative_to(root)),
        "db_path": DEFAULT_DB_PATH,
        "expected_stages": wiring_brief.get("expected_stages", ["my_retriever"]),
        "dataset_mode": "sample",
        "status": "setup_complete",
    }
    manifest_path = _write_manifest(root, manifest)
    written.append(str(manifest_path))

    retos_path = _write_retos_md(root, manifest, commands)
    written.append(str(retos_path))

    cursor_rules = root / ".cursor" / "rules"
    cursor_rules.mkdir(parents=True, exist_ok=True)
    rule_path = cursor_rules / "retobs.mdc"
    if not rule_path.exists():
        rule_path.write_text(CURSOR_RULE, encoding="utf-8")
        written.append(str(rule_path))

    return {
        "status": "setup_complete",
        "project_root": str(root),
        "framework": fw,
        "framework_scores": detection.framework_scores,
        "files_written": written,
        "config_path": str(config_path),
        "mcp_config_path": str(mcp_path),
        "manifest_path": str(manifest_path),
        "wiring_brief": wiring_brief,
        "agent_instructions": "Apply wiring_brief patches to the listed files, then call wire_project(phase='verify').",
        "post_wiring_commands": commands,
        "integration_guide": describe_integration(fw),
    }


async def verify_project(
    project_root: str | Path,
    db_path: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify retobs install and project wiring after agent patches code."""
    root = Path(project_root).resolve()
    manifest = load_manifest(root) or {}
    effective_db = db_path or manifest.get("db_path") or DEFAULT_DB_PATH
    if not Path(effective_db).is_absolute():
        effective_db = str((root / effective_db).resolve())

    checks: List[Dict[str, Any]] = []

    def record(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": passed, "detail": detail})

    record("manifest_present", bool(manifest), str(root / ".retobs" / "manifest.yaml"))
    record("retrieval_observatory import", importlib.util.find_spec("retrieval_observatory") is not None)
    record("config_exists", (root / manifest.get("config_path", "retobs/config.yaml")).is_file())

    verify = await verify_integration(
        db_path=effective_db,
        run_id=run_id,
        expected_stages=manifest.get("expected_stages"),
    )

    all_checks_pass = all(c["passed"] for c in checks)
    integration_ok = verify.get("status") == "ready"
    ready = all_checks_pass and integration_ok

    if ready and manifest:
        manifest["status"] = "ready"
        _write_manifest(root, manifest)

    commands = post_wiring_commands(root, root / manifest.get("config_path", "retobs/config.yaml"))

    return {
        "status": "ready" if ready else verify.get("status", "needs_attention"),
        "checks": checks,
        "integration": verify,
        "instrumentation": verify.get("instrumentation"),
        "dashboard_url": verify.get("dashboard_url") or dashboard_base_url(),
        "commands": commands,
        "manifest": manifest,
        "agent_instructions": (
            "Wiring complete. Use post_wiring_commands for evaluate, serve, and trace workflows."
            if ready
            else "Fix failing checks and apply wiring_brief patches, then call wire_project(phase='verify') again."
        ),
    }


async def wire_project(
    project_root: str,
    framework: Optional[str] = None,
    retriever_entrypoint: Optional[str] = None,
    experiment_name: Optional[str] = None,
    phase: str = "setup",
    db_path: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Integration orchestration: read-only plan, compatibility apply/setup, or verify."""
    if phase == "plan":
        return plan_project(
            project_root,
            framework=framework,
            retriever_entrypoint=retriever_entrypoint,
        )
    if phase == "verify":
        return await verify_project(project_root, db_path=db_path, run_id=run_id)
    return setup_project(
        project_root,
        framework=framework,
        retriever_entrypoint=retriever_entrypoint,
        experiment_name=experiment_name,
    )
