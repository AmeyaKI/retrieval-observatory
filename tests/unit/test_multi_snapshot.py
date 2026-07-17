import retrieval_observatory as ro
from retrieval_observatory.types import Document, StageSnapshot

CORPUS = {"d1": "alpha", "d2": "beta", "d3": "gamma", "d4": "delta"}
QUERIES = [{"query_id": "q1", "text": "alpha", "relevant_doc_ids": ["d1"]}]


def _docs(ids):
    return [Document(id=i, text=CORPUS.get(i, ""), score=float(len(ids) - r), rank=r + 1) for r, i in enumerate(ids)]


def test_monolith_emits_per_stage_snapshots(tmp_path):
    """A wrapped monolith returning list[StageSnapshot] yields per-stage metrics (Phase 2)."""

    def monolith(query: str):
        # Stage 0 (candidate gen) finds the gold doc; stage 1 (rerank) drops it.
        return [
            StageSnapshot(stage_index=0, stage_id="candidates", documents=_docs(["d1", "d2", "d3"]), latency_ms=5.0),
            StageSnapshot(stage_index=1, stage_id="rerank", documents=_docs(["d2", "d3"]), latency_ms=2.0),
        ]

    rep = ro.evaluate(monolith, queries=QUERIES, corpus=CORPUS, k=5, db_path=str(tmp_path / "m.db"))
    keys = set(rep.metrics)
    assert any("stage0|recall@5" in k for k in keys)
    assert any("stage1|recall@5" in k for k in keys)

    stage0_recall = next(v["mean"] for k, v in rep.metrics.items() if "stage0|recall@5" in k)
    stage1_recall = next(v["mean"] for k, v in rep.metrics.items() if "stage1|recall@5" in k)
    assert stage0_recall == 1.0  # candidate stage found the gold doc
    assert stage1_recall == 0.0  # rerank dropped it -> reranker_drop is now visible
