"""Walkthrough of the code-first features (roadmap Phases 1-3).

Run:  python examples/basic/demo_phases.py
Then: retobs serve --db .retobs/demo_phases.db   # explore in the dashboard (Phase 0)
"""
import retrieval_observatory as ro
from retrieval_observatory import Document, StageSnapshot

DB = ".retobs/demo_phases.db"

CORPUS = {
    "d1": "mitochondria produce ATP via cellular respiration",
    "d2": "photosynthesis converts light into chemical energy",
    "d3": "ATP is the energy currency of the cell",
    "d4": "the federal reserve raised interest rates",
}
QUERIES = [
    {"query_id": "q1", "text": "what produces ATP", "relevant_doc_ids": ["d1", "d3"]},
    {"query_id": "q2", "text": "how plants get energy", "relevant_doc_ids": ["d2"]},
]


def retrieve(q: str):
    return sorted(CORPUS, key=lambda d: sum(w in CORPUS[d] for w in q.split()), reverse=True)


def rerank(q: str, docs: list):
    return [d.id for d in sorted(docs, key=lambda d: len(d.text))]


print("\n### PHASE 1 — code-first SDK")
single = ro.benchmark(retrieve, queries=QUERIES, corpus=CORPUS, k=5, db_path=DB, name="search")
multi = ro.benchmark([retrieve, rerank], queries=QUERIES, corpus=CORPUS, k=5, db_path=DB, name="search_rr")
print("single-stage run:", single.run_id)
print("multi-stage run :", multi.run_id, "->", [k for k in multi.metrics if "recall@5" in k])

print("\n### PHASE 2 — per-stage snapshots from a monolithic pipeline")
def monolith(q: str):
    return [
        StageSnapshot(0, "candidates", [Document(id="d1", text="", score=3, rank=1),
                                        Document(id="d3", text="", score=2, rank=2)], 5.0),
        StageSnapshot(1, "rerank", [Document(id="d4", text="", score=1, rank=1)], 2.0),  # drops gold
    ]
mono = ro.benchmark(monolith, queries=[QUERIES[0]], corpus=CORPUS, k=5, db_path=DB, name="monolith")
s0 = next(v["mean"] for k, v in mono.metrics.items() if "stage0|recall@5" in k)
s1 = next(v["mean"] for k, v in mono.metrics.items() if "stage1|recall@5" in k)
print(f"candidate-stage recall={s0}  rerank-stage recall={s1}  -> reranker_drop is now visible")

print("\n### PHASE 3 — synthesize a labeled test set from a corpus (no API key)")
year_corpus = {f"report{y}": {"text": f"annual revenue report {y} quarterly growth earnings"}
               for y in (2019, 2020, 2021, 2022)}
testset = ro.generate_testset(year_corpus, n_per_type=2)
synth_q, synth_qrels = testset.load()
print(f"generated {len(synth_q)} synthetic queries + {len(synth_qrels)} qrels")
synth_run = ro.benchmark(lambda q: list(testset.corpus), dataset=testset, k=5, db_path=DB, name="synthetic")
print("benchmarked synthetic set as run:", synth_run.run_id)

print(f"\nDone. Explore everything:  retobs serve --db {DB}")
