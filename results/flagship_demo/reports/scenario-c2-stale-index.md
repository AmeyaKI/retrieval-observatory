# Run Comparison

**Verdict:** `BLOCK`  
**Validity:** `warning`  
**Baseline:** `4b5be1ce`  
**Candidate:** `2e9cfddc`

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
| `hotpotqa_hybrid_dag|stage8|recall@10` | `HOLD` | -0.0212 | -0.0394 to -0.0025 | 400 | 0.9875 |

### Declared slices

- `type-bridge` (`type='bridge'`): `HOLD`, paired n=312, label coverage=1.0000
- `type-comparison` (`type='comparison'`): `HOLD`, paired n=88, label coverage=1.0000
- `level-hard` (`level='hard'`): `HOLD`, paired n=400, label coverage=1.0000

### Investigation references

- `5a7d7deb5542995f4f402282` — `#/runs/2e9cfddc/queries/5a7d7deb5542995f4f402282/diff?against=4b5be1ce`
- `5ae0968955429924de1b7105` — `#/runs/2e9cfddc/queries/5ae0968955429924de1b7105/diff?against=4b5be1ce`
- `5a7b24fe55429931da12c9f7` — `#/runs/2e9cfddc/queries/5a7b24fe55429931da12c9f7/diff?against=4b5be1ce`
- `5abcff225542993a06baf9ea` — `#/runs/2e9cfddc/queries/5abcff225542993a06baf9ea/diff?against=4b5be1ce`
- `5a8f9c3f554299458435d69a` — `#/runs/2e9cfddc/queries/5a8f9c3f554299458435d69a/diff?against=4b5be1ce`
- `5a848b5c5542997175ce1ef2` — `#/runs/2e9cfddc/queries/5a848b5c5542997175ce1ef2/diff?against=4b5be1ce`
- `5ae352285542994393b9e685` — `#/runs/2e9cfddc/queries/5ae352285542994393b9e685/diff?against=4b5be1ce`
- `5ab4314955429942dd415ecd` — `#/runs/2e9cfddc/queries/5ab4314955429942dd415ecd/diff?against=4b5be1ce`
- `5ab4475c5542996a3a969f6c` — `#/runs/2e9cfddc/queries/5ab4475c5542996a3a969f6c/diff?against=4b5be1ce`
- `5a88e605554299206df2b39c` — `#/runs/2e9cfddc/queries/5a88e605554299206df2b39c/diff?against=4b5be1ce`
- `5a7363ec5542991f29ee2dd7` — `#/runs/2e9cfddc/queries/5a7363ec5542991f29ee2dd7/diff?against=4b5be1ce`
- `5ab4f7fc5542991779162d43` — `#/runs/2e9cfddc/queries/5ab4f7fc5542991779162d43/diff?against=4b5be1ce`
- `5abf931f5542990832d3a158` — `#/runs/2e9cfddc/queries/5abf931f5542990832d3a158/diff?against=4b5be1ce`
- `5abae3205542996cc5e49edc` — `#/runs/2e9cfddc/queries/5abae3205542996cc5e49edc/diff?against=4b5be1ce`
- `5a83eaae55429933447460b4` — `#/runs/2e9cfddc/queries/5a83eaae55429933447460b4/diff?against=4b5be1ce`
- `5ae4c5595542990ba0bbb123` — `#/runs/2e9cfddc/queries/5ae4c5595542990ba0bbb123/diff?against=4b5be1ce`
- `5ab42ef55542991751b4d6d9` — `#/runs/2e9cfddc/queries/5ab42ef55542991751b4d6d9/diff?against=4b5be1ce`
- `5ae7edee554299540e5a56ad` — `#/runs/2e9cfddc/queries/5ae7edee554299540e5a56ad/diff?against=4b5be1ce`
- `5a85fa815542996432c57155` — `#/runs/2e9cfddc/queries/5a85fa815542996432c57155/diff?against=4b5be1ce`
- `5a87411d5542994846c1cd37` — `#/runs/2e9cfddc/queries/5a87411d5542994846c1cd37/diff?against=4b5be1ce`

## Next action

Resolve missing or invalid required evidence, then rerun the comparison.

## Reproduce and inspect

- `retobs compare 4b5be1ce 2e9cfddc --db /Users/ameyakiwalkar/Documents/retrieval-observatory/results/flagship_demo/.retobs/demo.db --policy /Users/ameyakiwalkar/Documents/retrieval-observatory/results/flagship_demo/release-policy.yaml`
- Dashboard: http://127.0.0.1:4000/#/compare

## Provenance

- **Baseline:** run `4b5be1ce`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "baseline", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`
- **Candidate:** run `2e9cfddc`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "candidate-stale-index", "embedding_model_revision": "sentence-transformers/all-MiniLM-L12-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`

## Validity evidence

- `git_commit`: Runs differ on optional comparison axis 'git_commit'.

## Paired results

| Metric | Baseline | Candidate | Effect | q-value | n | Decision |
|---|---:|---:|---:|---:|---:|---|
| `hotpotqa_hybrid_dag|stage-1|dropout_count@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_p50@0` | 854.0280 | 987.8827 | 133.8547 | 0.0046 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage-1|latency_p95@0` | 854.0280 | 987.8827 | 133.8547 | 0.0046 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage-1|latency_p99@0` | 854.0280 | 987.8827 | 133.8547 | 0.0046 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage-1|timeout_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_p50@0|branch=bm25_lane` | 14.3014 | 14.1507 | -0.1507 | 0.0624 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_p50@0|branch=dense_lane` | 188.2689 | 245.6596 | 57.3908 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|latency_p95@0|branch=bm25_lane` | 14.3014 | 14.1507 | -0.1507 | 0.0624 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_p95@0|branch=dense_lane` | 188.2689 | 245.6596 | 57.3908 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|latency_p99@0|branch=bm25_lane` | 14.3014 | 14.1507 | -0.1507 | 0.0624 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_p99@0|branch=dense_lane` | 188.2689 | 245.6596 | 57.3908 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=bm25_lane` | 0.6069 | 0.6069 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=dense_lane` | 0.6444 | 0.4723 | -0.1721 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=bm25_lane` | 0.8279 | 0.8279 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=dense_lane` | 0.8668 | 0.6974 | -0.1694 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=bm25_lane` | 0.6991 | 0.6991 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=dense_lane` | 0.7299 | 0.5558 | -0.1741 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=bm25_lane` | 0.1552 | 0.1552 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=dense_lane` | 0.1573 | 0.1225 | -0.0348 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=bm25_lane` | 0.7762 | 0.7762 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=dense_lane` | 0.7863 | 0.6125 | -0.1737 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|latency_p50@0` | 0.6954 | 0.6938 | -0.0016 | 0.9456 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_p95@0` | 0.6954 | 0.6938 | -0.0016 | 0.9456 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_p99@0` | 0.6954 | 0.6938 | -0.0016 | 0.9456 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|map@0` | 0.6684 | 0.6216 | -0.0467 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|mrr@0` | 0.8778 | 0.8222 | -0.0556 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|ndcg@10` | 0.7583 | 0.7091 | -0.0492 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|precision@10` | 0.1682 | 0.1585 | -0.0097 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|recall@10` | 0.8413 | 0.7925 | -0.0488 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|latency_p50@0` | 0.7931 | 0.8081 | 0.0150 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_p95@0` | 0.7931 | 0.8081 | 0.0150 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_p99@0` | 0.7931 | 0.8081 | 0.0150 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|map@0` | 0.6684 | 0.6216 | -0.0467 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|mrr@0` | 0.8778 | 0.8222 | -0.0556 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|ndcg@10` | 0.7583 | 0.7091 | -0.0492 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|precision@10` | 0.1682 | 0.1585 | -0.0097 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|recall@10` | 0.8413 | 0.7925 | -0.0488 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p50@0|branch=bridge_hop2` | 159.4351 | 207.1370 | 47.7019 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p50@0|branch=comparison_widen` | 45.0303 | 58.1302 | 13.0999 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p95@0|branch=bridge_hop2` | 159.4351 | 207.1370 | 47.7019 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p95@0|branch=comparison_widen` | 45.0303 | 58.1302 | 13.0999 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p99@0|branch=bridge_hop2` | 159.4351 | 207.1370 | 47.7019 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_p99@0|branch=comparison_widen` | 45.0303 | 58.1302 | 13.0999 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=bridge_hop2` | 0.4964 | 0.4643 | -0.0320 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=comparison_widen` | 0.1723 | 0.1579 | -0.0145 | 0.0016 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=bridge_hop2` | 0.6706 | 0.6277 | -0.0428 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=comparison_widen` | 0.2072 | 0.1945 | -0.0127 | 0.0310 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=bridge_hop2` | 0.5701 | 0.5361 | -0.0340 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=comparison_widen` | 0.1881 | 0.1730 | -0.0151 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=bridge_hop2` | 0.1275 | 0.1212 | -0.0063 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=comparison_widen` | 0.0408 | 0.0372 | -0.0035 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=bridge_hop2` | 0.6375 | 0.6062 | -0.0312 | 0.0016 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=comparison_widen` | 0.2037 | 0.1862 | -0.0175 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|latency_p50@0` | 1.7737 | 1.7405 | -0.0332 | 0.9988 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_p95@0` | 1.7737 | 1.7405 | -0.0332 | 0.9988 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_p99@0` | 1.7737 | 1.7405 | -0.0332 | 0.9988 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|map@0` | 0.4976 | 0.4657 | -0.0319 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|mrr@0` | 0.6706 | 0.6277 | -0.0428 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|ndcg@10` | 0.5701 | 0.5361 | -0.0340 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|precision@10` | 0.1275 | 0.1212 | -0.0063 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|recall@10` | 0.6375 | 0.6062 | -0.0312 | 0.0016 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|latency_p50@0` | 0.8838 | 0.6678 | -0.2160 | 0.8493 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_p95@0` | 0.8838 | 0.6678 | -0.2160 | 0.8493 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_p99@0` | 0.8838 | 0.6678 | -0.2160 | 0.8493 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|map@0` | 0.6684 | 0.6216 | -0.0467 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|mrr@0` | 0.8778 | 0.8222 | -0.0556 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|ndcg@10` | 0.7583 | 0.7091 | -0.0492 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|precision@10` | 0.1682 | 0.1585 | -0.0097 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|recall@10` | 0.8413 | 0.7925 | -0.0488 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|latency_p50@0` | 0.5596 | 0.5477 | -0.0119 | 0.0509 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_p95@0` | 0.5596 | 0.5477 | -0.0119 | 0.0509 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_p99@0` | 0.5596 | 0.5477 | -0.0119 | 0.0509 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|map@0` | 0.6684 | 0.6216 | -0.0467 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|mrr@0` | 0.8778 | 0.8222 | -0.0556 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|ndcg@10` | 0.7583 | 0.7091 | -0.0492 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|precision@10` | 0.1682 | 0.1585 | -0.0097 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|recall@10` | 0.8413 | 0.7925 | -0.0488 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|latency_p50@0|branch=fast_lane` | 0.3082 | 0.2366 | -0.0716 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p50@0|branch=rerank` | 426.9118 | 446.3192 | 19.4074 | 0.8493 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p95@0|branch=fast_lane` | 0.3082 | 0.2366 | -0.0716 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p95@0|branch=rerank` | 426.9118 | 446.3192 | 19.4074 | 0.8493 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p99@0|branch=fast_lane` | 0.3082 | 0.2366 | -0.0716 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_p99@0|branch=rerank` | 426.9118 | 446.3192 | 19.4074 | 0.8493 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=fast_lane` | 0.3809 | 0.3005 | -0.0804 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=rerank` | 0.3726 | 0.4530 | 0.0804 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=fast_lane` | 0.5150 | 0.4072 | -0.1078 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=rerank` | 0.4374 | 0.5449 | 0.1075 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=fast_lane` | 0.4261 | 0.3324 | -0.0937 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=rerank` | 0.4031 | 0.4921 | 0.0889 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=fast_lane` | 0.0893 | 0.0673 | -0.0220 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=rerank` | 0.0858 | 0.1035 | 0.0178 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=fast_lane` | 0.4462 | 0.3362 | -0.1100 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=rerank` | 0.4288 | 0.5175 | 0.0887 | 0.0000 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage8|latency_p50@0` | 0.4401 | 0.3881 | -0.0520 | 0.6429 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_p95@0` | 0.4401 | 0.3881 | -0.0520 | 0.6429 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_p99@0` | 0.4401 | 0.3881 | -0.0520 | 0.6429 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|map@0` | 0.7472 | 0.7492 | 0.0020 | 0.9393 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|mrr@0` | 0.9523 | 0.9520 | -0.0003 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|ndcg@10` | 0.8292 | 0.8244 | -0.0048 | 0.5057 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|precision@10` | 0.1750 | 0.1707 | -0.0043 | 0.0016 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|recall@10` | 0.8750 | 0.8538 | -0.0212 | 0.0090 | 400 | candidate_worse |

## Most affected queries

Candidate minus baseline for `hotpotqa_hybrid_dag|stage-1|latency_p50@0`.

| Query | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `5a7d7deb5542995f4f402282` | 165.6370 | 8625.1875 | 8459.5505 |
| `5ae0968955429924de1b7105` | 142.0720 | 8571.5022 | 8429.4301 |
| `5a7b24fe55429931da12c9f7` | 169.5503 | 8479.6613 | 8310.1110 |
| `5abcff225542993a06baf9ea` | 8469.1613 | 1154.6085 | -7314.5528 |
| `5a8f9c3f554299458435d69a` | 8406.8707 | 1123.4366 | -7283.4341 |
| `5a848b5c5542997175ce1ef2` | 8580.1573 | 1416.1236 | -7164.0337 |
| `5ae352285542994393b9e685` | 8284.7152 | 9592.1005 | 1307.3853 |
| `5ab4314955429942dd415ecd` | 94.1953 | 1121.5405 | 1027.3452 |
| `5ab4475c5542996a3a969f6c` | 8074.9089 | 9084.0835 | 1009.1747 |
| `5a88e605554299206df2b39c` | 8129.9334 | 9129.9587 | 1000.0253 |
| `5a7363ec5542991f29ee2dd7` | 452.0387 | 1338.9805 | 886.9418 |
| `5ab4f7fc5542991779162d43` | 366.1987 | 1213.1859 | 846.9871 |
| `5abf931f5542990832d3a158` | 377.9875 | 1163.6189 | 785.6315 |
| `5abae3205542996cc5e49edc` | 428.5604 | 1206.2120 | 777.6516 |
| `5a83eaae55429933447460b4` | 444.8393 | 1191.3519 | 746.5126 |
| `5ae4c5595542990ba0bbb123` | 350.2994 | 1091.7265 | 741.4272 |
| `5ab42ef55542991751b4d6d9` | 1278.0017 | 557.9958 | -720.0059 |
| `5ae7edee554299540e5a56ad` | 400.4716 | 1118.0602 | 717.5885 |
| `5a85fa815542996432c57155` | 421.5592 | 1138.0435 | 716.4843 |
| `5a87411d5542994846c1cd37` | 450.3755 | 1162.7112 | 712.3356 |
