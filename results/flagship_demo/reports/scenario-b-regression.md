# Run Comparison

**Verdict:** `PASS`  
**Validity:** `valid`  
**Baseline:** `4b5be1ce`  
**Candidate:** `c7b3767e`

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

- `5a72a0be5542992359bc3143` — `#/runs/c7b3767e/queries/5a72a0be5542992359bc3143/diff?against=4b5be1ce`
- `5a893f305542993b751ca91e` — `#/runs/c7b3767e/queries/5a893f305542993b751ca91e/diff?against=4b5be1ce`
- `5abb23035542992ccd8e7f22` — `#/runs/c7b3767e/queries/5abb23035542992ccd8e7f22/diff?against=4b5be1ce`
- `5ab5ec0a5542997d4ad1f250` — `#/runs/c7b3767e/queries/5ab5ec0a5542997d4ad1f250/diff?against=4b5be1ce`
- `5adea0c5554299728e26c776` — `#/runs/c7b3767e/queries/5adea0c5554299728e26c776/diff?against=4b5be1ce`
- `5a7fb1e55542995d8a8ddef7` — `#/runs/c7b3767e/queries/5a7fb1e55542995d8a8ddef7/diff?against=4b5be1ce`
- `5adec96e5542995534e8c712` — `#/runs/c7b3767e/queries/5adec96e5542995534e8c712/diff?against=4b5be1ce`
- `5ab42ef55542991751b4d6d9` — `#/runs/c7b3767e/queries/5ab42ef55542991751b4d6d9/diff?against=4b5be1ce`
- `5ae748d1554299572ea547b0` — `#/runs/c7b3767e/queries/5ae748d1554299572ea547b0/diff?against=4b5be1ce`
- `5a88a4245542997e5c09a668` — `#/runs/c7b3767e/queries/5a88a4245542997e5c09a668/diff?against=4b5be1ce`
- `5ab9379a554299753720f79d` — `#/runs/c7b3767e/queries/5ab9379a554299753720f79d/diff?against=4b5be1ce`
- `5a7c6d98554299683c1c6304` — `#/runs/c7b3767e/queries/5a7c6d98554299683c1c6304/diff?against=4b5be1ce`
- `5ae527945542993aec5ec167` — `#/runs/c7b3767e/queries/5ae527945542993aec5ec167/diff?against=4b5be1ce`
- `5ae32b6755429928c4239644` — `#/runs/c7b3767e/queries/5ae32b6755429928c4239644/diff?against=4b5be1ce`
- `5a8492ab5542992a431d1a5b` — `#/runs/c7b3767e/queries/5a8492ab5542992a431d1a5b/diff?against=4b5be1ce`
- `5a726b0f5542997f827839be` — `#/runs/c7b3767e/queries/5a726b0f5542997f827839be/diff?against=4b5be1ce`
- `5ae2a0a1554299495565dae9` — `#/runs/c7b3767e/queries/5ae2a0a1554299495565dae9/diff?against=4b5be1ce`
- `5a7997a2554299029c4b5f59` — `#/runs/c7b3767e/queries/5a7997a2554299029c4b5f59/diff?against=4b5be1ce`
- `5a83eaae55429933447460b4` — `#/runs/c7b3767e/queries/5a83eaae55429933447460b4/diff?against=4b5be1ce`
- `5ab1c6c5554299722f9b4c67` — `#/runs/c7b3767e/queries/5ab1c6c5554299722f9b4c67/diff?against=4b5be1ce`

## Next action

Review the bounded evidence and proceed through the normal deployment approval process.

## Reproduce and inspect

- `retobs compare 4b5be1ce c7b3767e --db /Users/ameyakiwalkar/Documents/retrieval-observatory/results/flagship_demo/.retobs/demo.db --policy /Users/ameyakiwalkar/Documents/retrieval-observatory/results/flagship_demo/release-policy.yaml`
- Dashboard: http://127.0.0.1:4000/#/compare

## Provenance

- **Baseline:** run `4b5be1ce`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "baseline", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`
- **Candidate:** run `c7b3767e`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "candidate-no-bm25", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`

## Paired results

| Metric | Baseline | Candidate | Effect | q-value | n | Decision |
|---|---:|---:|---:|---:|---:|---|
| `hotpotqa_hybrid_dag|stage-1|dropout_count@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_p50@0` | 854.0280 | 706.3859 | -147.6421 | 0.0041 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage-1|latency_p95@0` | 854.0280 | 706.3859 | -147.6421 | 0.0041 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage-1|latency_p99@0` | 854.0280 | 706.3859 | -147.6421 | 0.0041 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage-1|timeout_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_p50@0|branch=bm25_lane` | 14.3014 | 0.0125 | -14.2889 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage0|latency_p50@0|branch=dense_lane` | 188.2689 | 141.0223 | -47.2465 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage0|latency_p95@0|branch=bm25_lane` | 14.3014 | 0.0125 | -14.2889 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage0|latency_p95@0|branch=dense_lane` | 188.2689 | 141.0223 | -47.2465 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage0|latency_p99@0|branch=bm25_lane` | 14.3014 | 0.0125 | -14.2889 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage0|latency_p99@0|branch=dense_lane` | 188.2689 | 141.0223 | -47.2465 | 0.0000 | 400 | candidate_better |
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
| `hotpotqa_hybrid_dag|stage1|latency_p50@0` | 0.6954 | 0.4183 | -0.2771 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_p95@0` | 0.6954 | 0.4183 | -0.2771 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_p99@0` | 0.6954 | 0.4183 | -0.2771 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|map@0` | 0.6684 | 0.6444 | -0.0240 | 0.0227 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|mrr@0` | 0.8778 | 0.8668 | -0.0110 | 0.4420 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|ndcg@10` | 0.7583 | 0.7299 | -0.0284 | 0.0014 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|precision@10` | 0.1682 | 0.1573 | -0.0110 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|recall@10` | 0.8413 | 0.7863 | -0.0550 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|latency_p50@0` | 0.7931 | 0.6731 | -0.1200 | 0.5640 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_p95@0` | 0.7931 | 0.6731 | -0.1200 | 0.5640 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_p99@0` | 0.7931 | 0.6731 | -0.1200 | 0.5640 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|map@0` | 0.6684 | 0.6444 | -0.0240 | 0.0227 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|mrr@0` | 0.8778 | 0.8668 | -0.0110 | 0.4420 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|ndcg@10` | 0.7583 | 0.7299 | -0.0284 | 0.0014 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|precision@10` | 0.1682 | 0.1573 | -0.0110 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|recall@10` | 0.8413 | 0.7863 | -0.0550 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p50@0|branch=bridge_hop2` | 159.4351 | 113.1331 | -46.3020 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage3|latency_p50@0|branch=comparison_widen` | 45.0303 | 33.6561 | -11.3742 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage3|latency_p95@0|branch=bridge_hop2` | 159.4351 | 113.1331 | -46.3020 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage3|latency_p95@0|branch=comparison_widen` | 45.0303 | 33.6561 | -11.3742 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage3|latency_p99@0|branch=bridge_hop2` | 159.4351 | 113.1331 | -46.3020 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage3|latency_p99@0|branch=comparison_widen` | 45.0303 | 33.6561 | -11.3742 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=bridge_hop2` | 0.4964 | 0.4645 | -0.0319 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=comparison_widen` | 0.1723 | 0.1806 | 0.0083 | 0.1053 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=bridge_hop2` | 0.6706 | 0.6571 | -0.0135 | 0.2898 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=comparison_widen` | 0.2072 | 0.2098 | 0.0026 | 0.6545 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=bridge_hop2` | 0.5701 | 0.5354 | -0.0348 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=comparison_widen` | 0.1881 | 0.1946 | 0.0064 | 0.0733 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=bridge_hop2` | 0.1275 | 0.1158 | -0.0117 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=comparison_widen` | 0.0408 | 0.0415 | 0.0008 | 0.2314 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=bridge_hop2` | 0.6375 | 0.5787 | -0.0587 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=comparison_widen` | 0.2037 | 0.2075 | 0.0038 | 0.2314 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_p50@0` | 1.7737 | 1.1166 | -0.6571 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_p95@0` | 1.7737 | 1.1166 | -0.6571 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_p99@0` | 1.7737 | 1.1166 | -0.6571 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|map@0` | 0.4976 | 0.4683 | -0.0293 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|mrr@0` | 0.6706 | 0.6571 | -0.0135 | 0.2898 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|ndcg@10` | 0.5701 | 0.5354 | -0.0348 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|precision@10` | 0.1275 | 0.1158 | -0.0117 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|recall@10` | 0.6375 | 0.5787 | -0.0587 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|latency_p50@0` | 0.8838 | 0.4809 | -0.4029 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_p95@0` | 0.8838 | 0.4809 | -0.4029 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_p99@0` | 0.8838 | 0.4809 | -0.4029 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|map@0` | 0.6684 | 0.6485 | -0.0198 | 0.0638 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|mrr@0` | 0.8778 | 0.8669 | -0.0109 | 0.4420 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|ndcg@10` | 0.7583 | 0.7299 | -0.0284 | 0.0014 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|precision@10` | 0.1682 | 0.1573 | -0.0110 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|recall@10` | 0.8413 | 0.7863 | -0.0550 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|latency_p50@0` | 0.5596 | 0.4724 | -0.0872 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_p95@0` | 0.5596 | 0.4724 | -0.0872 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_p99@0` | 0.5596 | 0.4724 | -0.0872 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|map@0` | 0.6684 | 0.6485 | -0.0198 | 0.0638 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|mrr@0` | 0.8778 | 0.8669 | -0.0109 | 0.4420 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|ndcg@10` | 0.7583 | 0.7299 | -0.0284 | 0.0014 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|precision@10` | 0.1682 | 0.1573 | -0.0110 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|recall@10` | 0.8413 | 0.7863 | -0.0550 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|latency_p50@0|branch=fast_lane` | 0.3082 | 0.0000 | -0.3082 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p50@0|branch=rerank` | 426.9118 | 411.7254 | -15.1864 | 0.8131 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p95@0|branch=fast_lane` | 0.3082 | 0.0000 | -0.3082 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p95@0|branch=rerank` | 426.9118 | 411.7254 | -15.1864 | 0.8131 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p99@0|branch=fast_lane` | 0.3082 | 0.0000 | -0.3082 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p99@0|branch=rerank` | 426.9118 | 411.7254 | -15.1864 | 0.8131 | 400 | no_decision |
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
| `hotpotqa_hybrid_dag|stage8|latency_p50@0` | 0.4401 | 0.1373 | -0.3028 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_p95@0` | 0.4401 | 0.1373 | -0.3028 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_p99@0` | 0.4401 | 0.1373 | -0.3028 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|map@0` | 0.7472 | 0.7924 | 0.0452 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage8|mrr@0` | 0.9523 | 0.9553 | 0.0030 | 0.7615 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|ndcg@10` | 0.8292 | 0.8607 | 0.0315 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage8|precision@10` | 0.1750 | 0.1810 | 0.0060 | 0.0014 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|recall@10` | 0.8750 | 0.9050 | 0.0300 | 0.0014 | 400 | candidate_better |

## Most affected queries

Candidate minus baseline for `hotpotqa_hybrid_dag|stage0|map@0|branch=bm25_lane`.

| Query | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `5a72a0be5542992359bc3143` | 1.0000 | 0.0000 | -1.0000 |
| `5a893f305542993b751ca91e` | 1.0000 | 0.0000 | -1.0000 |
| `5abb23035542992ccd8e7f22` | 1.0000 | 0.0000 | -1.0000 |
| `5ab5ec0a5542997d4ad1f250` | 1.0000 | 0.0000 | -1.0000 |
| `5adea0c5554299728e26c776` | 1.0000 | 0.0000 | -1.0000 |
| `5a7fb1e55542995d8a8ddef7` | 1.0000 | 0.0000 | -1.0000 |
| `5adec96e5542995534e8c712` | 1.0000 | 0.0000 | -1.0000 |
| `5ab42ef55542991751b4d6d9` | 1.0000 | 0.0000 | -1.0000 |
| `5ae748d1554299572ea547b0` | 1.0000 | 0.0000 | -1.0000 |
| `5a88a4245542997e5c09a668` | 1.0000 | 0.0000 | -1.0000 |
| `5ab9379a554299753720f79d` | 1.0000 | 0.0000 | -1.0000 |
| `5a7c6d98554299683c1c6304` | 1.0000 | 0.0000 | -1.0000 |
| `5ae527945542993aec5ec167` | 1.0000 | 0.0000 | -1.0000 |
| `5ae32b6755429928c4239644` | 1.0000 | 0.0000 | -1.0000 |
| `5a8492ab5542992a431d1a5b` | 1.0000 | 0.0000 | -1.0000 |
| `5a726b0f5542997f827839be` | 1.0000 | 0.0000 | -1.0000 |
| `5ae2a0a1554299495565dae9` | 1.0000 | 0.0000 | -1.0000 |
| `5a7997a2554299029c4b5f59` | 1.0000 | 0.0000 | -1.0000 |
| `5a83eaae55429933447460b4` | 1.0000 | 0.0000 | -1.0000 |
| `5ab1c6c5554299722f9b4c67` | 1.0000 | 0.0000 | -1.0000 |
