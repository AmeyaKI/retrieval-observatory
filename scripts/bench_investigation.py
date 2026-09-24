#!/usr/bin/env python3
"""Investigation performance harness for the plan §11 operating envelope.

    python scripts/bench_investigation.py --sizes tiny,small,medium --out-dir DIR \
        [--json PATH] [--time-cap-s 900] [--reps 30] [--seed N] [--allow-large]

Per size, a seeded synthetic hybrid run is generated and persisted query by query through the
same store methods the runner uses (``save_run``, ``save_run_manifest`` built by the runner's
``build_run_manifest`` from a graph ``ExperimentConfig`` and completed with
``judgment_records``/``judgment_digest``/``evaluation``, ``save_run_queries``, ``save_traces``,
``finish_run``) into ``DIR/<size>.db``. The DAG per query is

    dense ─[dedupe@dense]─ rerank@dense ──┐
    lexical ─ filter@lexical ─ rerank@lexical ─┴─ fuse ─[expand]─ rerank@fused ─[boost ─ dedupe]─ select

(bracketed operators only in the 12-operator shape). Every span records its actual
``input_groups`` and ``outputs`` (built with ``build_candidate_transition``, as the golden
fixture does) with ``input_capture``/``output_capture = "recorded"``; candidates carry IDs only,
no document text. Each query has 3-5 relevant documents in the judgments whose roles rotate
through: delivered, lost at the lexical filter, retrieved by dense but weakly reranked, and never
retrieved.

Measured phases, reported separately:

* storage      generation+persist seconds, DB bytes, bytes/query, bytes/occurrence (occurrence =
               one candidate entry in a span's ``outputs``); raw-trace bytes vs projection bytes.
* after        ``build_projection`` seconds via the same ``resolve_scope`` + ``build_projection``
               calls ``retobs storage index`` makes; then API latency through an in-process
               ``TestClient(create_app(registry=DbRegistry([db]), enable_uploads=False))``: a first
               call (cold for the two first pages, which are the app's first requests) plus warm
               p50/p95 over ``--reps`` for the first queries page, documents page, a mid-run
               documents cursor page, two outcome-filtered pages (priority 0 and 3), one query
               detail and one document detail; response bytes; ``limit=500`` behaviour; one cold call of a broad
               filter (``final_membership=excluded``).
* before       what the same answers cost from raw traces without the projection: (a) per query,
               ``list_traces`` for one query + ``project_trace_journeys`` (the service's own
               unprojected fallback, p50/p95 over ``--reps``); (b) whole run, load every trace and
               project + summarize them all once (what a run-level table would cost).
* capture      ``@observe(..., capture=CaptureSpec(...))`` on an 8-operator pipeline inside an
               in-memory ``start_trace``/``finish_trace`` versus the same undecorated functions, for a
               fast pipeline (trivial list ops) and a representative one (~1 ms CPU per operator);
               per-call µs, % overhead and serialized trace bytes. Persistence is excluded here (it
               is the storage phase).

Peak RSS is ``ru_maxrss`` after each phase: a monotonic process-wide peak, so later (larger)
sizes include earlier ones. The time cap is checked between phases and inside repetition loops;
the uninterruptible projection build and whole-run raw scan are skipped up front when their
estimate (raw per-query p50 x queries, a lower bound) exceeds the remaining cap. A size that stops
records ``"aborted": "<phase>"`` plus ``"abort_detail"`` and the report continues. The JSON is
rewritten after every phase. Nothing outside ``--out-dir`` (and ``--json``) is written.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import math
import platform
import random
import resource
import sqlite3
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from retrieval_observatory.config.schema import (
    DatasetConfig,
    ExperimentConfig,
    ExperimentMeta,
    GraphNodeConfig,
    GraphPipelineConfig,
    MetricsConfig,
)
from retrieval_observatory.datasets.judgments import EvaluationSpec, JudgmentSet
from retrieval_observatory.evidence.journeys import project_trace_journeys, summarize_journeys
from retrieval_observatory.evidence.service import InvestigationRequest, build_projection, resolve_scope
from retrieval_observatory.runner.manifest import build_run_manifest
from retrieval_observatory.store.base import TraceQuery
from retrieval_observatory.store.sqlite import SQLiteStore
from retrieval_observatory.tracing.candidates import build_candidate_transition, to_candidates
from retrieval_observatory.tracing.model import Candidate, OperatorSpan, RetrievalTrace
from retrieval_observatory.types import Query

REPO = Path(__file__).resolve().parents[1]
RUN_ID = "bench-run"
PIPELINE_ID = "bench-hybrid"
NAMESPACE = "kb"
K = 10
CORPUS_DOCS = 50_000
CHUNKS_PER_DOC = 3
RRF_K = 60
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
ROLES = ("delivered", "lost_at_filter", "weak_rerank", "never_retrieved")


@dataclass(frozen=True)
class Size:
    queries: int
    operators: int
    candidates: int


SIZES = {
    "tiny": Size(10, 8, 20),
    "small": Size(100, 8, 100),
    "medium": Size(1000, 12, 100),
    "large": Size(10_000, 12, 100),
}


class Aborted(Exception):
    pass


# ---------------------------------------------------------------------------
# Synthetic generator
# ---------------------------------------------------------------------------

Items = list[dict[str, Any]]
Reasons = dict[str, str]


def _chunk(doc: int, chunk: int) -> dict[str, Any]:
    local = f"d{doc}-c{chunk}"
    return {
        "doc_id": local,
        "candidate_id": f"{NAMESPACE}:{local}",
        "logical_chunk_id": local,
        "document_id": f"d{doc}",
        "metadata": {"namespace": NAMESPACE},
    }


def _item(candidate: Candidate, score: float, rank: int, **extra: Any) -> dict[str, Any]:
    return {
        "doc_id": candidate.doc_id,
        "candidate_id": candidate.candidate_id,
        "logical_chunk_id": candidate.logical_chunk_id,
        "document_id": candidate.document_id,
        "metadata": {"namespace": NAMESPACE},
        "score": round(score, 6),
        "rank": rank,
        **extra,
    }


def _ranked(scored: Sequence[tuple[Candidate, float]], keep: int, cutoff_reason: str) -> tuple[Items, Reasons]:
    ordered = sorted(scored, key=lambda pair: -pair[1])  # stable: ties keep input order
    items = [_item(candidate, score, rank) for rank, (candidate, score) in enumerate(ordered[:keep], start=1)]
    return items, {candidate.candidate_id: cutoff_reason for candidate, _ in ordered[keep:]}


def generate_query(index: int, size: Size, seed: int) -> tuple[Query, RetrievalTrace, list[dict[str, Any]]]:
    """One query's trace and judgment records; deterministic in (index, size, seed)."""
    rng = random.Random(f"{seed}:{index}")
    c = size.candidates
    twelve = size.operators == 12
    query_id = f"q{index:05d}"
    docs = rng.sample(range(CORPUS_DOCS), 2 * c + 10)
    relevant = docs[: rng.randint(3, 5)]
    role = {doc: ROLES[(i + index) % len(ROLES)] for i, doc in enumerate(relevant)}
    others = docs[len(relevant):]
    chunk_of = {doc: rng.randrange(CHUNKS_PER_DOC) for doc in docs}

    def planted(roles: tuple[str, ...]) -> list[int]:
        return [doc for doc in relevant if role[doc] in roles]

    dense_docs = others[: c - len(planted(("delivered", "weak_rerank")))]
    for doc in planted(("delivered",)):
        dense_docs.insert(rng.randrange(min(5, len(dense_docs) + 1)), doc)
    for doc in planted(("weak_rerank",)):
        dense_docs.insert(rng.randrange(len(dense_docs) + 1), doc)
    dense_items = [_chunk(doc, chunk_of[doc]) for doc in dense_docs]

    overlap = rng.sample(others[: len(dense_docs)], min(len(dense_docs), (3 * c) // 10))
    lexical_chunks = [(doc, chunk_of[doc] if rng.random() < 0.5 else (chunk_of[doc] + 1) % CHUNKS_PER_DOC) for doc in overlap]
    lexical_chunks += [(doc, chunk_of[doc]) for doc in others[c:]][: c - len(lexical_chunks) - len(planted(("lost_at_filter",)))]
    rng.shuffle(lexical_chunks)
    for doc in planted(("lost_at_filter",)):
        lexical_chunks.insert(rng.randrange(min(10, len(lexical_chunks) + 1)), (doc, chunk_of[doc]))
    lexical_items = [_chunk(doc, chunk) for doc, chunk in lexical_chunks]

    for rank, item in enumerate(dense_items, start=1):
        item.update(score=round(1 - rank / (2 * c), 6), rank=rank, score_type="cosine")
    for rank, item in enumerate(lexical_items, start=1):
        item.update(score=round(20 - rank * 0.1, 6), rank=rank, score_type="bm25")

    rerank_table: dict[str, float] = {}

    def rerank_score(candidate: Candidate) -> float:
        cid = str(candidate.candidate_id)
        if cid not in rerank_table:
            doc_role = role.get(int(str(candidate.document_id)[1:]))
            rerank_table[cid] = (
                rng.uniform(0.95, 0.99) if doc_role == "delivered"
                else rng.uniform(0.2, 0.5) if doc_role == "weak_rerank"
                else rng.uniform(0.0, 0.9)
            )
        return rerank_table[cid]

    spans: list[OperatorSpan] = []

    def links(op_id: str, parents: tuple[str, ...]) -> dict[str, Any]:
        return {
            "invocation_id": f"{query_id}:{op_id}",
            "parent_invocation_ids": tuple(f"{query_id}:{parent}" for parent in parents),
            "parent_linkage": "recorded",
        }

    def source(op_id: str, items: Items) -> list[Candidate]:
        span = OperatorSpan(
            op_id, "SOURCE", op_id, (), "FIRED", round(rng.uniform(2, 30), 3),
            outputs=to_candidates(items, op_id), branch_id=op_id, **links(op_id, ()),
        )
        spans.append(span)
        return list(span.outputs)

    def record(
        op_id: str,
        op_type: str,
        groups: Mapping[str, Sequence[Candidate]],
        operator: Callable[[], tuple[Items, Reasons]],
        *,
        operator_id: str | None = None,
        branch: str | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> list[Candidate]:
        items, reasons = operator()
        transition = build_candidate_transition(
            input_groups=groups, output_items=items, op_id=op_id, op_type=op_type, decision_reasons=reasons
        )
        parents = tuple(groups)
        spans.append(OperatorSpan(
            op_id, op_type, operator_id or op_id, parents, "FIRED", round(rng.uniform(0.5, 40), 3),
            input_groups=transition.input_groups, outputs=transition.outputs, deterministic=True,
            params=dict(params or {}), branch_id=branch, operator_id=operator_id, **links(op_id, parents),
        ))
        return list(transition.outputs)

    def drop(inputs: Sequence[Candidate], decide: Callable[[Candidate], str | None]) -> tuple[Items, Reasons]:
        kept: Items = []
        reasons: Reasons = {}
        for candidate in inputs:
            reason = decide(candidate)
            if reason is None:
                kept.append(_item(candidate, candidate.score, len(kept) + 1))
            else:
                reasons[str(candidate.candidate_id)] = reason
        return kept, reasons

    def lexical_filter(candidate: Candidate) -> str | None:
        if role.get(int(str(candidate.document_id)[1:])) == "lost_at_filter":
            return "min_score"
        return rng.choice(("min_score", "stale_year")) if rng.random() < 0.15 else None

    def rerank(inputs: Sequence[Candidate], keep: int) -> tuple[Items, Reasons]:
        return _ranked([(candidate, rerank_score(candidate)) for candidate in inputs], keep, "rerank_cutoff")

    dense = source("dense", dense_items)
    lexical = source("lexical", lexical_items)
    dense_parent = "dense"
    if twelve:
        dense = record(
            "dedupe@dense", "FILTER", {"dense": dense}, branch="dense", params={"rule": "near_duplicate"},
            operator=lambda: drop(dense, lambda cand: "near_duplicate" if role.get(int(str(cand.document_id)[1:])) is None and rng.random() < 0.05 else None),
        )
        dense_parent = "dedupe@dense"
    filtered = record(
        "filter@lexical", "FILTER", {"lexical": lexical}, branch="lexical", params={"min_score": 0.3, "min_year": 2023},
        operator=lambda: drop(lexical, lexical_filter),
    )
    rerank_params = {"model": "bench-crossencoder", "keep_fraction": 0.9}
    reranked_dense = record(
        "rerank@dense", "RERANK", {dense_parent: dense}, operator_id="rerank", branch="dense", params=rerank_params,
        operator=lambda: rerank(dense, (9 * len(dense)) // 10),
    )
    reranked_lexical = record(
        "rerank@lexical", "RERANK", {"filter@lexical": filtered}, operator_id="rerank", branch="lexical", params=rerank_params,
        operator=lambda: rerank(filtered, (9 * len(filtered)) // 10),
    )
    fuse_keep = c - (c // 10 if twelve else 0)
    fuse_groups = {"rerank@dense": reranked_dense, "rerank@lexical": reranked_lexical}

    def fuse() -> tuple[Items, Reasons]:
        fused: dict[str, list[Any]] = {}
        for candidates in fuse_groups.values():
            for candidate in candidates:
                entry = fused.setdefault(str(candidate.candidate_id), [candidate, 0.0])
                entry[1] += 1.0 / (RRF_K + candidate.rank)
        return _ranked([(candidate, score) for candidate, score in fused.values()], fuse_keep, "fusion_cutoff")

    stream = record("fuse", "FUSE", fuse_groups, params={"method": "rrf", "k": RRF_K, "keep": fuse_keep}, operator=fuse)
    parent = "fuse"
    if twelve:
        fused_out = stream

        def expand() -> tuple[Items, Reasons]:
            items = [_item(candidate, candidate.score, candidate.rank) for candidate in fused_out]
            present = {str(candidate.candidate_id) for candidate in fused_out}
            for candidate in fused_out[: c // 10]:
                doc, chunk = str(candidate.logical_chunk_id)[1:].split("-c")
                sibling = _chunk(int(doc), (int(chunk) + 1) % CHUNKS_PER_DOC)
                if sibling["candidate_id"] not in present:
                    present.add(sibling["candidate_id"])
                    items.append({
                        **sibling, "score": round(candidate.score * 0.9, 6), "rank": len(items) + 1,
                        "parent_candidate_ids": (candidate.candidate_id,), "add_reason": "expanded",
                    })
            return items, {}

        stream = record("expand", "EXPAND", {"fuse": fused_out}, params={"siblings": 1}, operator=expand)
        parent = "expand"
    rerank_keep = max(K + 5, c // 2)
    before_final = stream
    stream = record(
        "rerank@fused", "RERANK", {parent: before_final}, operator_id="rerank", params={"model": "bench-crossencoder", "keep": rerank_keep},
        operator=lambda: rerank(before_final, rerank_keep),
    )
    parent = "rerank@fused"
    select_budget = min(20, rerank_keep)
    if twelve:
        reranked = stream
        stream = record(
            "boost", "BOOST", {parent: reranked}, params={"recency_boost": 0.05},
            operator=lambda: _ranked([(cand, cand.score + (0.05 if int(str(cand.document_id)[1:]) % 2 == 0 else 0.0)) for cand in reranked], len(reranked), "boost_cutoff"),
        )
        boosted = stream

        def one_per_document() -> tuple[Items, Reasons]:
            seen: set[str] = set()

            def decide(candidate: Candidate) -> str | None:
                if candidate.document_id in seen:
                    return "duplicate_document"
                seen.add(str(candidate.document_id))
                return None

            return drop(boosted, decide)

        stream = record("dedupe", "TRANSFORM", {"boost": boosted}, params={"one_chunk_per_document": True}, operator=one_per_document)
        parent = "dedupe"
    select_inputs = stream

    def select() -> tuple[Items, Reasons]:
        seen: set[str] = set()

        def decide(candidate: Candidate) -> str | None:
            if candidate.document_id in seen:
                return "duplicate_document"
            if len(seen) >= select_budget:
                return "context_budget"
            seen.add(str(candidate.document_id))
            return None

        return drop(select_inputs, decide)

    record("select", "TRANSFORM", {parent: select_inputs}, params={"budget": select_budget}, operator=select)
    assert len(spans) == size.operators, (len(spans), size.operators)

    query = Query(text=f"synthetic query {index}", k=select_budget, query_id=query_id)
    trace = RetrievalTrace(
        trace_id=f"trace-{query_id}", service_id="bench", run_id=RUN_ID, query_id=query_id, query_text=query.text,
        pipeline_id=PIPELINE_ID, spans=tuple(spans), final_op_ids=("select",), timestamp=BASE_TIME + timedelta(seconds=index),
        dataset_id="bench", corpus_version="bench@1",
    )
    judged = [(doc, rng.choice((1, 2))) for doc in relevant]
    judged += [(doc, 0) for doc in rng.sample(dense_docs[:10], 2) if doc not in role]  # judged non-relevant
    records = [
        {"query_id": query_id, "namespace": NAMESPACE, "entity_id": f"d{doc}", "unit": "document", "grade": grade,
         "source_kind": "gold", "source_version": "bench-1"}
        for doc, grade in judged
    ]
    return query, trace, records


def experiment_config(size: Size) -> ExperimentConfig:
    """The bench DAG as the runner sees a graph-configured run (``graphs``, not ``pipelines``)."""
    twelve = size.operators == 12
    nodes: list[dict[str, Any]] = [
        {"id": "dense", "type": "adapter.bench_dense"},
        {"id": "lexical", "type": "adapter.bench_lexical"},
        *([{"id": "dedupe@dense", "inputs": ["dense"]}] if twelve else []),
        {"id": "filter@lexical", "inputs": ["lexical"]},
        {"id": "rerank@dense", "inputs": ["dedupe@dense" if twelve else "dense"]},
        {"id": "rerank@lexical", "inputs": ["filter@lexical"]},
        {"id": "fuse", "op": "fuse", "inputs": ["rerank@dense", "rerank@lexical"]},
        *([{"id": "expand", "inputs": ["fuse"]}] if twelve else []),
        {"id": "rerank@fused", "inputs": ["expand" if twelve else "fuse"]},
        *([{"id": "boost", "inputs": ["rerank@fused"]}, {"id": "dedupe", "inputs": ["boost"]}] if twelve else []),
        {"id": "select", "inputs": ["dedupe" if twelve else "rerank@fused"]},
    ]
    return ExperimentConfig(
        experiment=ExperimentMeta(name="bench-investigation"),
        dataset=DatasetConfig(name="bench"),
        graphs=[GraphPipelineConfig(id=PIPELINE_ID, nodes=[GraphNodeConfig(**node) for node in nodes])],
        metrics=MetricsConfig(recall_at_k=[K]),
    )


async def generate_run(db_path: Path, size: Size, seed: int) -> dict[str, int]:
    """Persist one run query by query through the runner's store methods; returns counts.

    The manifest is built and completed the way ``runner.execute`` does it: ``build_run_manifest``
    before the queries, then counts, judgments and the evaluation spec once they are known.
    """
    store = SQLiteStore(str(db_path))
    await store.init_db()
    config = experiment_config(size)
    await store.save_run(RUN_ID, config.experiment.name, config.model_dump_json())
    await store.save_run_manifest(RUN_ID, build_run_manifest(config, {"name": "bench", "seed": seed}, seed=seed))
    records: list[dict[str, Any]] = []
    queries: list[Query] = []
    counts = {"traces": 0, "spans": 0, "output_occurrences": 0, "input_occurrences": 0}
    for index in range(size.queries):
        query, trace, query_records = generate_query(index, size, seed)
        await store.save_traces([trace])
        queries.append(query)
        records.extend(query_records)
        counts["traces"] += 1
        counts["spans"] += len(trace.spans)
        counts["output_occurrences"] += sum(len(span.outputs) for span in trace.spans)
        counts["input_occurrences"] += sum(len(group) for span in trace.spans for group in span.input_groups.values())
    await store.save_run_queries(RUN_ID, queries, "bench")
    judgments = JudgmentSet.from_records(records)
    manifest = await store.get_run_manifest(RUN_ID) or {}
    manifest["counts"] = {"attempted": size.queries, "completed": size.queries, "labeled": size.queries, "metric_eligible": size.queries}
    manifest["judgment_records"] = judgments.to_records()
    manifest["judgment_digest"] = judgments.digest()
    manifest["evaluation"] = EvaluationSpec(unit="document", k=K).to_dict()
    await store.save_run_manifest(RUN_ID, manifest)
    await store.finish_run(RUN_ID)
    counts["judgments"] = len(records)
    return counts


def request(**values: Any) -> InvestigationRequest:
    return InvestigationRequest.from_mapping({"run_id": RUN_ID, "pipeline_id": PIPELINE_ID, **values})


async def index_run(db_path: Path) -> tuple[float, float, dict]:
    """The `retobs storage index` path: resolve_scope then build_projection (both timed)."""
    store = SQLiteStore(str(db_path))
    await store.init_db()
    t0 = time.perf_counter()
    resolved = await resolve_scope(store, request())
    t1 = time.perf_counter()
    meta = await build_projection(
        store, resolved.run_id, resolved.pipeline_id, resolved.spec, judgments=resolved.judgments, chunk_map=resolved.chunk_map
    )
    return t1 - t0, time.perf_counter() - t1, meta


# ---------------------------------------------------------------------------
# Measurement helpers
# ---------------------------------------------------------------------------


def percentile(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def ms_stats(samples_s: Sequence[float]) -> dict[str, Any]:
    ms = [s * 1000 for s in samples_s]
    return {"n": len(ms), "p50_ms": _r(percentile(ms, 50)), "p95_ms": _r(percentile(ms, 95)), "max_ms": _r(max(ms) if ms else None)}


def _r(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def file_bytes(db_path: Path) -> int:
    return sum(p.stat().st_size for p in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-journal")) if p.exists())


def sql_scalar(db_path: Path, sql: str) -> Any:
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        return conn.execute(sql).fetchone()[0]


# ---------------------------------------------------------------------------
# "Before": answers computed from raw traces without the projection
# ---------------------------------------------------------------------------


async def before_per_query(db_path: Path, reps: int, n_queries: int, check: Callable[[str], None]) -> dict[str, Any]:
    store = SQLiteStore(str(db_path))
    resolved = await resolve_scope(store, request())
    samples: list[float] = []
    step = max(1, n_queries // max(1, reps))
    for rep in range(reps):
        check("before_per_query")
        query_id = f"q{(rep * step + n_queries // 2) % n_queries:05d}"
        t0 = time.perf_counter()
        traces = await store.list_traces(TraceQuery(run_id=RUN_ID, pipeline_id=PIPELINE_ID, query_id=query_id))
        rows = [row for trace in traces for row in project_trace_journeys(trace, resolved.judgments, resolved.spec)]
        samples.append(time.perf_counter() - t0)
        assert rows
    return {**ms_stats(samples), "method": "list_traces(query_id) + project_trace_journeys; scope resolution excluded"}


async def before_whole_run(db_path: Path) -> dict[str, Any]:
    store = SQLiteStore(str(db_path))
    resolved = await resolve_scope(store, request())
    t0 = time.perf_counter()
    traces = await store.list_traces(TraceQuery(run_id=RUN_ID, pipeline_id=PIPELINE_ID))
    t1 = time.perf_counter()
    rows = [row for trace in traces for row in project_trace_journeys(trace, resolved.judgments, resolved.spec)]
    t2 = time.perf_counter()
    summarize_journeys(rows)
    t3 = time.perf_counter()
    return {"load_s": _r(t1 - t0), "project_s": _r(t2 - t1), "summarize_s": _r(t3 - t2), "total_s": _r(t3 - t0),
            "traces": len(traces), "rows": len(rows), "method": "list_traces(run) + project all + summarize_journeys, once"}


# ---------------------------------------------------------------------------
# "After": API latency through the dashboard app
# ---------------------------------------------------------------------------


def api_latency(db_path: Path, reps: int, n_queries: int, check: Callable[[str], None]) -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from retrieval_observatory.dashboard.api import create_app
    from retrieval_observatory.dashboard.registry import DbRegistry

    registry = DbRegistry([str(db_path)])
    client = TestClient(create_app(registry=registry, enable_uploads=False))
    base = f"/dbs/{registry.default_db_id}/investigation/runs/{RUN_ID}"
    scope = {"pipeline_id": PIPELINE_ID}

    def get(path: str, **params: Any):
        t0 = time.perf_counter()
        response = client.get(base + path, params={**scope, **params})
        elapsed = time.perf_counter() - t0
        return elapsed, response, response.json() if response.headers.get("content-type", "").startswith("application/json") else None

    # The first two requests of a fresh app are the cold ones (the OS page cache is not purged).
    first = {"queries_first_page": get("/queries"), "documents_first_page": get("/documents")}

    # Untimed discovery: a mid-run documents cursor and a detail target.
    pages = math.ceil((first["documents_first_page"][2]["total"] or 0) / 50)
    cursor, page_no = None, 0
    while page_no < pages // 2:
        body = (get("/documents", cursor=cursor) if cursor else get("/documents"))[2]
        cursor, page_no = body["next_cursor"], page_no + 1
    mid_query = f"q{n_queries // 2:05d}"
    detail = get(f"/queries/{mid_query}")[2]
    judged = next(row for row in detail["rows"] if row["judgment"] == "relevant" and row["observed"])
    entity = f"{judged['namespace']}:{judged['entity_id']}"

    endpoints: dict[str, tuple[str, dict[str, Any]]] = {
        "queries_first_page": ("/queries", {}),
        "documents_first_page": ("/documents", {}),
        "documents_mid_cursor_page": ("/documents", {"cursor": cursor} if cursor else {}),
        # relevant_excluded sorts first (priority 0): the best case for the priority-index walk;
        # retained_below_cutoff (priority 3) sits behind most of the scope.
        "queries_outcome_relevant_excluded": ("/queries", {"outcome": "relevant_excluded"}),
        "queries_outcome_retained_below_cutoff": ("/queries", {"outcome": "retained_below_cutoff"}),
        "query_detail": (f"/queries/{mid_query}", {}),
        "document_detail": (f"/documents/{entity}", {}),
    }
    results: dict[str, Any] = {
        "mid_cursor_page_index": page_no if cursor else None, "document_detail_entity": entity,
        "first_call_note": "first pages: the app's first two requests (cold); others: first timed call after untimed discovery",
    }
    for name, (path, params) in endpoints.items():
        check(f"api:{name}")
        elapsed, response, body = first.get(name) or get(path, **params)
        warm: list[float] = []
        for _ in range(reps):
            check(f"api:{name}")
            warm.append(get(path, **params)[0])
        results[name] = {
            "status": response.status_code, "bytes": len(response.content), "rows": len(body["rows"]) if body else None,
            "total": body.get("total") if body else None, "first_call_ms": _r(elapsed * 1000), **{f"warm_{k}": v for k, v in ms_stats(warm).items()},
        }
    check("api:filtered_broad_once")
    elapsed, response, body = get("/queries", final_membership="excluded")
    results["queries_filtered_broad_once"] = {
        "status": response.status_code, "bytes": len(response.content), "total": body.get("total") if body else None,
        "first_call_ms": _r(elapsed * 1000), "filter": "final_membership=excluded",
    }
    _, response, body = get("/documents", limit=500)
    rows = len(body["rows"]) if body and "rows" in body else None
    results["limit_500"] = {
        "status": response.status_code, "rows": rows, "total": body.get("total") if body else None,
        "behavior": "rejected" if response.status_code >= 400 else "clamped_to_200" if rows == min(200, body["total"]) else "unclamped",
    }
    return results


# ---------------------------------------------------------------------------
# Capture overhead (@observe versus plain functions)
# ---------------------------------------------------------------------------


def capture_overhead(iterations: int = 200, candidates: int = 100) -> dict[str, Any]:
    from retrieval_observatory.sdk.observe import ObserveContext, finish_trace, observe, start_trace
    from retrieval_observatory.store.sqlite import json_default
    from retrieval_observatory.tracing.capture import CaptureSpec

    def work(n: int) -> int:
        acc = 0
        for i in range(n):
            acc = (acc * 31 + i) & 0xFFFFFFFF
        return acc

    loops = 10_000
    t0 = time.perf_counter()
    work(loops)
    loops = max(1000, int(loops * 0.001 / (time.perf_counter() - t0)))  # ~1 ms per operator call

    def build(spin: int) -> dict[str, Callable[..., Any]]:
        def src(prefix: str) -> Callable[[str], list[dict]]:
            def retrieve(query: str) -> list[dict]:
                work(spin)
                return [{"doc_id": f"{prefix}{i}", "score": 1 - i / candidates, "rank": i + 1} for i in range(candidates)]
            return retrieve

        def rescore(docs: list[dict], keep: int) -> list[dict]:
            work(spin)
            ordered = sorted(docs, key=lambda d: d["doc_id"])[:keep]
            return [{**d, "rank": r} for r, d in enumerate(ordered, start=1)]

        def filt(docs: list[dict]) -> list[dict]:
            work(spin)
            return [d for i, d in enumerate(docs) if i % 7]

        def fuse(dense: list[dict], lexical: list[dict]) -> list[dict]:
            work(spin)
            merged = {d["doc_id"]: d for d in (*dense, *lexical)}
            return [{**d, "rank": r} for r, d in enumerate(list(merged.values())[:candidates], start=1)]

        return {
            "dense": src("a"), "lexical": src("b"), "filter@lexical": filt,
            "rerank@dense": lambda docs: rescore(docs, (9 * len(docs)) // 10),
            "rerank@lexical": lambda docs: rescore(docs, (9 * len(docs)) // 10),
            "fuse": fuse, "rerank@fused": lambda docs: rescore(docs, candidates // 2),
            "select": lambda docs: rescore(docs, 20),
        }

    def instrument(ops: dict[str, Callable[..., Any]]) -> dict[str, Callable[..., Any]]:
        single = {"filter@lexical": "lexical", "rerank@dense": "dense", "rerank@lexical": "filter@lexical",
                  "rerank@fused": "fuse", "select": "rerank@fused"}
        out: dict[str, Callable[..., Any]] = {}
        for op_id, fn in ops.items():
            if op_id in ("dense", "lexical"):
                spec = CaptureSpec(outputs=lambda result: result)
                out[op_id] = observe("SOURCE", op_id=op_id, capture=spec)(fn)
            elif op_id == "fuse":
                spec = CaptureSpec(inputs=lambda b: {"rerank@dense": b.args[0], "rerank@lexical": b.args[1]}, outputs=lambda result: result)
                out[op_id] = observe("FUSE", op_id=op_id, parent_ids=("rerank@dense", "rerank@lexical"), capture=spec)(fn)
            else:
                parent = single[op_id]
                spec = CaptureSpec(inputs=lambda b, parent=parent: {parent: b.args[0]}, outputs=lambda result: result)
                op_type = "FILTER" if op_id.startswith("filter") else "TRANSFORM" if op_id == "select" else "RERANK"
                out[op_id] = observe(op_type, op_id=op_id, parent_ids=(parent,), capture=spec)(fn)
        return out

    def pipeline(ops: dict[str, Callable[..., Any]], query: str) -> list[dict]:
        dense, lexical = ops["dense"](query), ops["lexical"](query)
        fused = ops["fuse"](ops["rerank@dense"](dense), ops["rerank@lexical"](ops["filter@lexical"](lexical)))
        return ops["select"](ops["rerank@fused"](fused))

    results: dict[str, Any] = {"operators": 8, "candidates_per_source": candidates, "iterations": iterations,
                               "representative_work_loops": loops, "persistence": "excluded (in-memory start_trace/finish_trace)"}
    for label, spin in (("fast", 0), ("representative", loops)):
        plain = build(spin)
        observed = instrument(plain)
        ctx = ObserveContext(None, "q", "query", "capture-bench", "bench")
        plain_s: list[float] = []
        observed_s: list[float] = []
        for i in range(iterations + 10):  # first 10 are warm-up
            t0 = time.perf_counter()
            pipeline(plain, "query")
            t1 = time.perf_counter()
            start_trace(ctx)
            pipeline(observed, "query")
            trace = finish_trace()
            t2 = time.perf_counter()
            if i >= 10:
                plain_s.append(t1 - t0)
                observed_s.append(t2 - t1)
        trace_bytes = len(json.dumps(trace.to_dict(), sort_keys=True, default=json_default))
        p50_plain, p50_obs = percentile(plain_s, 50), percentile(observed_s, 50)
        results[label] = {
            "plain_p50_us": _r(p50_plain * 1e6, 1), "observed_p50_us": _r(p50_obs * 1e6, 1),
            "overhead_p50_us": _r((p50_obs - p50_plain) * 1e6, 1), "overhead_pct": _r((p50_obs / p50_plain - 1) * 100, 1),
            "plain_mean_us": _r(sum(plain_s) / len(plain_s) * 1e6, 1), "observed_mean_us": _r(sum(observed_s) / len(observed_s) * 1e6, 1),
            "trace_json_bytes_per_call": trace_bytes, "spans_per_trace": len(trace.spans),
        }
    return results


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def environment() -> dict[str, Any]:
    def run(*cmd: str) -> str | None:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=REPO).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    status = run("git", "status", "--porcelain")
    return {
        "platform": platform.platform(), "machine": platform.machine(), "python": sys.version.split()[0],
        "cpu": run("sysctl", "-n", "machdep.cpu.brand_string") if sys.platform == "darwin" else platform.processor(),
        "git_commit": run("git", "rev-parse", "HEAD"), "git_dirty": None if status is None else bool(status),
        "sqlite": sqlite3.sqlite_version, "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def run_size(name: str, size: Size, args: argparse.Namespace, out_dir: Path, save: Callable[[], None], result: dict[str, Any]) -> None:
    db_path = out_dir / f"{name}.db"
    for path in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm"), Path(f"{db_path}-journal")):
        path.unlink(missing_ok=True)
    started = time.perf_counter()
    result.update(shape=asdict(size), db_path=str(db_path), phases_completed=[], aborted=None, peak_rss_bytes={})

    def check(phase: str, estimate_s: float = 0.0) -> None:
        """Abort when the cap is spent, or when a phase's estimated cost cannot fit in what remains."""
        remaining = args.time_cap_s - (time.perf_counter() - started)
        if remaining <= 0 or estimate_s > remaining:
            detail = f"estimated {estimate_s:.0f} s > {remaining:.0f} s remaining" if estimate_s > 0 else "time cap reached"
            raise Aborted(phase, detail)

    def done(phase: str) -> None:
        result["phases_completed"].append(phase)
        result["peak_rss_bytes"][phase] = peak_rss_bytes()
        result["elapsed_s"] = _r(time.perf_counter() - started)
        gc.collect()
        save()

    try:
        check("generate_persist")
        t0 = time.perf_counter()
        counts = asyncio.run(generate_run(db_path, size, args.seed))
        seconds = time.perf_counter() - t0
        raw = file_bytes(db_path)
        result["storage"] = {
            "generate_persist_s": _r(seconds), **counts, "db_bytes_raw": raw,
            "bytes_per_query_raw": round(raw / size.queries), "bytes_per_output_occurrence_raw": _r(raw / counts["output_occurrences"], 1),
            "trace_json_bytes": sql_scalar(db_path, "SELECT SUM(LENGTH(trace_json)) FROM traces"),
            "manifest_bytes": sql_scalar(db_path, f"SELECT LENGTH(manifest_json) FROM run_manifests WHERE run_id = '{RUN_ID}'"),
        }
        done("generate_persist")

        # The raw per-query cost runs first: a projection build and a whole-run raw scan each cost at
        # least (per-query p50 x queries), so that product guards both single-call phases below,
        # which cannot be interrupted once started.
        check("before_per_query")
        result["before"] = {"per_query": asyncio.run(before_per_query(db_path, args.reps, size.queries, check))}
        done("before_per_query")
        estimate = result["before"]["per_query"]["p50_ms"] / 1000 * size.queries
        result["estimated_whole_run_projection_s"] = _r(estimate)

        check("projection_build", estimate)
        resolve_s, build_s, meta = asyncio.run(index_run(db_path))
        total = file_bytes(db_path)
        result["after_projection_build"] = {
            "resolve_scope_s": _r(resolve_s), "build_projection_s": _r(build_s), "pair_rows": meta["row_count"],
            "summary_rows": sql_scalar(db_path, "SELECT COUNT(*) FROM investigation_summaries"),
            "db_bytes_total": total, "projection_bytes": total - raw,
            "bytes_per_query_total": round(total / size.queries), "bytes_per_output_occurrence_total": _r(total / counts["output_occurrences"], 1),
            "run_summary_payload_bytes": sql_scalar(db_path, "SELECT LENGTH(payload_json) FROM investigation_summaries WHERE kind = 'run'"),
        }
        done("projection_build")

        check("before_whole_run", estimate)
        result["before"]["whole_run"] = asyncio.run(before_whole_run(db_path))
        done("before_whole_run")

        check("api")
        result["after_api"] = api_latency(db_path, args.reps, size.queries, check)
        done("api")
    except Aborted as abort:
        result["aborted"], result["abort_detail"] = abort.args
        result["elapsed_s"] = _r(time.perf_counter() - started)
        save()


def _fmt(value: Any) -> str:
    return "-" if value is None else f"{value:,}" if isinstance(value, int) else str(value)


def print_report(report: dict[str, Any]) -> None:
    print(f"\nenvironment: {report['environment']['cpu']} | python {report['environment']['python']} | sqlite {report['environment']['sqlite']} | commit {str(report['environment']['git_commit'])[:12]}")
    for name, res in report["sizes"].items():
        shape = res["shape"]
        print(f"\n== {name}: {shape['queries']} queries x {shape['operators']} operators x {shape['candidates']} candidates"
              f"  (elapsed {res.get('elapsed_s')} s{', ABORTED at ' + res['aborted'] + ': ' + res['abort_detail'] if res.get('aborted') else ''})")
        st, pr = res.get("storage", {}), res.get("after_projection_build", {})
        print("-- storage")
        for label, value in (
            ("generate+persist s", st.get("generate_persist_s")), ("output occurrences", st.get("output_occurrences")),
            ("input occurrences", st.get("input_occurrences")), ("DB bytes (raw traces)", st.get("db_bytes_raw")),
            ("bytes/query (raw)", st.get("bytes_per_query_raw")), ("bytes/occurrence (raw)", st.get("bytes_per_output_occurrence_raw")),
            ("DB bytes (with projection)", pr.get("db_bytes_total")), ("bytes/query (total)", pr.get("bytes_per_query_total")),
            ("bytes/occurrence (total)", pr.get("bytes_per_output_occurrence_total")), ("manifest bytes", st.get("manifest_bytes")),
            ("run summary payload bytes", pr.get("run_summary_payload_bytes")),
        ):
            print(f"   {label:<34} {_fmt(value)}")
        print("-- offline projection (after: one-time build)")
        for label, value in (("resolve_scope s", pr.get("resolve_scope_s")), ("build_projection s", pr.get("build_projection_s")),
                             ("pair rows", pr.get("pair_rows")), ("summary rows", pr.get("summary_rows"))):
            print(f"   {label:<34} {_fmt(value)}")
        before = res.get("before", {})
        pq, wr = before.get("per_query", {}), before.get("whole_run", {})
        print("-- before (raw traces, no projection)")
        print(f"   {'per-query load+project p50/p95 ms':<34} {_fmt(pq.get('p50_ms'))} / {_fmt(pq.get('p95_ms'))}  (n={_fmt(pq.get('n'))})")
        print(f"   {'whole-run load/project/total s':<34} {_fmt(wr.get('load_s'))} / {_fmt(wr.get('project_s'))} / {_fmt(wr.get('total_s'))}")
        api = res.get("after_api", {})
        print("-- after (API via TestClient)                 first ms   warm p50   warm p95    bytes   rows")
        for key in ("queries_first_page", "documents_first_page", "documents_mid_cursor_page", "queries_outcome_relevant_excluded",
                    "queries_outcome_retained_below_cutoff", "query_detail", "document_detail", "queries_filtered_broad_once"):
            row = api.get(key)
            if row:
                print(f"   {key:<41} {_fmt(row.get('first_call_ms')):>8} {_fmt(row.get('warm_p50_ms')):>10} {_fmt(row.get('warm_p95_ms')):>10}"
                      f" {_fmt(row.get('bytes')):>8} {_fmt(row.get('rows')):>6}")
        if "limit_500" in api:
            print(f"   limit=500 -> {api['limit_500']['behavior']} (status {api['limit_500']['status']}, rows {api['limit_500']['rows']})")
        rss = res.get("peak_rss_bytes") or {}
        if rss:
            print(f"   peak RSS after last phase: {max(rss.values()) / 2**20:,.1f} MiB (monotonic process peak)")
    cap = report.get("capture_overhead")
    if cap:
        print(f"\n== capture overhead (8 operators, {cap['candidates_per_source']} candidates/source, {cap['iterations']} iterations; {cap['persistence']})")
        print("   pipeline         plain p50 us  observed p50 us  overhead us  overhead %  trace bytes")
        for label in ("fast", "representative"):
            row = cap[label]
            print(f"   {label:<16} {row['plain_p50_us']:>12} {row['observed_p50_us']:>16} {row['overhead_p50_us']:>12} {row['overhead_pct']:>11} {row['trace_json_bytes_per_call']:>12,}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", default="tiny", help=f"comma-separated subset of {', '.join(SIZES)}")
    parser.add_argument("--out-dir", required=True, type=Path, help="directory for the generated <size>.db files")
    parser.add_argument("--json", type=Path, default=None, help="JSON report path (default: OUT_DIR/bench_investigation.json)")
    parser.add_argument("--time-cap-s", type=float, default=900.0, help="per-size wall-clock cap, checked between phases and repetitions")
    parser.add_argument("--reps", type=int, default=30, help="warm repetitions per timed call")
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--allow-large", action="store_true", help="permit the 10,000-query 'large' size")
    args = parser.parse_args(argv)

    names = [name.strip() for name in args.sizes.split(",") if name.strip()]
    unknown = [name for name in names if name not in SIZES]
    if unknown:
        parser.error(f"unknown size(s) {unknown}; choose from {list(SIZES)}")
    if "large" in names and not args.allow_large:
        parser.error("'large' (10,000 queries) is a scale test; pass --allow-large to run it")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.json or args.out_dir / "bench_investigation.json"
    report: dict[str, Any] = {
        "environment": environment(),
        "config": {"sizes": names, "seed": args.seed, "reps": args.reps, "time_cap_s": args.time_cap_s, "k": K},
        "sizes": {},
    }

    def save() -> None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, indent=2, sort_keys=True))

    for name in names:
        print(f"[bench] {name}: {SIZES[name]}", flush=True)
        report["sizes"][name] = {}
        run_size(name, SIZES[name], args, args.out_dir, save, report["sizes"][name])
    print("[bench] capture overhead", flush=True)
    report["capture_overhead"] = capture_overhead()
    save()
    print_report(report)
    print(f"\nJSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
