# Run Comparison

**Verdict:** `PASS`  
**Validity:** `warning`  
**Baseline:** `0c9f6a25`  
**Candidate:** `2c3572a1`

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
| `hotpotqa_hybrid_dag|stage8|recall@10` | `PASS` | 0.0088 | 0.0019 to 0.0181 | 400 | 0.9875 |

### Declared slices

- `type-bridge` (`type='bridge'`): `PASS`, paired n=312, label coverage=1.0000
- `type-comparison` (`type='comparison'`): `PASS`, paired n=88, label coverage=1.0000
- `level-hard` (`level='hard'`): `PASS`, paired n=400, label coverage=1.0000

### Investigation references

- `5ae08a0455429924de1b70fc` — `#/runs/2c3572a1/queries/5ae08a0455429924de1b70fc/diff?against=0c9f6a25`
- `5ab2d3df554299194fa9352c` — `#/runs/2c3572a1/queries/5ab2d3df554299194fa9352c/diff?against=0c9f6a25`
- `5adccf645542990d50227d32` — `#/runs/2c3572a1/queries/5adccf645542990d50227d32/diff?against=0c9f6a25`
- `5a7140585542994082a3e6fa` — `#/runs/2c3572a1/queries/5a7140585542994082a3e6fa/diff?against=0c9f6a25`
- `5ae249925542994d89d5b3c1` — `#/runs/2c3572a1/queries/5ae249925542994d89d5b3c1/diff?against=0c9f6a25`
- `5a7150c75542994082a3e7be` — `#/runs/2c3572a1/queries/5a7150c75542994082a3e7be/diff?against=0c9f6a25`
- `5a8a3e745542996c9b8d5e70` — `#/runs/2c3572a1/queries/5a8a3e745542996c9b8d5e70/diff?against=0c9f6a25`
- `5ae1500655429920d52343cc` — `#/runs/2c3572a1/queries/5ae1500655429920d52343cc/diff?against=0c9f6a25`
- `5ae527945542993aec5ec167` — `#/runs/2c3572a1/queries/5ae527945542993aec5ec167/diff?against=0c9f6a25`
- `5a75f32055429976ec32bcb7` — `#/runs/2c3572a1/queries/5a75f32055429976ec32bcb7/diff?against=0c9f6a25`
- `5a8b987f5542997f31a41d7a` — `#/runs/2c3572a1/queries/5a8b987f5542997f31a41d7a/diff?against=0c9f6a25`
- `5a7af32e55429931da12c99c` — `#/runs/2c3572a1/queries/5a7af32e55429931da12c99c/diff?against=0c9f6a25`
- `5adcfe5f5542992c1e3a24f0` — `#/runs/2c3572a1/queries/5adcfe5f5542992c1e3a24f0/diff?against=0c9f6a25`
- `5ab950bd55429970cfb8ea4c` — `#/runs/2c3572a1/queries/5ab950bd55429970cfb8ea4c/diff?against=0c9f6a25`
- `5a87ab9b5542996e4f3088c2` — `#/runs/2c3572a1/queries/5a87ab9b5542996e4f3088c2/diff?against=0c9f6a25`
- `5a75092b55429916b0164242` — `#/runs/2c3572a1/queries/5a75092b55429916b0164242/diff?against=0c9f6a25`
- `5ae4f2c75542993aec5ec0fb` — `#/runs/2c3572a1/queries/5ae4f2c75542993aec5ec0fb/diff?against=0c9f6a25`
- `5a8466a75542993344746108` — `#/runs/2c3572a1/queries/5a8466a75542993344746108/diff?against=0c9f6a25`
- `5ab8f33155429919ba4e237f` — `#/runs/2c3572a1/queries/5ab8f33155429919ba4e237f/diff?against=0c9f6a25`
- `5a88a4245542997e5c09a668` — `#/runs/2c3572a1/queries/5a88a4245542997e5c09a668/diff?against=0c9f6a25`

## Next action

Review the bounded evidence and proceed through the normal deployment approval process.

## Reproduce and inspect

- `retobs compare 0c9f6a25 2c3572a1 --db .retobs/demo.db --policy release-policy.yaml`
- Dashboard: http://127.0.0.1:4000/#/compare

## Provenance

- **Baseline:** run `0c9f6a25`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "baseline", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`
- **Candidate:** run `2c3572a1`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "candidate-wider-merge", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`

## Validity evidence

- `git_commit`: Optional comparison metadata 'git_commit' is missing for at least one run.
- `git_dirty`: Optional comparison metadata 'git_dirty' is missing for at least one run.

## Paired results

| Metric | Baseline | Candidate | Effect | q-value | n | Decision |
|---|---:|---:|---:|---:|---:|---|
| `hotpotqa_hybrid_dag|stage-1|dropout_count@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_mean@0` | 840.6314 | 1049.3476 | 208.7162 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage-1|timeout_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=bm25_lane` | 14.3702 | 17.0652 | 2.6950 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=dense_lane` | 191.5777 | 233.3142 | 41.7364 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=bm25_lane` | 0.6069 | 0.6069 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=dense_lane` | 0.6444 | 0.6444 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=bm25_lane` | 0.8279 | 0.8279 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=dense_lane` | 0.8668 | 0.8668 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=bm25_lane` | 0.6991 | 0.6991 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=dense_lane` | 0.7299 | 0.7299 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=bm25_lane` | 0.1552 | 0.1552 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=dense_lane` | 0.1573 | 0.1573 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=bm25_lane` | 0.7762 | 0.7762 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=dense_lane` | 0.7863 | 0.7863 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_mean@0` | 0.6875 | 1.0133 | 0.3258 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|map@0` | 0.6684 | 0.6684 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|mrr@0` | 0.8778 | 0.8778 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|ndcg@10` | 0.7583 | 0.7583 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|precision@10` | 0.1682 | 0.1682 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|recall@10` | 0.8413 | 0.8413 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_mean@0` | 0.7668 | 0.6505 | -0.1163 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|map@0` | 0.6684 | 0.6684 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|mrr@0` | 0.8778 | 0.8778 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|ndcg@10` | 0.7583 | 0.7583 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|precision@10` | 0.1682 | 0.1682 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|recall@10` | 0.8413 | 0.8413 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=bridge_hop2` | 157.5002 | 196.6091 | 39.1089 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=comparison_widen` | 43.2031 | 53.5925 | 10.3893 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=bridge_hop2` | 0.4964 | 0.4964 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=comparison_widen` | 0.1723 | 0.1723 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=bridge_hop2` | 0.6706 | 0.6706 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=comparison_widen` | 0.2072 | 0.2072 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=bridge_hop2` | 0.5701 | 0.5701 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=comparison_widen` | 0.1881 | 0.1881 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=bridge_hop2` | 0.1275 | 0.1275 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=comparison_widen` | 0.0408 | 0.0408 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=bridge_hop2` | 0.6375 | 0.6375 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=comparison_widen` | 0.2037 | 0.2037 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_mean@0` | 1.5936 | 1.6092 | 0.0156 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|map@0` | 0.4976 | 0.4976 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|mrr@0` | 0.6706 | 0.6706 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|ndcg@10` | 0.5701 | 0.5701 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|precision@10` | 0.1275 | 0.1275 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|recall@10` | 0.6375 | 0.6375 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_mean@0` | 0.8919 | 0.9572 | 0.0654 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|map@0` | 0.6684 | 0.6700 | 0.0016 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|mrr@0` | 0.8778 | 0.8778 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|ndcg@10` | 0.7583 | 0.7583 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|precision@10` | 0.1682 | 0.1682 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|recall@10` | 0.8413 | 0.8413 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_mean@0` | 0.8029 | 0.9546 | 0.1517 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|map@0` | 0.6684 | 0.6700 | 0.0016 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|mrr@0` | 0.8778 | 0.8778 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|ndcg@10` | 0.7583 | 0.7583 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|precision@10` | 0.1682 | 0.1682 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|recall@10` | 0.8413 | 0.8413 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=fast_lane` | 0.3006 | 0.5331 | 0.2324 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=rerank` | 417.8948 | 530.3284 | 112.4336 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=fast_lane` | 0.3809 | 0.3819 | 0.0009 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=rerank` | 0.3726 | 0.3754 | 0.0028 | 0.0949 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=fast_lane` | 0.5150 | 0.5150 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=rerank` | 0.4374 | 0.4361 | -0.0013 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=fast_lane` | 0.4261 | 0.4261 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=rerank` | 0.4031 | 0.4067 | 0.0035 | 0.1008 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=fast_lane` | 0.0893 | 0.0893 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=rerank` | 0.0858 | 0.0875 | 0.0017 | 0.0601 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=fast_lane` | 0.4462 | 0.4462 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=rerank` | 0.4288 | 0.4375 | 0.0087 | 0.0601 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_mean@0` | 0.2047 | 0.2799 | 0.0752 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|map@0` | 0.7472 | 0.7500 | 0.0028 | 0.0949 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|mrr@0` | 0.9523 | 0.9511 | -0.0012 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|ndcg@10` | 0.8292 | 0.8327 | 0.0035 | 0.0811 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|precision@10` | 0.1750 | 0.1768 | 0.0018 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|recall@10` | 0.8750 | 0.8838 | 0.0088 | 0.0000 | 400 | no_decision |

## Most affected queries

Candidate minus baseline for `hotpotqa_hybrid_dag|stage-1|latency_mean@0`.

| Query | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `5ae08a0455429924de1b70fc` | 909.9693 | 2047.9904 | 1138.0211 |
| `5ab2d3df554299194fa9352c` | 988.5377 | 1963.7345 | 975.1968 |
| `5adccf645542990d50227d32` | 968.3488 | 1853.8781 | 885.5293 |
| `5a7140585542994082a3e6fa` | 921.4790 | 1801.1240 | 879.6451 |
| `5ae249925542994d89d5b3c1` | 955.7358 | 1810.2930 | 854.5573 |
| `5a7150c75542994082a3e7be` | 972.9428 | 1811.3267 | 838.3839 |
| `5a8a3e745542996c9b8d5e70` | 965.7777 | 1751.1022 | 785.3245 |
| `5ae1500655429920d52343cc` | 945.8335 | 1729.3334 | 783.4999 |
| `5ae527945542993aec5ec167` | 996.8985 | 1779.9593 | 783.0608 |
| `5a75f32055429976ec32bcb7` | 905.6128 | 1678.0324 | 772.4196 |
| `5a8b987f5542997f31a41d7a` | 915.0840 | 1668.7554 | 753.6714 |
| `5a7af32e55429931da12c99c` | 962.3747 | 1697.1498 | 734.7751 |
| `5adcfe5f5542992c1e3a24f0` | 917.0515 | 1639.4608 | 722.4094 |
| `5ab950bd55429970cfb8ea4c` | 965.7538 | 1682.7991 | 717.0453 |
| `5a87ab9b5542996e4f3088c2` | 1017.4362 | 1726.2230 | 708.7867 |
| `5a75092b55429916b0164242` | 881.9735 | 1581.4034 | 699.4299 |
| `5ae4f2c75542993aec5ec0fb` | 1012.5823 | 1681.3415 | 668.7592 |
| `5a8466a75542993344746108` | 940.1484 | 1598.7604 | 658.6120 |
| `5ab8f33155429919ba4e237f` | 983.5530 | 1639.1422 | 655.5892 |
| `5a88a4245542997e5c09a668` | 920.7820 | 1573.6700 | 652.8880 |
