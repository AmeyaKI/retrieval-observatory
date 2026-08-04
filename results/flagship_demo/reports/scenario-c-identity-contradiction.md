# Run Comparison

**Verdict:** `BLOCK`  
**Validity:** `valid`  
**Baseline:** `4b5be1ce`  
**Candidate:** `6fe66dac`

Required promotion evidence is missing or invalid; metric deltas are not decision-bearing.

## Release decision

Artifact schema: `1`  
**Status:** `BLOCK`  
**Policy:** `hotpotqa-flagship-demo`  
**Policy schema:** `2`  
**Policy digest:** `sha256:5b22419daa098a342c68adb17007fe8ed90c461e51c61193b07a849e2c9209de`

### Claim readiness

| Scope | Status | Findings |
|---|---|---:|
| `promotion` | `BLOCK` | 1 |
| `aggregate_or_slice_evaluation` | `BLOCK` | 1 |
| `lineage_diagnosis` | `READY` | 0 |
| `lineage_diff` | `BLOCK` | 1 |
| `production_trace` | `BLOCK` | 1 |

### Evidence findings

- `promotion/release_identity_mismatch` — Runs differ on release identity field 'embedding_model_revision'. Next: Compare runs with the same embedding_model_revision.
- `aggregate_or_slice_evaluation/release_identity_mismatch` — Runs differ on release identity field 'embedding_model_revision'. Next: Compare runs with the same embedding_model_revision.
- `lineage_diff/lineage_document_identity_partial` — Stable logical-chunk and document revision/content-hash identity is incomplete. Next: Record a document revision or content hash for every lineage candidate.
- `production_trace/telemetry_window_unavailable` — Production trace health is unavailable for at least one run window. Next: Capture instrumentation health inside each run window.

### Policy guard intervals

| Metric | Status | Effect | Interval | Paired n | Adjusted confidence |
|---|---|---:|---:|---:|---:|
| `hotpotqa_hybrid_dag|stage8|recall@10` | `PASS` | 0.0000 | -0.0175 to 0.0188 | 400 | 0.9875 |

### Declared slices

- `type-bridge` (`type='bridge'`): `HOLD`, paired n=312, label coverage=1.0000
- `type-comparison` (`type='comparison'`): `HOLD`, paired n=88, label coverage=1.0000
- `level-hard` (`level='hard'`): `PASS`, paired n=400, label coverage=1.0000

### Investigation references

- `5ab981555542996be2020532` — `#/runs/6fe66dac/queries/5ab981555542996be2020532/diff?against=4b5be1ce`
- `5adcceda5542990d50227d31` — `#/runs/6fe66dac/queries/5adcceda5542990d50227d31/diff?against=4b5be1ce`
- `5a7d61645542997cc2c47455` — `#/runs/6fe66dac/queries/5a7d61645542997cc2c47455/diff?against=4b5be1ce`
- `5a7cef5d55429909bec768ac` — `#/runs/6fe66dac/queries/5a7cef5d55429909bec768ac/diff?against=4b5be1ce`
- `5ae0aefe554299603e418437` — `#/runs/6fe66dac/queries/5ae0aefe554299603e418437/diff?against=4b5be1ce`
- `5ac119335542992a796dede4` — `#/runs/6fe66dac/queries/5ac119335542992a796dede4/diff?against=4b5be1ce`
- `5a7140585542994082a3e6fa` — `#/runs/6fe66dac/queries/5a7140585542994082a3e6fa/diff?against=4b5be1ce`
- `5adf4a275542993a75d26498` — `#/runs/6fe66dac/queries/5adf4a275542993a75d26498/diff?against=4b5be1ce`
- `5ac1a3fa5542991316484b7d` — `#/runs/6fe66dac/queries/5ac1a3fa5542991316484b7d/diff?against=4b5be1ce`
- `5ae54eea5542993aec5ec19d` — `#/runs/6fe66dac/queries/5ae54eea5542993aec5ec19d/diff?against=4b5be1ce`
- `5a84c4135542994c784dda31` — `#/runs/6fe66dac/queries/5a84c4135542994c784dda31/diff?against=4b5be1ce`
- `5a75fa14554299109176e5dc` — `#/runs/6fe66dac/queries/5a75fa14554299109176e5dc/diff?against=4b5be1ce`
- `5a877e5d5542993e715abf7d` — `#/runs/6fe66dac/queries/5a877e5d5542993e715abf7d/diff?against=4b5be1ce`
- `5ae47df15542996836b02cba` — `#/runs/6fe66dac/queries/5ae47df15542996836b02cba/diff?against=4b5be1ce`
- `5ab808ea5542991d3222380e` — `#/runs/6fe66dac/queries/5ab808ea5542991d3222380e/diff?against=4b5be1ce`
- `5abba584554299642a094afa` — `#/runs/6fe66dac/queries/5abba584554299642a094afa/diff?against=4b5be1ce`
- `5abce9ca554299114383a193` — `#/runs/6fe66dac/queries/5abce9ca554299114383a193/diff?against=4b5be1ce`
- `5ae1e9fd5542997f29b3c1a1` — `#/runs/6fe66dac/queries/5ae1e9fd5542997f29b3c1a1/diff?against=4b5be1ce`
- `5ab78edc5542995dae37e95c` — `#/runs/6fe66dac/queries/5ab78edc5542995dae37e95c/diff?against=4b5be1ce`
- `5abd94525542992ac4f382d2` — `#/runs/6fe66dac/queries/5abd94525542992ac4f382d2/diff?against=4b5be1ce`

## Next action

Resolve missing or invalid required evidence, then rerun the comparison.

## Reproduce and inspect

- `retobs compare 4b5be1ce 6fe66dac --db /Users/ameyakiwalkar/Documents/retrieval-observatory/results/flagship_demo/.retobs/demo.db --policy /Users/ameyakiwalkar/Documents/retrieval-observatory/results/flagship_demo/release-policy.yaml`
- Dashboard: http://127.0.0.1:4000/#/compare

## Provenance

- **Baseline:** run `4b5be1ce`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "baseline", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`
- **Candidate:** run `6fe66dac`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "candidate-swapped-embedding", "embedding_model_revision": "sentence-transformers/all-MiniLM-L12-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`

## Paired results

| Metric | Baseline | Candidate | Effect | q-value | n | Decision |
|---|---:|---:|---:|---:|---:|---|
| `hotpotqa_hybrid_dag|stage-1|dropout_count@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_p50@0` | 854.0280 | 871.7889 | 17.7609 | 0.9035 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_p95@0` | 854.0280 | 871.7889 | 17.7609 | 0.9035 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_p99@0` | 854.0280 | 871.7889 | 17.7609 | 0.9035 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|timeout_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_p50@0|branch=bm25_lane` | 14.3014 | 14.0181 | -0.2833 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_p50@0|branch=dense_lane` | 188.2689 | 230.8584 | 42.5896 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|latency_p95@0|branch=bm25_lane` | 14.3014 | 14.0181 | -0.2833 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_p95@0|branch=dense_lane` | 188.2689 | 230.8584 | 42.5896 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|latency_p99@0|branch=bm25_lane` | 14.3014 | 14.0181 | -0.2833 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_p99@0|branch=dense_lane` | 188.2689 | 230.8584 | 42.5896 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=bm25_lane` | 0.6069 | 0.6069 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=dense_lane` | 0.6444 | 0.6538 | 0.0094 | 0.4929 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=bm25_lane` | 0.8279 | 0.8279 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=dense_lane` | 0.8668 | 0.8789 | 0.0121 | 0.4774 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=bm25_lane` | 0.6991 | 0.6991 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=dense_lane` | 0.7299 | 0.7421 | 0.0122 | 0.2602 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=bm25_lane` | 0.1552 | 0.1552 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=dense_lane` | 0.1573 | 0.1600 | 0.0028 | 0.3044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=bm25_lane` | 0.7762 | 0.7762 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=dense_lane` | 0.7863 | 0.8000 | 0.0138 | 0.3044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_p50@0` | 0.6954 | 0.6839 | -0.0115 | 0.2044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_p95@0` | 0.6954 | 0.6839 | -0.0115 | 0.2044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_p99@0` | 0.6954 | 0.6839 | -0.0115 | 0.2044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|map@0` | 0.6684 | 0.6795 | 0.0111 | 0.2044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|mrr@0` | 0.8778 | 0.8851 | 0.0073 | 0.6030 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|ndcg@10` | 0.7583 | 0.7677 | 0.0095 | 0.2044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|precision@10` | 0.1682 | 0.1695 | 0.0013 | 0.5998 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|recall@10` | 0.8413 | 0.8475 | 0.0062 | 0.8000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_p50@0` | 0.7931 | 0.5511 | -0.2420 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_p95@0` | 0.7931 | 0.5511 | -0.2420 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_p99@0` | 0.7931 | 0.5511 | -0.2420 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|map@0` | 0.6684 | 0.6795 | 0.0111 | 0.2044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|mrr@0` | 0.8778 | 0.8851 | 0.0073 | 0.6030 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|ndcg@10` | 0.7583 | 0.7677 | 0.0095 | 0.2044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|precision@10` | 0.1682 | 0.1695 | 0.0013 | 0.5998 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|recall@10` | 0.8413 | 0.8475 | 0.0062 | 0.8000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|latency_p50@0|branch=bridge_hop2` | 159.4351 | 198.3519 | 38.9168 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p50@0|branch=comparison_widen` | 45.0303 | 55.5514 | 10.5210 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p95@0|branch=bridge_hop2` | 159.4351 | 198.3519 | 38.9168 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p95@0|branch=comparison_widen` | 45.0303 | 55.5514 | 10.5210 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p99@0|branch=bridge_hop2` | 159.4351 | 198.3519 | 38.9168 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p99@0|branch=comparison_widen` | 45.0303 | 55.5514 | 10.5210 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=bridge_hop2` | 0.4964 | 0.5043 | 0.0079 | 0.3044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=comparison_widen` | 0.1723 | 0.1756 | 0.0033 | 0.4929 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=bridge_hop2` | 0.6706 | 0.6798 | 0.0092 | 0.4635 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=comparison_widen` | 0.2072 | 0.2053 | -0.0019 | 0.7266 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=bridge_hop2` | 0.5701 | 0.5765 | 0.0063 | 0.4243 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=comparison_widen` | 0.1881 | 0.1912 | 0.0031 | 0.3044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=bridge_hop2` | 0.1275 | 0.1275 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=comparison_widen` | 0.0408 | 0.0420 | 0.0013 | 0.1980 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=bridge_hop2` | 0.6375 | 0.6375 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=comparison_widen` | 0.2037 | 0.2100 | 0.0063 | 0.1980 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_p50@0` | 1.7737 | 1.3283 | -0.4454 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_p95@0` | 1.7737 | 1.3283 | -0.4454 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_p99@0` | 1.7737 | 1.3283 | -0.4454 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|map@0` | 0.4976 | 0.5057 | 0.0081 | 0.3044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|mrr@0` | 0.6706 | 0.6798 | 0.0092 | 0.4635 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|ndcg@10` | 0.5701 | 0.5765 | 0.0063 | 0.4243 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|precision@10` | 0.1275 | 0.1275 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|recall@10` | 0.6375 | 0.6375 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_p50@0` | 0.8838 | 0.9652 | 0.0814 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_p95@0` | 0.8838 | 0.9652 | 0.0814 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_p99@0` | 0.8838 | 0.9652 | 0.0814 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|map@0` | 0.6684 | 0.6795 | 0.0111 | 0.2044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|mrr@0` | 0.8778 | 0.8851 | 0.0073 | 0.6030 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|ndcg@10` | 0.7583 | 0.7677 | 0.0095 | 0.2044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|precision@10` | 0.1682 | 0.1695 | 0.0013 | 0.5998 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|recall@10` | 0.8413 | 0.8475 | 0.0062 | 0.8000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_p50@0` | 0.5596 | 0.8150 | 0.2554 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_p95@0` | 0.5596 | 0.8150 | 0.2554 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_p99@0` | 0.5596 | 0.8150 | 0.2554 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|map@0` | 0.6684 | 0.6795 | 0.0111 | 0.2044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|mrr@0` | 0.8778 | 0.8851 | 0.0073 | 0.6030 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|ndcg@10` | 0.7583 | 0.7677 | 0.0095 | 0.2044 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|precision@10` | 0.1682 | 0.1695 | 0.0013 | 0.5998 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|recall@10` | 0.8413 | 0.8475 | 0.0062 | 0.8000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p50@0|branch=fast_lane` | 0.3082 | 0.3023 | -0.0059 | 0.8484 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p50@0|branch=rerank` | 426.9118 | 354.3310 | -72.5808 | 0.2388 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p95@0|branch=fast_lane` | 0.3082 | 0.3023 | -0.0059 | 0.8484 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p95@0|branch=rerank` | 426.9118 | 354.3310 | -72.5808 | 0.2388 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p99@0|branch=fast_lane` | 0.3082 | 0.3023 | -0.0059 | 0.8484 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p99@0|branch=rerank` | 426.9118 | 354.3310 | -72.5808 | 0.2388 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=fast_lane` | 0.3809 | 0.3863 | 0.0054 | 0.9035 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=rerank` | 0.3726 | 0.3702 | -0.0024 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=fast_lane` | 0.5150 | 0.5251 | 0.0101 | 0.8000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=rerank` | 0.4374 | 0.4322 | -0.0052 | 0.9529 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=fast_lane` | 0.4261 | 0.4309 | 0.0048 | 0.9683 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=rerank` | 0.4031 | 0.4007 | -0.0024 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=fast_lane` | 0.0893 | 0.0893 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=rerank` | 0.0858 | 0.0858 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=fast_lane` | 0.4462 | 0.4462 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=rerank` | 0.4288 | 0.4288 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_p50@0` | 0.4401 | 0.5499 | 0.1098 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_p95@0` | 0.4401 | 0.5499 | 0.1098 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_p99@0` | 0.4401 | 0.5499 | 0.1098 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|map@0` | 0.7472 | 0.7501 | 0.0029 | 0.9035 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|mrr@0` | 0.9523 | 0.9571 | 0.0048 | 0.7277 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|ndcg@10` | 0.8292 | 0.8316 | 0.0024 | 0.9035 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|precision@10` | 0.1750 | 0.1750 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|recall@10` | 0.8750 | 0.8750 | 0.0000 | 1.0000 | 400 | no_decision |

## Most affected queries

Candidate minus baseline for `hotpotqa_hybrid_dag|stage0|latency_p50@0|branch=dense_lane`.

| Query | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `5ab981555542996be2020532` | 156.8413 | 426.6918 | 269.8505 |
| `5adcceda5542990d50227d31` | 164.0082 | 370.8643 | 206.8561 |
| `5a7d61645542997cc2c47455` | 159.8543 | 350.4715 | 190.6172 |
| `5a7cef5d55429909bec768ac` | 123.2016 | 301.8080 | 178.6064 |
| `5ae0aefe554299603e418437` | 155.1072 | 332.9035 | 177.7963 |
| `5ac119335542992a796dede4` | 153.8376 | 331.2838 | 177.4462 |
| `5a7140585542994082a3e6fa` | 163.4423 | 337.8675 | 174.4253 |
| `5adf4a275542993a75d26498` | 187.5980 | 360.0614 | 172.4634 |
| `5ac1a3fa5542991316484b7d` | 172.3442 | 344.7189 | 172.3748 |
| `5ae54eea5542993aec5ec19d` | 131.1162 | 303.0871 | 171.9709 |
| `5a84c4135542994c784dda31` | 197.3437 | 366.9651 | 169.6214 |
| `5a75fa14554299109176e5dc` | 162.6930 | 330.1482 | 167.4553 |
| `5a877e5d5542993e715abf7d` | 184.6717 | 349.7903 | 165.1186 |
| `5ae47df15542996836b02cba` | 213.7847 | 377.4499 | 163.6651 |
| `5ab808ea5542991d3222380e` | 151.1242 | 306.0522 | 154.9280 |
| `5abba584554299642a094afa` | 167.3561 | 317.5379 | 150.1818 |
| `5abce9ca554299114383a193` | 155.0975 | 299.5227 | 144.4252 |
| `5ae1e9fd5542997f29b3c1a1` | 144.6853 | 289.0787 | 144.3934 |
| `5ab78edc5542995dae37e95c` | 219.9452 | 362.3187 | 142.3735 |
| `5abd94525542992ac4f382d2` | 194.0133 | 334.4083 | 140.3950 |
