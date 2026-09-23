"""A multi-route project verifies against the scenarios its manifest declares: the lexical route
never fires ``dense`` and that is not a failure, an unobserved scenario is named precisely, and the
instrumented entrypoint returns exactly what the plain one returns (an oracle that does not depend
on the manifest)."""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path

from retrieval_observatory.integrations.manifest import write_manifest
from retrieval_observatory.integrations.model import IntegrationManifest, OperatorMapping, VerificationScenario
from retrieval_observatory.integrations.verify import verify_project
from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore

HYBRID_QUERY = "hybrid question"
LEXICAL_QUERY = "lexical question"

APP = '''
CORPUS = {{"d1": "hybrid dense lexical", "d2": "lexical sparse", "d3": "dense vectors", "d4": "question answering"}}


def intent_gate(query):
    return "hybrid" if "hybrid" in query else "lexical_only"


{bm25}
def bm25(query, route):
    terms = set(query.split())
    hits = [{{"id": doc_id, "score": float(len(terms & set(text.split())))}} for doc_id, text in CORPUS.items()]
    return [hit for hit in sorted(hits, key=lambda hit: (-hit["score"], hit["id"])) if hit["score"] > 0]


{dense}
def dense(query, route):
    return [{{"id": "d3", "score": 0.9}}, {{"id": "d1", "score": 0.8}}]


{rrf}
def rrf(*lanes):
    scores = {{}}
    for lane in lanes:
        for rank, hit in enumerate(lane, start=1):
            scores[hit["id"]] = scores.get(hit["id"], 0.0) + 1.0 / (60 + rank)
    return [{{"id": doc_id, "score": score}} for doc_id, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]


{rerank}
def rerank(candidates):
    return sorted(candidates, key=lambda hit: (-len(CORPUS[hit["id"]]), hit["id"]))[:3]


{retrieve}
def retrieve(query):
{gate}
    lanes = [bm25(query, route)]
    if route == "hybrid":
        lanes.append(dense(query, route))
    return rerank(rrf(*lanes))
'''

PLAIN = {"bm25": "", "dense": "", "rrf": "", "rerank": "", "retrieve": "", "gate": "    route = intent_gate(query)"}


def _instrumented(db: str) -> dict[str, str]:
    return {
        "bm25": '@observe("SOURCE", op_id="bm25")',
        "dense": '@observe("SOURCE", op_id="dense")',
        "rrf": (
            '@observe("FUSE", op_id="rrf", parent_ids=("bm25", "dense"), '
            'capture=CaptureSpec(inputs=lambda bound: dict(zip(("bm25", "dense"), bound.arguments["lanes"]))))'
        ),
        "rerank": '@observe("RERANK", op_id="rerank", parent_ids=("rrf",))',
        "retrieve": f'@trace_scope("route-svc", "route-pipe", db_path={db!r})',
        "gate": (
            '    with observe_gate("intent_gate", True, op_id="gate") as gate:\n'
            "        route = intent_gate(query)\n"
            '        gate.gate_values["selected_route"] = route'
        ),
    }


def _write_app(directory: Path, fields: dict[str, str], *, imports: str = "") -> Path:
    directory.mkdir(parents=True)
    path = directory / "app.py"
    path.write_text(imports + APP.format(**fields), encoding="utf-8")
    return path


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def _manifest() -> IntegrationManifest:
    return IntegrationManifest(
        2, "plan-routes", "route-svc", "route-pipe",
        (
            OperatorMapping("gate", "GATE", "intent_gate", "instrumented/app.py"),
            OperatorMapping("bm25", "SOURCE", "bm25", "instrumented/app.py"),
            OperatorMapping("dense", "SOURCE", "dense", "instrumented/app.py"),
            OperatorMapping("rrf", "FUSE", "rrf", "instrumented/app.py", ("bm25", "dense")),
            OperatorMapping("rerank", "RERANK", "rerank", "instrumented/app.py", ("rrf",)),
        ),
        {"doc_id": "id"},
        (
            VerificationScenario("hybrid", HYBRID_QUERY, ("gate", "bm25", "dense", "rrf", "rerank")),
            VerificationScenario("lexical_only", LEXICAL_QUERY, ("gate", "bm25", "rrf", "rerank"), route="lexical_only"),
        ),
        judgments={"qrels": "data/qrels.jsonl"},
    )


def _write_qrels(root: Path) -> None:
    path = root / "data" / "qrels.jsonl"
    path.parent.mkdir(parents=True)
    rows = [
        {"query_id": hashlib.sha256(HYBRID_QUERY.encode("utf-8")).hexdigest()[:16], "relevant_doc_ids": ["d1", "d3"]},
        {"query_id": hashlib.sha256(LEXICAL_QUERY.encode("utf-8")).hexdigest()[:16], "relevant_doc_ids": ["d2"]},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


async def _verify(root: Path, db: str):
    store = SQLiteStore(db_path=db)
    await store.init_db()
    result = await verify_project(root, store)
    traces = await store.list_traces(TraceQuery(service_id="route-svc", pipeline_id="route-pipe"))
    return result, traces


def _all_failures(result) -> list[dict]:
    return [failure for capability in result.capabilities.values() for failure in capability["failures"]]


def test_declared_routes_are_verified_across_scenarios(tmp_path: Path) -> None:
    root = tmp_path / "project"
    db = str(root / ".retobs" / "results.db")
    plain = _load("route_plain", _write_app(root / "plain", PLAIN))
    instrumented = _load(
        "route_instrumented",
        _write_app(
            root / "instrumented",
            _instrumented(db),
            imports=(
                "from retrieval_observatory.sdk.observe import observe, observe_gate, trace_scope\n"
                "from retrieval_observatory.tracing.capture import CaptureSpec\n"
            ),
        ),
    )
    write_manifest(root, _manifest())
    _write_qrels(root)

    # The oracle: instrumentation changes nothing the application returns, on either route.
    assert instrumented.retrieve(HYBRID_QUERY) == plain.retrieve(HYBRID_QUERY) == [
        {"id": "d1", "score": 1 / 61 + 1 / 62}, {"id": "d4", "score": 1 / 62}, {"id": "d3", "score": 1 / 61},
    ]

    partial, traces = asyncio.run(_verify(root, db))
    assert len(traces) == 1
    assert partial.status == "partial", partial.errors
    coverage = partial.capabilities["declared_route_coverage"]
    assert coverage["status"] == "partial"
    assert coverage["evidence"]["unobserved"] == ["lexical_only"]
    assert coverage["evidence"]["observed_routes"] == ["hybrid"]
    assert "1 of 2 declared scenarios" in coverage["scope"]
    assert [failure["code"] for failure in coverage["failures"]] == ["scenario_unobserved"]
    assert LEXICAL_QUERY in coverage["failures"][0]["detail"]
    for name in ("topology_observed", "actual_input_output_capture", "candidate_identity", "query_identity", "final_output_capture", "judgment_mapping"):
        assert partial.capabilities[name]["status"] == "ready", (name, partial.capabilities[name]["failures"])

    assert instrumented.retrieve(LEXICAL_QUERY) == plain.retrieve(LEXICAL_QUERY)
    assert instrumented.retrieve(HYBRID_QUERY) == plain.retrieve(HYBRID_QUERY)

    ready, traces = asyncio.run(_verify(root, db))
    assert ready.status == "ready", _all_failures(ready)
    assert {name: capability["status"] for name, capability in ready.capabilities.items()} == {name: "ready" for name in ready.capabilities}
    assert ready.capabilities["declared_route_coverage"]["evidence"]["observed_routes"] == ["hybrid", "lexical_only"]
    assert ready.capabilities["cross_run_entity_alignment"]["evidence"]["repeated_queries"] == 1
    assert set(ready.observed_operator_ids) == {"gate", "bm25", "dense", "rrf", "rerank"}

    lexical = next(trace for trace in traces if trace.query_text == LEXICAL_QUERY)
    assert [span.op_id for span in lexical.spans] == ["gate", "bm25", "rrf", "rerank"]
    assert lexical.span("gate").gate_values == {"selected_route": "lexical_only"}
    assert lexical.span("rrf").input_capture == "recorded" and set(lexical.span("rrf").input_groups) == {"bm25"}
    assert not any("dense" in failure["detail"] for failure in _all_failures(ready))
