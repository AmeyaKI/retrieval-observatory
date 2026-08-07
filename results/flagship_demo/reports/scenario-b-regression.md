# Run Comparison

**Verdict:** `PASS`  
**Validity:** `warning`  
**Baseline:** `0c9f6a25`  
**Candidate:** `de11e591`

The recorded evidence proves non-inferiority for every declared policy guard.

## Release decision

Artifact schema: `1`  
**Status:** `PASS`  
**Policy:** `hotpotqa-flagship-demo`  
**Policy schema:** `2`  
**Policy digest:** `sha256:5b22419daa098a342c68adb17007fe8ed90c461e51c61193b07a849e2c9209de`

### Claim readiness

| Scope | Status | Findings |
|---|---|---:|
| `promotion` | `READY` | 0 |
| `aggregate_or_slice_evaluation` | `READY` | 0 |
| `lineage_diagnosis` | `READY` | 0 |
| `lineage_diff` | `BLOCK` | 1 |
| `production_trace` | `BLOCK` | 1 |

### Evidence findings

- `lineage_diff/lineage_document_identity_partial` — Stable logical-chunk and document revision/content-hash identity is incomplete. Next: Record a document revision or content hash for every lineage candidate.
- `production_trace/telemetry_window_unavailable` — Production trace health is unavailable for at least one run window. Next: Capture instrumentation health inside each run window.

### Policy guard intervals

| Metric | Status | Effect | Interval | Paired n | Adjusted confidence |
|---|---|---:|---:|---:|---:|
| `hotpotqa_hybrid_dag|stage8|recall@10` | `PASS` | 0.0300 | 0.0056 to 0.0563 | 400 | 0.9875 |

### Declared slices

- `type-bridge` (`type='bridge'`): `PASS`, paired n=312, label coverage=1.0000
- `type-comparison` (`type='comparison'`): `PASS`, paired n=88, label coverage=1.0000
- `level-hard` (`level='hard'`): `PASS`, paired n=400, label coverage=1.0000

### Investigation references

- `5ac01bca5542992a796dec8d` — `#/runs/de11e591/queries/5ac01bca5542992a796dec8d/diff?against=0c9f6a25`
- `5ab5ec0a5542997d4ad1f250` — `#/runs/de11e591/queries/5ab5ec0a5542997d4ad1f250/diff?against=0c9f6a25`
- `5ae534bb5542990ba0bbb21d` — `#/runs/de11e591/queries/5ae534bb5542990ba0bbb21d/diff?against=0c9f6a25`
- `5ab2e3a35542991669774124` — `#/runs/de11e591/queries/5ab2e3a35542991669774124/diff?against=0c9f6a25`
- `5ab4f7fc5542991779162d43` — `#/runs/de11e591/queries/5ab4f7fc5542991779162d43/diff?against=0c9f6a25`
- `5a7769a35542993569682d8f` — `#/runs/de11e591/queries/5a7769a35542993569682d8f/diff?against=0c9f6a25`
- `5abd12bb55429933744ab703` — `#/runs/de11e591/queries/5abd12bb55429933744ab703/diff?against=0c9f6a25`
- `5abfca465542993fe9a41e65` — `#/runs/de11e591/queries/5abfca465542993fe9a41e65/diff?against=0c9f6a25`
- `5a77d65055429949eeb29f7b` — `#/runs/de11e591/queries/5a77d65055429949eeb29f7b/diff?against=0c9f6a25`
- `5a8038b55542996402f6a485` — `#/runs/de11e591/queries/5a8038b55542996402f6a485/diff?against=0c9f6a25`
- `5a7b3ec95542995eb53be8d3` — `#/runs/de11e591/queries/5a7b3ec95542995eb53be8d3/diff?against=0c9f6a25`
- `5a78bc6b554299148911f979` — `#/runs/de11e591/queries/5a78bc6b554299148911f979/diff?against=0c9f6a25`
- `5a72a9ab5542992359bc315a` — `#/runs/de11e591/queries/5a72a9ab5542992359bc315a/diff?against=0c9f6a25`
- `5a7fb1765542992e7d278d20` — `#/runs/de11e591/queries/5a7fb1765542992e7d278d20/diff?against=0c9f6a25`
- `5ae236445542992decbdcc69` — `#/runs/de11e591/queries/5ae236445542992decbdcc69/diff?against=0c9f6a25`
- `5a8492ab5542992a431d1a5b` — `#/runs/de11e591/queries/5a8492ab5542992a431d1a5b/diff?against=0c9f6a25`
- `5adea0c5554299728e26c776` — `#/runs/de11e591/queries/5adea0c5554299728e26c776/diff?against=0c9f6a25`
- `5ab9812d554299753720f821` — `#/runs/de11e591/queries/5ab9812d554299753720f821/diff?against=0c9f6a25`
- `5ae54eea5542993aec5ec19d` — `#/runs/de11e591/queries/5ae54eea5542993aec5ec19d/diff?against=0c9f6a25`
- `5a8a1b7a5542992d82986ec0` — `#/runs/de11e591/queries/5a8a1b7a5542992d82986ec0/diff?against=0c9f6a25`

## Next action

Review the bounded evidence and proceed through the normal deployment approval process.

## Reproduce and inspect

- `retobs compare 0c9f6a25 de11e591 --db .retobs/demo.db --policy release-policy.yaml`
- Dashboard: http://127.0.0.1:4000/#/compare

## Provenance

- **Baseline:** run `0c9f6a25`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "baseline", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`
- **Candidate:** run `de11e591`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "candidate-no-bm25", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`

## Validity evidence

- `git_commit`: Optional comparison metadata 'git_commit' is missing for at least one run.
- `git_dirty`: Optional comparison metadata 'git_dirty' is missing for at least one run.

## Paired results

| Metric | Baseline | Candidate | Effect | q-value | n | Decision |
|---|---:|---:|---:|---:|---:|---|
| `hotpotqa_hybrid_dag|stage-1|dropout_count@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_mean@0` | 840.6314 | 797.8788 | -42.7526 | 0.5177 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|timeout_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=bm25_lane` | 14.3702 | 0.0148 | -14.3554 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=dense_lane` | 191.5777 | 164.7436 | -26.8342 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=bm25_lane` | 0.6069 | 0.0000 | -0.6069 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=dense_lane` | 0.6444 | 0.6444 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=bm25_lane` | 0.8279 | 0.0000 | -0.8279 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=dense_lane` | 0.8668 | 0.8668 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=bm25_lane` | 0.6991 | 0.0000 | -0.6991 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=dense_lane` | 0.7299 | 0.7299 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=bm25_lane` | 0.1552 | 0.0000 | -0.1552 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=dense_lane` | 0.1573 | 0.1573 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=bm25_lane` | 0.7762 | 0.0000 | -0.7762 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=dense_lane` | 0.7863 | 0.7863 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_mean@0` | 0.6875 | 0.5109 | -0.1766 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|map@0` | 0.6684 | 0.6444 | -0.0240 | 0.0248 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|mrr@0` | 0.8778 | 0.8668 | -0.0110 | 0.4450 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|ndcg@10` | 0.7583 | 0.7299 | -0.0284 | 0.0015 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|precision@10` | 0.1682 | 0.1573 | -0.0110 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|recall@10` | 0.8413 | 0.7863 | -0.0550 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|latency_mean@0` | 0.7668 | 0.5039 | -0.2629 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|map@0` | 0.6684 | 0.6444 | -0.0240 | 0.0248 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|mrr@0` | 0.8778 | 0.8668 | -0.0110 | 0.4450 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|ndcg@10` | 0.7583 | 0.7299 | -0.0284 | 0.0015 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|precision@10` | 0.1682 | 0.1573 | -0.0110 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|recall@10` | 0.8413 | 0.7863 | -0.0550 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=bridge_hop2` | 157.5002 | 126.3093 | -31.1909 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=comparison_widen` | 43.2031 | 36.8172 | -6.3859 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=bridge_hop2` | 0.4964 | 0.4645 | -0.0319 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=comparison_widen` | 0.1723 | 0.1806 | 0.0083 | 0.1122 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=bridge_hop2` | 0.6706 | 0.6571 | -0.0135 | 0.3021 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=comparison_widen` | 0.2072 | 0.2098 | 0.0026 | 0.6581 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=bridge_hop2` | 0.5701 | 0.5354 | -0.0348 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=comparison_widen` | 0.1881 | 0.1946 | 0.0064 | 0.0785 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=bridge_hop2` | 0.1275 | 0.1158 | -0.0117 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=comparison_widen` | 0.0408 | 0.0415 | 0.0008 | 0.2438 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=bridge_hop2` | 0.6375 | 0.5787 | -0.0587 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=comparison_widen` | 0.2037 | 0.2075 | 0.0038 | 0.2438 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_mean@0` | 1.5936 | 1.3563 | -0.2373 | 0.3205 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|map@0` | 0.4976 | 0.4683 | -0.0293 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|mrr@0` | 0.6706 | 0.6571 | -0.0135 | 0.3021 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|ndcg@10` | 0.5701 | 0.5354 | -0.0348 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|precision@10` | 0.1275 | 0.1158 | -0.0117 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|recall@10` | 0.6375 | 0.5787 | -0.0587 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|latency_mean@0` | 0.8919 | 0.5914 | -0.3004 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|map@0` | 0.6684 | 0.6485 | -0.0198 | 0.0688 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|mrr@0` | 0.8778 | 0.8669 | -0.0109 | 0.4450 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|ndcg@10` | 0.7583 | 0.7299 | -0.0284 | 0.0015 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|precision@10` | 0.1682 | 0.1573 | -0.0110 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|recall@10` | 0.8413 | 0.7863 | -0.0550 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|latency_mean@0` | 0.8029 | 0.5835 | -0.2193 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|map@0` | 0.6684 | 0.6485 | -0.0198 | 0.0688 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|mrr@0` | 0.8778 | 0.8669 | -0.0109 | 0.4450 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|ndcg@10` | 0.7583 | 0.7299 | -0.0284 | 0.0015 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|precision@10` | 0.1682 | 0.1573 | -0.0110 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|recall@10` | 0.8413 | 0.7863 | -0.0550 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=fast_lane` | 0.3006 | 0.0000 | -0.3006 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=rerank` | 417.8948 | 461.8855 | 43.9907 | 0.5019 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=fast_lane` | 0.3809 | 0.0000 | -0.3809 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=rerank` | 0.3726 | 0.7924 | 0.4198 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=fast_lane` | 0.5150 | 0.0000 | -0.5150 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=rerank` | 0.4374 | 0.9553 | 0.5179 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=fast_lane` | 0.4261 | 0.0000 | -0.4261 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=rerank` | 0.4031 | 0.8607 | 0.4576 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=fast_lane` | 0.0893 | 0.0000 | -0.0893 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=rerank` | 0.0858 | 0.1810 | 0.0953 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=fast_lane` | 0.4462 | 0.0000 | -0.4462 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=rerank` | 0.4288 | 0.9050 | 0.4763 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage8|latency_mean@0` | 0.2047 | 0.1680 | -0.0368 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|map@0` | 0.7472 | 0.7924 | 0.0452 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage8|mrr@0` | 0.9523 | 0.9553 | 0.0030 | 0.7627 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|ndcg@10` | 0.8292 | 0.8607 | 0.0315 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage8|precision@10` | 0.1750 | 0.1810 | 0.0060 | 0.0015 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|recall@10` | 0.8750 | 0.9050 | 0.0300 | 0.0015 | 400 | candidate_better |

## Most affected queries

Candidate minus baseline for `hotpotqa_hybrid_dag|stage0|map@0|branch=bm25_lane`.

| Query | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `5ac01bca5542992a796dec8d` | 1.0000 | 0.0000 | -1.0000 |
| `5ab5ec0a5542997d4ad1f250` | 1.0000 | 0.0000 | -1.0000 |
| `5ae534bb5542990ba0bbb21d` | 1.0000 | 0.0000 | -1.0000 |
| `5ab2e3a35542991669774124` | 1.0000 | 0.0000 | -1.0000 |
| `5ab4f7fc5542991779162d43` | 1.0000 | 0.0000 | -1.0000 |
| `5a7769a35542993569682d8f` | 1.0000 | 0.0000 | -1.0000 |
| `5abd12bb55429933744ab703` | 1.0000 | 0.0000 | -1.0000 |
| `5abfca465542993fe9a41e65` | 1.0000 | 0.0000 | -1.0000 |
| `5a77d65055429949eeb29f7b` | 1.0000 | 0.0000 | -1.0000 |
| `5a8038b55542996402f6a485` | 1.0000 | 0.0000 | -1.0000 |
| `5a7b3ec95542995eb53be8d3` | 1.0000 | 0.0000 | -1.0000 |
| `5a78bc6b554299148911f979` | 1.0000 | 0.0000 | -1.0000 |
| `5a72a9ab5542992359bc315a` | 1.0000 | 0.0000 | -1.0000 |
| `5a7fb1765542992e7d278d20` | 1.0000 | 0.0000 | -1.0000 |
| `5ae236445542992decbdcc69` | 1.0000 | 0.0000 | -1.0000 |
| `5a8492ab5542992a431d1a5b` | 1.0000 | 0.0000 | -1.0000 |
| `5adea0c5554299728e26c776` | 1.0000 | 0.0000 | -1.0000 |
| `5ab9812d554299753720f821` | 1.0000 | 0.0000 | -1.0000 |
| `5ae54eea5542993aec5ec19d` | 1.0000 | 0.0000 | -1.0000 |
| `5a8a1b7a5542992d82986ec0` | 1.0000 | 0.0000 | -1.0000 |
