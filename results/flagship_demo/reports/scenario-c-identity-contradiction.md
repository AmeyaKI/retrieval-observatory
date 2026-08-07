# Run Comparison

**Verdict:** `BLOCK`  
**Validity:** `warning`  
**Baseline:** `0c9f6a25`  
**Candidate:** `bfa6b953`

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

- `5ae352285542994393b9e685` — `#/runs/bfa6b953/queries/5ae352285542994393b9e685/diff?against=0c9f6a25`
- `5ab4475c5542996a3a969f6c` — `#/runs/bfa6b953/queries/5ab4475c5542996a3a969f6c/diff?against=0c9f6a25`
- `5a7a33205542996a35c1712f` — `#/runs/bfa6b953/queries/5a7a33205542996a35c1712f/diff?against=0c9f6a25`
- `5a78db8055429970f5fffdb2` — `#/runs/bfa6b953/queries/5a78db8055429970f5fffdb2/diff?against=0c9f6a25`
- `5a8f38fa55429924144829f5` — `#/runs/bfa6b953/queries/5a8f38fa55429924144829f5/diff?against=0c9f6a25`
- `5a7ed2c655429930675135e5` — `#/runs/bfa6b953/queries/5a7ed2c655429930675135e5/diff?against=0c9f6a25`
- `5ae528ed5542993aec5ec16e` — `#/runs/bfa6b953/queries/5ae528ed5542993aec5ec16e/diff?against=0c9f6a25`
- `5a77a65b5542992a6e59df57` — `#/runs/bfa6b953/queries/5a77a65b5542992a6e59df57/diff?against=0c9f6a25`
- `5a8457835542990548d0b28a` — `#/runs/bfa6b953/queries/5a8457835542990548d0b28a/diff?against=0c9f6a25`
- `5a7634f155429976ec32bd6b` — `#/runs/bfa6b953/queries/5a7634f155429976ec32bd6b/diff?against=0c9f6a25`
- `5a848b5c5542997175ce1ef2` — `#/runs/bfa6b953/queries/5a848b5c5542997175ce1ef2/diff?against=0c9f6a25`
- `5a80707e5542992bc0c4a70e` — `#/runs/bfa6b953/queries/5a80707e5542992bc0c4a70e/diff?against=0c9f6a25`
- `5ae00a27554299025d62a3bb` — `#/runs/bfa6b953/queries/5ae00a27554299025d62a3bb/diff?against=0c9f6a25`
- `5ab9379a554299753720f79d` — `#/runs/bfa6b953/queries/5ab9379a554299753720f79d/diff?against=0c9f6a25`
- `5a77309d55429972597f1487` — `#/runs/bfa6b953/queries/5a77309d55429972597f1487/diff?against=0c9f6a25`
- `5ab84f2c55429934fafe6d54` — `#/runs/bfa6b953/queries/5ab84f2c55429934fafe6d54/diff?against=0c9f6a25`
- `5a7cf29255429909bec768b8` — `#/runs/bfa6b953/queries/5a7cf29255429909bec768b8/diff?against=0c9f6a25`
- `5a7b3ec95542995eb53be8d3` — `#/runs/bfa6b953/queries/5a7b3ec95542995eb53be8d3/diff?against=0c9f6a25`
- `5a77897f55429949eeb29edc` — `#/runs/bfa6b953/queries/5a77897f55429949eeb29edc/diff?against=0c9f6a25`
- `5a74f5155542993748c89750` — `#/runs/bfa6b953/queries/5a74f5155542993748c89750/diff?against=0c9f6a25`

## Next action

Resolve missing or invalid required evidence, then rerun the comparison.

## Reproduce and inspect

- `retobs compare 0c9f6a25 bfa6b953 --db .retobs/demo.db --policy release-policy.yaml`
- Dashboard: http://127.0.0.1:4000/#/compare

## Provenance

- **Baseline:** run `0c9f6a25`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "baseline", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`
- **Candidate:** run `bfa6b953`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "candidate-swapped-embedding", "embedding_model_revision": "sentence-transformers/all-MiniLM-L12-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`

## Validity evidence

- `git_commit`: Optional comparison metadata 'git_commit' is missing for at least one run.
- `git_dirty`: Optional comparison metadata 'git_dirty' is missing for at least one run.

## Paired results

| Metric | Baseline | Candidate | Effect | q-value | n | Decision |
|---|---:|---:|---:|---:|---:|---|
| `hotpotqa_hybrid_dag|stage-1|dropout_count@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_mean@0` | 840.6314 | 994.2895 | 153.6581 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage-1|timeout_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=bm25_lane` | 14.3702 | 16.4965 | 2.1263 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=dense_lane` | 191.5777 | 262.9190 | 71.3412 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=bm25_lane` | 0.6069 | 0.6069 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=dense_lane` | 0.6444 | 0.6538 | 0.0094 | 0.5510 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=bm25_lane` | 0.8279 | 0.8279 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=dense_lane` | 0.8668 | 0.8789 | 0.0121 | 0.5462 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=bm25_lane` | 0.6991 | 0.6991 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=dense_lane` | 0.7299 | 0.7421 | 0.0122 | 0.3535 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=bm25_lane` | 0.1552 | 0.1552 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=dense_lane` | 0.1573 | 0.1600 | 0.0028 | 0.3741 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=bm25_lane` | 0.7762 | 0.7762 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=dense_lane` | 0.7863 | 0.8000 | 0.0138 | 0.3741 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_mean@0` | 0.6875 | 1.0541 | 0.3666 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|map@0` | 0.6684 | 0.6795 | 0.0111 | 0.2596 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|mrr@0` | 0.8778 | 0.8851 | 0.0073 | 0.6271 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|ndcg@10` | 0.7583 | 0.7677 | 0.0095 | 0.2596 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|precision@10` | 0.1682 | 0.1695 | 0.0013 | 0.6271 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|recall@10` | 0.8413 | 0.8475 | 0.0062 | 0.7951 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_mean@0` | 0.7668 | 0.6500 | -0.1168 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|map@0` | 0.6684 | 0.6795 | 0.0111 | 0.2596 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|mrr@0` | 0.8778 | 0.8851 | 0.0073 | 0.6271 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|ndcg@10` | 0.7583 | 0.7677 | 0.0095 | 0.2596 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|precision@10` | 0.1682 | 0.1695 | 0.0013 | 0.6271 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|recall@10` | 0.8413 | 0.8475 | 0.0062 | 0.7951 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=bridge_hop2` | 157.5002 | 233.3921 | 75.8919 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=comparison_widen` | 43.2031 | 62.2767 | 19.0736 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=bridge_hop2` | 0.4964 | 0.5043 | 0.0079 | 0.3741 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=comparison_widen` | 0.1723 | 0.1756 | 0.0033 | 0.5510 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=bridge_hop2` | 0.6706 | 0.6798 | 0.0092 | 0.5371 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=comparison_widen` | 0.2072 | 0.2053 | -0.0019 | 0.7460 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=bridge_hop2` | 0.5701 | 0.5765 | 0.0063 | 0.5054 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=comparison_widen` | 0.1881 | 0.1912 | 0.0031 | 0.3741 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=bridge_hop2` | 0.1275 | 0.1275 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=comparison_widen` | 0.0408 | 0.0420 | 0.0013 | 0.2596 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=bridge_hop2` | 0.6375 | 0.6375 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=comparison_widen` | 0.2037 | 0.2100 | 0.0063 | 0.2596 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_mean@0` | 1.5936 | 1.5621 | -0.0315 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|map@0` | 0.4976 | 0.5057 | 0.0081 | 0.3741 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|mrr@0` | 0.6706 | 0.6798 | 0.0092 | 0.5371 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|ndcg@10` | 0.5701 | 0.5765 | 0.0063 | 0.5054 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|precision@10` | 0.1275 | 0.1275 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|recall@10` | 0.6375 | 0.6375 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_mean@0` | 0.8919 | 0.7683 | -0.1236 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|map@0` | 0.6684 | 0.6795 | 0.0111 | 0.2596 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|mrr@0` | 0.8778 | 0.8851 | 0.0073 | 0.6271 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|ndcg@10` | 0.7583 | 0.7677 | 0.0095 | 0.2596 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|precision@10` | 0.1682 | 0.1695 | 0.0013 | 0.6271 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|recall@10` | 0.8413 | 0.8475 | 0.0062 | 0.7951 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_mean@0` | 0.8029 | 0.6357 | -0.1672 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|map@0` | 0.6684 | 0.6795 | 0.0111 | 0.2596 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|mrr@0` | 0.8778 | 0.8851 | 0.0073 | 0.6271 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|ndcg@10` | 0.7583 | 0.7677 | 0.0095 | 0.2596 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|precision@10` | 0.1682 | 0.1695 | 0.0013 | 0.6271 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|recall@10` | 0.8413 | 0.8475 | 0.0062 | 0.7951 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=fast_lane` | 0.3006 | 0.3502 | 0.0495 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=rerank` | 417.8948 | 394.9929 | -22.9020 | 0.9338 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=fast_lane` | 0.3809 | 0.3863 | 0.0054 | 0.9373 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=rerank` | 0.3726 | 0.3702 | -0.0024 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=fast_lane` | 0.5150 | 0.5251 | 0.0101 | 0.7951 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=rerank` | 0.4374 | 0.4322 | -0.0052 | 0.9919 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=fast_lane` | 0.4261 | 0.4309 | 0.0048 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=rerank` | 0.4031 | 0.4007 | -0.0024 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=fast_lane` | 0.0893 | 0.0893 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=rerank` | 0.0858 | 0.0858 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=fast_lane` | 0.4462 | 0.4462 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=rerank` | 0.4288 | 0.4288 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_mean@0` | 0.2047 | 0.2409 | 0.0361 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|map@0` | 0.7472 | 0.7501 | 0.0029 | 0.9338 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|mrr@0` | 0.9523 | 0.9571 | 0.0048 | 0.7460 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|ndcg@10` | 0.8292 | 0.8316 | 0.0024 | 0.9341 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|precision@10` | 0.1750 | 0.1750 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|recall@10` | 0.8750 | 0.8750 | 0.0000 | 1.0000 | 400 | no_decision |

## Most affected queries

Candidate minus baseline for `hotpotqa_hybrid_dag|stage-1|latency_mean@0`.

| Query | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `5ae352285542994393b9e685` | 8419.3203 | 637.2164 | -7782.1039 |
| `5ab4475c5542996a3a969f6c` | 8270.4845 | 594.8610 | -7675.6235 |
| `5a7a33205542996a35c1712f` | 1174.9228 | 8488.5956 | 7313.6727 |
| `5a78db8055429970f5fffdb2` | 1109.1233 | 8300.6650 | 7191.5417 |
| `5a8f38fa55429924144829f5` | 435.9396 | 1364.8717 | 928.9321 |
| `5a7ed2c655429930675135e5` | 432.2333 | 1267.1755 | 834.9423 |
| `5ae528ed5542993aec5ec16e` | 403.7371 | 1235.8955 | 832.1584 |
| `5a77a65b5542992a6e59df57` | 378.5055 | 1171.6434 | 793.1379 |
| `5a8457835542990548d0b28a` | 457.6354 | 1249.5281 | 791.8927 |
| `5a7634f155429976ec32bd6b` | 475.8395 | 1240.8240 | 764.9845 |
| `5a848b5c5542997175ce1ef2` | 8303.6425 | 7576.7318 | -726.9107 |
| `5a80707e5542992bc0c4a70e` | 461.6098 | 1187.2455 | 725.6357 |
| `5ae00a27554299025d62a3bb` | 395.2037 | 1118.2603 | 723.0566 |
| `5ab9379a554299753720f79d` | 398.6121 | 1115.3777 | 716.7655 |
| `5a77309d55429972597f1487` | 435.0772 | 1148.2560 | 713.1788 |
| `5ab84f2c55429934fafe6d54` | 500.0340 | 1211.6737 | 711.6397 |
| `5a7cf29255429909bec768b8` | 399.2303 | 1085.5023 | 686.2720 |
| `5a7b3ec95542995eb53be8d3` | 398.6855 | 1053.8557 | 655.1701 |
| `5a77897f55429949eeb29edc` | 345.4380 | 997.1464 | 651.7084 |
| `5a74f5155542993748c89750` | 384.7520 | 1022.8634 | 638.1113 |
