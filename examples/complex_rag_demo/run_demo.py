r"""Complex RAG demo: a gated, multi-source retrieval pipeline fully instrumented
with retobs's trace-native operator DAG (RetrievalTraceV2).

The pipeline models a support/on-call knowledge-base search:

    GATE (intent) --> SOURCE (bm25) -----\
                  \--> SOURCE (dense) -----> FUSE (rrf) --> FILTER (cap)
                                                                  |
                                                                  v
                                            EXPAND (thread siblings, informational only)
                                                                  |
                                                                  v
                                            TRANSFORM (context prefix) --> RERANK --> BOOST (recency)

All 8 operator types in retobs's model (SOURCE, FUSE, EXPAND, FILTER,
TRANSFORM, RERANK, BOOST, GATE) appear in this trace, on a small custom
JSONL dataset (see corpus.jsonl / queries.jsonl / edges.jsonl in this
directory), so the dashboard's segment/operator attribution grid, operator
inspector, and counterfactual replay all have something real to show.

Run:
    python examples/complex_rag_demo/run_demo.py
    retobs serve --db .retobs/complex_rag_demo.db
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import retrieval_observatory as ro
from retrieval_observatory.corpus.graph import EdgeStore, load_graph_corpus
from retrieval_observatory.tracing.attribution import operator_marginal_contribution
from retrieval_observatory.tracing.model_v2 import Candidate, OperatorSpan

HERE = Path(__file__).parent
DB_PATH = ".retobs/complex_rag_demo.db"
RUN_ID = "complex-rag-demo"
PIPELINE_ID = "kb_search_v1"

INTENT_NAV_HINTS = ["how do i", "how to", "steps to", "rate limit", "authentication", "scale", "scaling"]


def load_jsonl(path: Path) -> list[dict]:
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def bm25_like_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
    """Lightweight lexical overlap score. Stand-in for retobs's real BM25Adapter
    (adapters/bm25_adapter.py), which is built for the YAML/SDK benchmark path;
    this keeps the demo dependency-free while still deterministic and EXACT-replayable.
    """
    if not doc_tokens:
        return 0.0
    doc_counts = Counter(doc_tokens)
    overlap = sum(doc_counts.get(t, 0) for t in set(query_tokens))
    return overlap / math.sqrt(len(doc_tokens))


def _trigrams(text: str) -> set[str]:
    joined = "".join(tokenize(text))
    return {joined[i : i + 3] for i in range(len(joined) - 2)}


def semantic_like_score(query_text: str, doc_text: str) -> float:
    """Character-trigram Jaccard similarity as a dependency-free "semantic" stand-in.
    Swap this for adapters/hf_biencoder_adapter.py or your own embedding call for
    real dense retrieval -- kept as NOT_REPLAYABLE/non-deterministic below to match
    retobs's honesty convention for real embedding models (tracing/lift.py mapping).
    """
    q, d = _trigrams(query_text), _trigrams(doc_text)
    if not q or not d:
        return 0.0
    return len(q & d) / len(q | d)


def classify_intent(query_text: str) -> str:
    q = query_text.lower()
    if any(hint in q for hint in INTENT_NAV_HINTS):
        return "navigational"
    return "informational"


def rrf_fuse(ranked_lists: list[tuple[str, list[str]]], k: int = 60):
    scores: dict[str, float] = {}
    contributions: dict[str, dict[str, float]] = {}
    for op_id, ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            contribution = 1.0 / (k + rank)
            scores[doc_id] = scores.get(doc_id, 0.0) + contribution
            contributions.setdefault(doc_id, {})[op_id] = contribution
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return ordered, contributions


def is_recent(timestamp_str: str, days: int = 120) -> bool:
    ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - ts).days <= days


async def run_pipeline(t, query: dict, corpus_by_id: dict, edge_store: EdgeStore) -> list[str]:
    query_text = query["text"]
    query_tokens = tokenize(query_text)

    # 1. GATE -- classify intent; the EXPAND operator below only fires for informational queries
    t0 = time.perf_counter()
    intent = classify_intent(query_text)
    gate_span = OperatorSpan(
        op_id="gate_intent", op_type="GATE", op_name="intent_gate",
        parent_ids=[], status="FIRED", deterministic=True, replay_policy="NOT_REPLAYABLE",
        latency_ms=(time.perf_counter() - t0) * 1000,
        gate_values={"intent": intent},
    )
    t.add_span(gate_span)

    # 2a. SOURCE -- lexical arm
    t0 = time.perf_counter()
    bm25_scores = {doc_id: bm25_like_score(query_tokens, tokenize(doc["text"])) for doc_id, doc in corpus_by_id.items()}
    bm25_ranked = [d for d, s in sorted(bm25_scores.items(), key=lambda kv: kv[1], reverse=True) if s > 0][:20]
    bm25_span = OperatorSpan(
        op_id="source_bm25", op_type="SOURCE", op_name="bm25",
        parent_ids=[gate_span.op_id], status="FIRED", deterministic=True, replay_policy="EXACT",
        latency_ms=(time.perf_counter() - t0) * 1000,
        outputs=[Candidate(doc_id=d, score=bm25_scores[d], rank=i + 1, origin_op_ids=["source_bm25"]) for i, d in enumerate(bm25_ranked)],
        params={"k": 20},
    )
    t.add_span(bm25_span)

    # 2b. SOURCE -- semantic arm
    t0 = time.perf_counter()
    dense_scores = {doc_id: semantic_like_score(query_text, doc["text"]) for doc_id, doc in corpus_by_id.items()}
    dense_ranked = [d for d, s in sorted(dense_scores.items(), key=lambda kv: kv[1], reverse=True) if s > 0][:20]
    dense_span = OperatorSpan(
        op_id="source_dense", op_type="SOURCE", op_name="dense",
        parent_ids=[gate_span.op_id], status="FIRED", deterministic=False, replay_policy="NOT_REPLAYABLE",
        latency_ms=(time.perf_counter() - t0) * 1000,
        outputs=[Candidate(doc_id=d, score=dense_scores[d], rank=i + 1, origin_op_ids=["source_dense"]) for i, d in enumerate(dense_ranked)],
        params={"k": 20},
    )
    t.add_span(dense_span)

    # 3. FUSE -- reciprocal rank fusion of both arms
    t0 = time.perf_counter()
    fused_ranked, contributions = rrf_fuse([("source_bm25", bm25_ranked), ("source_dense", dense_ranked)], k=60)
    fuse_outputs = [
        Candidate(doc_id=doc_id, score=score, rank=i + 1, origin_op_ids=sorted(contributions[doc_id]), score_components=contributions[doc_id], add_reason="fused")
        for i, (doc_id, score) in enumerate(fused_ranked)
    ]
    fuse_span = OperatorSpan(
        op_id="fuse_rrf", op_type="FUSE", op_name="rrf_fuse",
        parent_ids=[bm25_span.op_id, dense_span.op_id], status="FIRED", deterministic=True, replay_policy="EXACT",
        latency_ms=(time.perf_counter() - t0) * 1000,
        inputs=list(bm25_span.outputs) + list(dense_span.outputs), outputs=fuse_outputs, params={"k": 60},
    )
    t.add_span(fuse_span)

    # 4. FILTER -- cap the candidate pool
    t0 = time.perf_counter()
    cap = 8
    kept = fuse_outputs[:cap]
    for c in fuse_outputs[cap:]:
        c.drop_reason = "capacity_cap"
    filter_span = OperatorSpan(
        op_id="filter_cap", op_type="FILTER", op_name="cap_top_n",
        parent_ids=[fuse_span.op_id], status="FIRED", deterministic=True, replay_policy="EXACT",
        latency_ms=(time.perf_counter() - t0) * 1000,
        inputs=fuse_outputs, outputs=kept, params={"cap": cap},
    )
    t.add_span(filter_span)

    # 5. EXPAND -- pull in thread-sibling docs, but only for informational queries
    t0 = time.perf_counter()
    expanded = list(kept)
    fired = False
    if intent == "informational" and kept:
        siblings = await edge_store.neighbors(kept[0].doc_id, edge_type="thread_sibling")
        existing_ids = {c.doc_id for c in expanded}
        min_score = min((c.score for c in expanded), default=0.0)
        for edge in siblings:
            if edge.dst_doc_id not in existing_ids and edge.dst_doc_id in corpus_by_id:
                expanded.append(Candidate(doc_id=edge.dst_doc_id, score=min_score * 0.9, rank=0, origin_op_ids=["expand_thread"], add_reason="expanded"))
                existing_ids.add(edge.dst_doc_id)
                fired = True
    for i, c in enumerate(expanded):
        c.rank = i + 1
    expand_span = OperatorSpan(
        op_id="expand_thread", op_type="EXPAND", op_name="thread_expand",
        parent_ids=[filter_span.op_id], status="FIRED" if fired else "SKIPPED_BY_GATE",
        deterministic=True, replay_policy="EXACT",
        latency_ms=(time.perf_counter() - t0) * 1000,
        inputs=kept, outputs=expanded, params={"edge_type": "thread_sibling", "intent": intent},
    )
    t.add_span(expand_span)

    # 6. TRANSFORM -- context-prefix step; candidate set is unchanged, but the stage is a first-class span
    t0 = time.perf_counter()
    transform_span = OperatorSpan(
        op_id="transform_context", op_type="TRANSFORM", op_name="context_prefix",
        parent_ids=[expand_span.op_id], status="FIRED", deterministic=True, replay_policy="EXACT",
        latency_ms=(time.perf_counter() - t0) * 1000,
        inputs=expanded, outputs=list(expanded), params={"prefix": "kb_ticket_context"},
    )
    t.add_span(transform_span)

    # 7. RERANK -- blend the fused score with fresh lexical overlap (stand-in for a cross-encoder)
    t0 = time.perf_counter()
    blended_pairs = []
    for c in transform_span.outputs:
        doc = corpus_by_id.get(c.doc_id)
        lexical = bm25_like_score(query_tokens, tokenize(doc["text"])) if doc else 0.0
        blended_pairs.append((c, 0.6 * c.score + 0.4 * lexical))
    blended_pairs.sort(key=lambda pair: pair[1], reverse=True)
    rerank_outputs = [
        Candidate(doc_id=c.doc_id, score=score, rank=i + 1, origin_op_ids=c.origin_op_ids, score_components={**c.score_components, "pre_rerank": c.score}, add_reason=c.add_reason)
        for i, (c, score) in enumerate(blended_pairs)
    ]
    rerank_span = OperatorSpan(
        op_id="rerank_cross", op_type="RERANK", op_name="cross_rerank",
        parent_ids=[transform_span.op_id], status="FIRED", deterministic=False, replay_policy="OBSERVED_ABLATION",
        latency_ms=(time.perf_counter() - t0) * 1000,
        inputs=transform_span.outputs, outputs=rerank_outputs, params={},
    )
    t.add_span(rerank_span)

    # 8. BOOST -- recency boost; pre_boost is recorded so without_operator() can replay this exactly
    t0 = time.perf_counter()
    boosted = []
    for c in rerank_outputs:
        doc = corpus_by_id.get(c.doc_id)
        recent = bool(doc and is_recent(doc["timestamp"]))
        boosted_score = c.score * 1.15 if recent else c.score
        boosted.append(Candidate(doc_id=c.doc_id, score=boosted_score, rank=0, origin_op_ids=c.origin_op_ids, score_components={**c.score_components, "pre_boost": c.score}, add_reason=c.add_reason))
    boosted.sort(key=lambda c: c.score, reverse=True)
    for i, c in enumerate(boosted):
        c.rank = i + 1
    boost_span = OperatorSpan(
        op_id="boost_recency", op_type="BOOST", op_name="recency_boost",
        parent_ids=[rerank_span.op_id], status="FIRED", deterministic=True, replay_policy="EXACT",
        latency_ms=(time.perf_counter() - t0) * 1000,
        inputs=rerank_outputs, outputs=boosted, params={"window_days": 120, "multiplier": 1.15},
    )
    t.add_span(boost_span)

    return [c.doc_id for c in boosted]


async def main() -> None:
    corpus = {d["id"]: d for d in load_jsonl(HERE / "corpus.jsonl")}
    queries = load_jsonl(HERE / "queries.jsonl")

    # TraceRecorderV2 stamps every trace's run_id from `service=`, so the run we
    # register (RUN_ID) and the run we later query traces for must both use it.
    recorder = ro.init(service=RUN_ID, db=DB_PATH)
    store = recorder.store
    await store.init_db()
    await store.save_run(RUN_ID, experiment_name="Complex RAG KB search demo", config_json=json.dumps({"pipeline_id": PIPELINE_ID}))

    edge_store = EdgeStore(store)
    n_edges = await load_graph_corpus(HERE / "edges.jsonl", edge_store)
    print(f"Loaded {n_edges} thread-sibling edges")

    for query in queries:
        async with recorder.trace(query["text"], PIPELINE_ID, query_id=query["query_id"]) as t:
            await run_pipeline(t, query, corpus, edge_store)

    # Persist qrels so the dashboard's /operator-attribution and /miss-attribution
    # endpoints can recover ground truth (store.get_qrels) after this process exits.
    qrels = {q["query_id"]: {doc_id: 1 for doc_id in q["relevant_doc_ids"]} for q in queries}
    await store.save_qrels(RUN_ID, qrels)

    await store.finish_run(RUN_ID)
    print(f"\nWrote {len(queries)} traces to {DB_PATH} under run_id={RUN_ID!r}")

    # Offline attribution preview -- the same engine the dashboard's /operator-attribution
    # endpoint calls, run here directly against the traces we just wrote.
    traces = await store.get_traces_v2(RUN_ID)
    op_ids = ["source_bm25", "source_dense", "fuse_rrf", "filter_cap", "expand_thread", "rerank_cross", "boost_recency"]
    print("\nOperator marginal contribution (recall@10):")
    for op_id in op_ids:
        for result in operator_marginal_contribution(traces, op_id=op_id, qrels=qrels, metric="recall", k=10):
            print(
                f"  {op_id:16s} segment={result.segment:24s} delta={result.delta} "
                f"n_pairs={result.n_pairs} replay={result.replay_policy} status={result.result_status}"
            )

    print(f"\nNow run:\n  retobs serve --db {DB_PATH}\nand open run '{RUN_ID}' to see the Operator Attribution Grid and Operator Inspector panels.")


if __name__ == "__main__":
    asyncio.run(main())
