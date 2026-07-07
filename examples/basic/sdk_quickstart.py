"""Code-first quickstart — benchmark a retrieval pipeline in pure Python (no YAML).

Run:  python examples/basic/sdk_quickstart.py
"""
import retrieval_observatory as ro

# A tiny corpus + labeled queries. In practice these come from your own data /
# vector DB; see `ro.generate_testset(corpus)` to synthesize labels with zero ground truth.
CORPUS = {
    "d1": "The mitochondrion is the powerhouse of the cell.",
    "d2": "Photosynthesis converts light energy into chemical energy.",
    "d3": "Cellular respiration produces ATP in mitochondria.",
    "d4": "The stock market closed higher on Friday.",
}
QUERIES = [
    {"query_id": "q1", "text": "what makes ATP in cells", "relevant_doc_ids": ["d1", "d3"]},
    {"query_id": "q2", "text": "how plants make energy", "relevant_doc_ids": ["d2"]},
]


# --- your existing retrieval pipeline, wrapped as-is -------------------------
@ro.retriever
def my_retriever(query: str) -> list[str]:
    # naive keyword overlap; swap in your real vector DB / hybrid search
    ranked = sorted(
        CORPUS,
        key=lambda d: sum(w in CORPUS[d].lower() for w in query.lower().split()),
        reverse=True,
    )
    return ranked


def my_reranker(query: str, docs: list) -> list[str]:
    # trivial reranker that prefers shorter documents; returns doc ids
    return [d.id for d in sorted(docs, key=lambda d: len(d.text))]


if __name__ == "__main__":
    # Single-stage: simplest entry point.
    report = ro.benchmark(my_retriever, queries=QUERIES, corpus=CORPUS, k=5)
    report.show()

    # Multi-stage: this is where retobs earns its keep — per-stage contribution
    # and candidate_miss vs reranker_drop diagnostics.
    report2 = ro.benchmark([my_retriever, my_reranker], queries=QUERIES, corpus=CORPUS, k=5)
    report2.show()

    print(f"\nRun IDs: {report.run_id}, {report2.run_id}")
    print("Open the dashboard with:  report.serve()  (or `retobs serve --db .retobs/results.db`)")
