# Run Comparison

**Verdict:** `PASS`  
**Validity:** `valid`  
**Baseline:** `4b5be1ce`  
**Candidate:** `b1ecb65d`

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

- `5ae08a0455429924de1b70fc` — `#/runs/b1ecb65d/queries/5ae08a0455429924de1b70fc/diff?against=4b5be1ce`
- `5ab2d3df554299194fa9352c` — `#/runs/b1ecb65d/queries/5ab2d3df554299194fa9352c/diff?against=4b5be1ce`
- `5ab262a4554299340b5254ac` — `#/runs/b1ecb65d/queries/5ab262a4554299340b5254ac/diff?against=4b5be1ce`
- `5adf4a275542993a75d26498` — `#/runs/b1ecb65d/queries/5adf4a275542993a75d26498/diff?against=4b5be1ce`
- `5adccf645542990d50227d32` — `#/runs/b1ecb65d/queries/5adccf645542990d50227d32/diff?against=4b5be1ce`
- `5ab4475c5542996a3a969f6c` — `#/runs/b1ecb65d/queries/5ab4475c5542996a3a969f6c/diff?against=4b5be1ce`
- `5a78db8055429970f5fffdb2` — `#/runs/b1ecb65d/queries/5a78db8055429970f5fffdb2/diff?against=4b5be1ce`
- `5a87ab9b5542996e4f3088c2` — `#/runs/b1ecb65d/queries/5a87ab9b5542996e4f3088c2/diff?against=4b5be1ce`
- `5a7140585542994082a3e6fa` — `#/runs/b1ecb65d/queries/5a7140585542994082a3e6fa/diff?against=4b5be1ce`
- `5adcfe5f5542992c1e3a24f0` — `#/runs/b1ecb65d/queries/5adcfe5f5542992c1e3a24f0/diff?against=4b5be1ce`
- `5a75f32055429976ec32bcb7` — `#/runs/b1ecb65d/queries/5a75f32055429976ec32bcb7/diff?against=4b5be1ce`
- `5a8a3e745542996c9b8d5e70` — `#/runs/b1ecb65d/queries/5a8a3e745542996c9b8d5e70/diff?against=4b5be1ce`
- `5a848b5c5542997175ce1ef2` — `#/runs/b1ecb65d/queries/5a848b5c5542997175ce1ef2/diff?against=4b5be1ce`
- `5aded04755429975fa854fa7` — `#/runs/b1ecb65d/queries/5aded04755429975fa854fa7/diff?against=4b5be1ce`
- `5ae352285542994393b9e685` — `#/runs/b1ecb65d/queries/5ae352285542994393b9e685/diff?against=4b5be1ce`
- `5abde4595542991f66106095` — `#/runs/b1ecb65d/queries/5abde4595542991f66106095/diff?against=4b5be1ce`
- `5abd516a5542992ac4f3825c` — `#/runs/b1ecb65d/queries/5abd516a5542992ac4f3825c/diff?against=4b5be1ce`
- `5a75092b55429916b0164242` — `#/runs/b1ecb65d/queries/5a75092b55429916b0164242/diff?against=4b5be1ce`
- `5a875b2a5542993e715abf0f` — `#/runs/b1ecb65d/queries/5a875b2a5542993e715abf0f/diff?against=4b5be1ce`
- `5abba584554299642a094afa` — `#/runs/b1ecb65d/queries/5abba584554299642a094afa/diff?against=4b5be1ce`

## Next action

Review the bounded evidence and proceed through the normal deployment approval process.

## Reproduce and inspect

- `retobs compare 4b5be1ce b1ecb65d --db /Users/ameyakiwalkar/Documents/retrieval-observatory/results/flagship_demo/.retobs/demo.db --policy /Users/ameyakiwalkar/Documents/retrieval-observatory/results/flagship_demo/release-policy.yaml`
- Dashboard: http://127.0.0.1:4000/#/compare

## Provenance

- **Baseline:** run `4b5be1ce`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "baseline", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`
- **Candidate:** run `b1ecb65d`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "candidate-wider-merge", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`

## Paired results

| Metric | Baseline | Candidate | Effect | q-value | n | Decision |
|---|---:|---:|---:|---:|---:|---|
| `hotpotqa_hybrid_dag|stage-1|dropout_count@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_p50@0` | 854.0280 | 944.9615 | 90.9335 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage-1|latency_p95@0` | 854.0280 | 944.9615 | 90.9335 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage-1|latency_p99@0` | 854.0280 | 944.9615 | 90.9335 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage-1|timeout_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_p50@0|branch=bm25_lane` | 14.3014 | 14.5387 | 0.2373 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_p50@0|branch=dense_lane` | 188.2689 | 203.3040 | 15.0352 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|latency_p95@0|branch=bm25_lane` | 14.3014 | 14.5387 | 0.2373 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_p95@0|branch=dense_lane` | 188.2689 | 203.3040 | 15.0352 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|latency_p99@0|branch=bm25_lane` | 14.3014 | 14.5387 | 0.2373 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_p99@0|branch=dense_lane` | 188.2689 | 203.3040 | 15.0352 | 0.0000 | 400 | candidate_worse |
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
| `hotpotqa_hybrid_dag|stage1|latency_p50@0` | 0.6954 | 0.7017 | 0.0063 | 0.6397 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_p95@0` | 0.6954 | 0.7017 | 0.0063 | 0.6397 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_p99@0` | 0.6954 | 0.7017 | 0.0063 | 0.6397 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|map@0` | 0.6684 | 0.6684 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|mrr@0` | 0.8778 | 0.8778 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|ndcg@10` | 0.7583 | 0.7583 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|precision@10` | 0.1682 | 0.1682 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|recall@10` | 0.8413 | 0.8413 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_p50@0` | 0.7931 | 0.7886 | -0.0045 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_p95@0` | 0.7931 | 0.7886 | -0.0045 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_p99@0` | 0.7931 | 0.7886 | -0.0045 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|map@0` | 0.6684 | 0.6684 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|mrr@0` | 0.8778 | 0.8778 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|ndcg@10` | 0.7583 | 0.7583 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|precision@10` | 0.1682 | 0.1682 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|recall@10` | 0.8413 | 0.8413 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|latency_p50@0|branch=bridge_hop2` | 159.4351 | 172.7061 | 13.2710 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p50@0|branch=comparison_widen` | 45.0303 | 48.2602 | 3.2298 | 0.0165 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p95@0|branch=bridge_hop2` | 159.4351 | 172.7061 | 13.2710 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p95@0|branch=comparison_widen` | 45.0303 | 48.2602 | 3.2298 | 0.0165 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p99@0|branch=bridge_hop2` | 159.4351 | 172.7061 | 13.2710 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p99@0|branch=comparison_widen` | 45.0303 | 48.2602 | 3.2298 | 0.0165 | 400 | candidate_worse |
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
| `hotpotqa_hybrid_dag|stage4|latency_p50@0` | 1.7737 | 1.3882 | -0.3855 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_p95@0` | 1.7737 | 1.3882 | -0.3855 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_p99@0` | 1.7737 | 1.3882 | -0.3855 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|map@0` | 0.4976 | 0.4976 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|mrr@0` | 0.6706 | 0.6706 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|ndcg@10` | 0.5701 | 0.5701 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|precision@10` | 0.1275 | 0.1275 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|recall@10` | 0.6375 | 0.6375 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_p50@0` | 0.8838 | 0.8192 | -0.0646 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_p95@0` | 0.8838 | 0.8192 | -0.0646 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_p99@0` | 0.8838 | 0.8192 | -0.0646 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|map@0` | 0.6684 | 0.6700 | 0.0016 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|mrr@0` | 0.8778 | 0.8778 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|ndcg@10` | 0.7583 | 0.7583 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|precision@10` | 0.1682 | 0.1682 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|recall@10` | 0.8413 | 0.8413 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_p50@0` | 0.5596 | 0.8175 | 0.2579 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_p95@0` | 0.5596 | 0.8175 | 0.2579 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_p99@0` | 0.5596 | 0.8175 | 0.2579 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|map@0` | 0.6684 | 0.6700 | 0.0016 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|mrr@0` | 0.8778 | 0.8778 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|ndcg@10` | 0.7583 | 0.7583 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|precision@10` | 0.1682 | 0.1682 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|recall@10` | 0.8413 | 0.8413 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p50@0|branch=fast_lane` | 0.3082 | 0.9951 | 0.6869 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p50@0|branch=rerank` | 426.9118 | 487.0578 | 60.1459 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|latency_p95@0|branch=fast_lane` | 0.3082 | 0.9951 | 0.6869 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p95@0|branch=rerank` | 426.9118 | 487.0578 | 60.1459 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|latency_p99@0|branch=fast_lane` | 0.3082 | 0.9951 | 0.6869 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p99@0|branch=rerank` | 426.9118 | 487.0578 | 60.1459 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=fast_lane` | 0.3809 | 0.3819 | 0.0009 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=rerank` | 0.3726 | 0.3754 | 0.0028 | 0.0735 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=fast_lane` | 0.5150 | 0.5150 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=rerank` | 0.4374 | 0.4361 | -0.0013 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=fast_lane` | 0.4261 | 0.4261 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=rerank` | 0.4031 | 0.4067 | 0.0035 | 0.0798 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=fast_lane` | 0.0893 | 0.0893 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=rerank` | 0.0858 | 0.0875 | 0.0017 | 0.0433 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=fast_lane` | 0.4462 | 0.4462 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=rerank` | 0.4288 | 0.4375 | 0.0087 | 0.0433 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_p50@0` | 0.4401 | 0.2361 | -0.2039 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_p95@0` | 0.4401 | 0.2361 | -0.2039 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_p99@0` | 0.4401 | 0.2361 | -0.2039 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|map@0` | 0.7472 | 0.7500 | 0.0028 | 0.0735 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|mrr@0` | 0.9523 | 0.9511 | -0.0012 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|ndcg@10` | 0.8292 | 0.8327 | 0.0035 | 0.0600 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|precision@10` | 0.1750 | 0.1768 | 0.0018 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|recall@10` | 0.8750 | 0.8838 | 0.0088 | 0.0000 | 400 | no_decision |

## Most affected queries

Candidate minus baseline for `hotpotqa_hybrid_dag|stage-1|latency_p50@0`.

| Query | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `5ae08a0455429924de1b70fc` | 1003.5754 | 1827.7116 | 824.1362 |
| `5ab2d3df554299194fa9352c` | 1012.6342 | 1626.3021 | 613.6679 |
| `5ab262a4554299340b5254ac` | 964.2435 | 1495.9468 | 531.7034 |
| `5adf4a275542993a75d26498` | 972.7890 | 1477.3044 | 504.5154 |
| `5adccf645542990d50227d32` | 1003.9053 | 1477.8613 | 473.9559 |
| `5ab4475c5542996a3a969f6c` | 8074.9089 | 8548.7889 | 473.8800 |
| `5a78db8055429970f5fffdb2` | 995.2764 | 1452.2354 | 456.9590 |
| `5a87ab9b5542996e4f3088c2` | 1059.8839 | 1515.2390 | 455.3550 |
| `5a7140585542994082a3e6fa` | 928.2125 | 1377.2909 | 449.0784 |
| `5adcfe5f5542992c1e3a24f0` | 1040.8144 | 1483.0639 | 442.2495 |
| `5a75f32055429976ec32bcb7` | 1002.2476 | 1440.3906 | 438.1430 |
| `5a8a3e745542996c9b8d5e70` | 1013.0213 | 1441.3724 | 428.3511 |
| `5a848b5c5542997175ce1ef2` | 8580.1573 | 8159.1156 | -421.0417 |
| `5aded04755429975fa854fa7` | 931.1555 | 1338.3051 | 407.1497 |
| `5ae352285542994393b9e685` | 8284.7152 | 8687.4994 | 402.7842 |
| `5abde4595542991f66106095` | 1068.5940 | 1467.7050 | 399.1110 |
| `5abd516a5542992ac4f3825c` | 915.0556 | 1294.2443 | 379.1886 |
| `5a75092b55429916b0164242` | 1022.0525 | 1395.0977 | 373.0452 |
| `5a875b2a5542993e715abf0f` | 916.9964 | 1285.3905 | 368.3942 |
| `5abba584554299642a094afa` | 1086.6926 | 1452.3276 | 365.6350 |
