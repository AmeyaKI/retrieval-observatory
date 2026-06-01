#!/usr/bin/env python3
"""Generate corpus and queries for the dashboard demo benchmark."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent

TOPICS = [
    ("bm25", "BM25 sparse retrieval ranks documents using term frequency and inverse document frequency."),
    ("dense", "Dense retrieval encodes queries and documents as neural embeddings for semantic search."),
    ("hybrid", "Hybrid retrieval combines sparse BM25 scores with dense vector similarity using fusion."),
    ("rerank", "Cross-encoder rerankers rescore candidate documents for improved precision at the top."),
    ("rag", "Retrieval-augmented generation retrieves context before the language model generates an answer."),
    ("ndcg", "NDCG at ten measures ranking quality with graded relevance in the top results."),
    ("recall", "Recall at K reports the fraction of relevant documents found in the top K hits."),
    ("latency", "Pipeline latency includes retrieval time plus reranking and network overhead."),
    ("fusion", "Reciprocal rank fusion merges ranked lists from multiple retrievers without score calibration."),
    ("chunk", "Document chunking splits long passages into smaller units for embedding and retrieval."),
    ("embed", "Embedding models map text into vector space for approximate nearest neighbor search."),
    ("eval", "Information retrieval evaluation uses labeled qrels to score recall, MRR, and NDCG."),
    ("filter", "Metadata filters restrict retrieval to a subset of documents before ranking."),
    ("cache", "Result caching avoids recomputing expensive reranker scores across benchmark reruns."),
    ("stage", "Multi-stage pipelines chain a retriever with one or more reranking or fusion stages."),
]

CORPUS_EXTRA = [
    "Vector databases like FAISS and pgvector store embeddings for fast similarity search.",
    "Query expansion adds synonyms or pseudo-relevant terms to improve sparse retrieval recall.",
    "Hard negatives in contrastive training improve dense retriever discrimination.",
    "Mean average precision summarizes ranking quality across many queries.",
    "Mean reciprocal rank focuses on the rank of the first relevant document.",
    "Production RAG systems often use a wide first stage and a narrow final stage.",
    "Latency budgets force tradeoffs between quality gains and reranker cost.",
    "Failure analysis labels candidate misses, reranker drops, and lexical mismatches.",
    "Difficulty bucketing groups queries by cross-pipeline recall variance.",
    "Classifier calibration checks whether predicted difficulty matches observed recall.",
    "Stage attribution compares prefix pipelines to measure incremental reranker value.",
    "Pareto frontiers highlight pipelines that are not dominated on quality and latency.",
    "Segment breakdown plots metrics by number of relevant documents per query.",
    "HTTP adapters let benchmarks call live retrieval microservices over REST.",
    "Observatory dashboards visualize recall curves, funnels, and tradeoff scatter plots.",
]

QUERIES = [
    ("What is BM25 sparse retrieval?", ["bm25_0", "bm25_1"], "easy"),
    ("How does dense embedding retrieval work?", ["dense_0", "dense_1"], "easy"),
    ("Explain hybrid sparse and dense retrieval.", ["hybrid_0", "hybrid_1", "fusion_0"], "medium"),
    ("What does a cross-encoder reranker do?", ["rerank_0", "rerank_1"], "easy"),
    ("How does retrieval-augmented generation work?", ["rag_0", "rag_1"], "easy"),
    ("Define NDCG at ten for ranking evaluation.", ["ndcg_0", "ndcg_1"], "easy"),
    ("What is recall at K in IR benchmarks?", ["recall_0", "recall_1"], "easy"),
    ("Why does pipeline latency matter in production?", ["latency_0", "latency_1"], "medium"),
    ("Describe reciprocal rank fusion.", ["fusion_0", "fusion_1", "hybrid_0"], "medium"),
    ("Why chunk documents for RAG?", ["chunk_0", "chunk_1"], "easy"),
    ("How are text embeddings used in search?", ["embed_0", "embed_1", "dense_0"], "medium"),
    ("How do you evaluate a retrieval system?", ["eval_0", "eval_1"], "easy"),
    ("What are metadata filters in retrieval?", ["filter_0", "filter_1"], "medium"),
    ("Why cache benchmark retrieval results?", ["cache_0", "cache_1"], "easy"),
    ("What is a multi-stage retrieval pipeline?", ["stage_0", "stage_1", "rag_0"], "medium"),
    ("Compare BM25 and dense retrievers.", ["bm25_0", "dense_0", "hybrid_0"], "hard"),
    ("When should you add a reranker stage?", ["rerank_0", "stage_0", "latency_0"], "hard"),
    ("How does hybrid fusion improve recall?", ["hybrid_0", "fusion_0", "bm25_0"], "hard"),
    ("What metrics matter for RAG retrieval quality?", ["ndcg_0", "recall_0", "eval_0"], "medium"),
    ("Explain mean reciprocal rank.", ["eval_0", "extra_6"], "medium"),
    ("What is mean average precision?", ["eval_0", "extra_5"], "medium"),
    ("How do vector databases support RAG?", ["embed_0", "extra_0"], "medium"),
    ("What is query expansion?", ["bm25_0", "extra_1"], "hard"),
    ("Why use hard negatives in training?", ["dense_0", "extra_2"], "hard"),
    ("How do latency budgets affect rerankers?", ["latency_0", "extra_6", "rerank_0"], "hard"),
    ("What failure labels appear in diagnostics?", ["eval_0", "extra_7"], "medium"),
    ("How is query difficulty bucketed?", ["eval_0", "extra_8"], "medium"),
    ("What is classifier calibration in retrieval eval?", ["eval_0", "extra_9"], "medium"),
    ("What is stage attribution analysis?", ["stage_0", "extra_10"], "medium"),
    ("How do Pareto frontiers compare pipelines?", ["latency_0", "extra_11"], "hard"),
    ("Segment metrics by number of relevant docs.", ["eval_0", "extra_12"], "medium"),
    ("Benchmark a live HTTP retrieval service.", ["extra_13", "eval_0"], "medium"),
    ("Visualize recall curves and latency tradeoffs.", ["extra_14", "eval_0"], "easy"),
    ("Combine BM25 with two reranking stages.", ["bm25_0", "rerank_0", "stage_0"], "hard"),
    ("Does the second reranker pay for itself?", ["rerank_0", "stage_0", "latency_0"], "hard"),
    ("Find documents about FAISS vector search.", ["extra_0", "embed_0"], "easy"),
    ("Improve precision without hurting recall too much.", ["rerank_0", "recall_0", "ndcg_0"], "hard"),
    ("Measure end-to-end pipeline latency percentiles.", ["latency_0", "extra_6"], "medium"),
    ("Use observatory dashboards for pipeline comparison.", ["extra_14", "eval_0"], "easy"),
    ("Production RAG wide retrieval narrow rerank pattern.", ["stage_0", "extra_6", "rag_0"], "medium"),
]


def main() -> None:
    corpus_lines = []
    doc_idx = 0
    for slug, text in TOPICS:
        for i in range(2):
            doc_id = f"{slug}_{i}"
            corpus_lines.append({"id": doc_id, "text": text, "metadata": {"topic": slug}})
            doc_idx += 1
    for i, text in enumerate(CORPUS_EXTRA):
        corpus_lines.append({"id": f"extra_{i}", "text": text, "metadata": {"topic": "extra"}})

    query_lines = []
    for i, (text, rel_ids, _hint) in enumerate(QUERIES, start=1):
        qid = f"q{i:02d}"
        grades = {doc_id: 2 if j == 0 else 1 for j, doc_id in enumerate(rel_ids)}
        query_lines.append(
            {
                "query_id": qid,
                "text": text,
                "relevant_doc_ids": grades,
                "metadata": {"n_relevant": len(rel_ids), "seed_difficulty": _hint},
            }
        )

    (OUT / "corpus.jsonl").write_text("\n".join(json.dumps(row) for row in corpus_lines) + "\n")
    (OUT / "queries.jsonl").write_text("\n".join(json.dumps(row) for row in query_lines) + "\n")
    print(f"Wrote {len(corpus_lines)} docs and {len(query_lines)} queries to {OUT}")


if __name__ == "__main__":
    main()
