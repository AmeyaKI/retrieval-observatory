# Run Comparison

**Verdict:** `BLOCK`  
**Validity:** `warning`  
**Baseline:** `0c9f6a25`  
**Candidate:** `4838eb6e`

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

- `5a7d7deb5542995f4f402282` — `#/runs/4838eb6e/queries/5a7d7deb5542995f4f402282/diff?against=0c9f6a25`
- `5a7b24fe55429931da12c9f7` — `#/runs/4838eb6e/queries/5a7b24fe55429931da12c9f7/diff?against=0c9f6a25`
- `5ae0968955429924de1b7105` — `#/runs/4838eb6e/queries/5ae0968955429924de1b7105/diff?against=0c9f6a25`
- `5a848b5c5542997175ce1ef2` — `#/runs/4838eb6e/queries/5a848b5c5542997175ce1ef2/diff?against=0c9f6a25`
- `5abcff225542993a06baf9ea` — `#/runs/4838eb6e/queries/5abcff225542993a06baf9ea/diff?against=0c9f6a25`
- `5a8f9c3f554299458435d69a` — `#/runs/4838eb6e/queries/5a8f9c3f554299458435d69a/diff?against=0c9f6a25`
- `5ab4314955429942dd415ecd` — `#/runs/4838eb6e/queries/5ab4314955429942dd415ecd/diff?against=0c9f6a25`
- `5ab9812d554299753720f821` — `#/runs/4838eb6e/queries/5ab9812d554299753720f821/diff?against=0c9f6a25`
- `5ae829ea5542997ec2727738` — `#/runs/4838eb6e/queries/5ae829ea5542997ec2727738/diff?against=0c9f6a25`
- `5adf076f5542992d7e9f9277` — `#/runs/4838eb6e/queries/5adf076f5542992d7e9f9277/diff?against=0c9f6a25`
- `5ae789615542997ec2727695` — `#/runs/4838eb6e/queries/5ae789615542997ec2727695/diff?against=0c9f6a25`
- `5a7a6c1a5542994f819ef1d5` — `#/runs/4838eb6e/queries/5a7a6c1a5542994f819ef1d5/diff?against=0c9f6a25`
- `5a7363ec5542991f29ee2dd7` — `#/runs/4838eb6e/queries/5a7363ec5542991f29ee2dd7/diff?against=0c9f6a25`
- `5aba943c554299232ef4a33e` — `#/runs/4838eb6e/queries/5aba943c554299232ef4a33e/diff?against=0c9f6a25`
- `5ab4f7fc5542991779162d43` — `#/runs/4838eb6e/queries/5ab4f7fc5542991779162d43/diff?against=0c9f6a25`
- `5abae3205542996cc5e49edc` — `#/runs/4838eb6e/queries/5abae3205542996cc5e49edc/diff?against=0c9f6a25`
- `5a852cd05542997b5ce3ffb0` — `#/runs/4838eb6e/queries/5a852cd05542997b5ce3ffb0/diff?against=0c9f6a25`
- `5a78ed6855429970f5fffdd9` — `#/runs/4838eb6e/queries/5a78ed6855429970f5fffdd9/diff?against=0c9f6a25`
- `5a8501915542997175ce1f5a` — `#/runs/4838eb6e/queries/5a8501915542997175ce1f5a/diff?against=0c9f6a25`
- `5a83eaae55429933447460b4` — `#/runs/4838eb6e/queries/5a83eaae55429933447460b4/diff?against=0c9f6a25`

## Next action

Resolve missing or invalid required evidence, then rerun the comparison.

## Reproduce and inspect

- `retobs compare 0c9f6a25 4838eb6e --db .retobs/demo.db --policy release-policy.yaml`
- Dashboard: http://127.0.0.1:4000/#/compare

## Provenance

- **Baseline:** run `0c9f6a25`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "baseline", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`
- **Candidate:** run `4838eb6e`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "candidate-stale-index", "embedding_model_revision": "sentence-transformers/all-MiniLM-L12-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`

## Validity evidence

- `git_commit`: Optional comparison metadata 'git_commit' is missing for at least one run.
- `git_dirty`: Optional comparison metadata 'git_dirty' is missing for at least one run.

## Paired results

| Metric | Baseline | Candidate | Effect | q-value | n | Decision |
|---|---:|---:|---:|---:|---:|---|
| `hotpotqa_hybrid_dag|stage-1|dropout_count@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_mean@0` | 840.6314 | 1283.7704 | 443.1391 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage-1|timeout_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=bm25_lane` | 14.3702 | 20.0123 | 5.6420 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=dense_lane` | 191.5777 | 343.4198 | 151.8420 | 0.0000 | 400 | candidate_worse |
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
| `hotpotqa_hybrid_dag|stage1|latency_mean@0` | 0.6875 | 1.3366 | 0.6491 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|map@0` | 0.6684 | 0.6216 | -0.0467 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|mrr@0` | 0.8778 | 0.8222 | -0.0556 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|ndcg@10` | 0.7583 | 0.7091 | -0.0492 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|precision@10` | 0.1682 | 0.1585 | -0.0097 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|recall@10` | 0.8413 | 0.7925 | -0.0488 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|latency_mean@0` | 0.7668 | 1.1239 | 0.3571 | 0.5680 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|map@0` | 0.6684 | 0.6216 | -0.0467 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|mrr@0` | 0.8778 | 0.8222 | -0.0556 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|ndcg@10` | 0.7583 | 0.7091 | -0.0492 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|precision@10` | 0.1682 | 0.1585 | -0.0097 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|recall@10` | 0.8413 | 0.7925 | -0.0488 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=bridge_hop2` | 157.5002 | 283.1518 | 125.6516 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=comparison_widen` | 43.2031 | 78.8056 | 35.6024 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=bridge_hop2` | 0.4964 | 0.4643 | -0.0320 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=comparison_widen` | 0.1723 | 0.1579 | -0.0145 | 0.0013 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=bridge_hop2` | 0.6706 | 0.6277 | -0.0428 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=comparison_widen` | 0.2072 | 0.1945 | -0.0127 | 0.0251 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=bridge_hop2` | 0.5701 | 0.5361 | -0.0340 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=comparison_widen` | 0.1881 | 0.1730 | -0.0151 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=bridge_hop2` | 0.1275 | 0.1212 | -0.0063 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=comparison_widen` | 0.0408 | 0.0372 | -0.0035 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=bridge_hop2` | 0.6375 | 0.6062 | -0.0312 | 0.0013 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=comparison_widen` | 0.2037 | 0.1862 | -0.0175 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|latency_mean@0` | 1.5936 | 1.9726 | 0.3790 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|map@0` | 0.4976 | 0.4657 | -0.0319 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|mrr@0` | 0.6706 | 0.6277 | -0.0428 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|ndcg@10` | 0.5701 | 0.5361 | -0.0340 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|precision@10` | 0.1275 | 0.1212 | -0.0063 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage4|recall@10` | 0.6375 | 0.6062 | -0.0312 | 0.0013 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|latency_mean@0` | 0.8919 | 0.9627 | 0.0708 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|map@0` | 0.6684 | 0.6216 | -0.0467 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|mrr@0` | 0.8778 | 0.8222 | -0.0556 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|ndcg@10` | 0.7583 | 0.7091 | -0.0492 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|precision@10` | 0.1682 | 0.1585 | -0.0097 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|recall@10` | 0.8413 | 0.7925 | -0.0488 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|latency_mean@0` | 0.8029 | 0.7878 | -0.0150 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|map@0` | 0.6684 | 0.6216 | -0.0467 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|mrr@0` | 0.8778 | 0.8222 | -0.0556 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|ndcg@10` | 0.7583 | 0.7091 | -0.0492 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|precision@10` | 0.1682 | 0.1585 | -0.0097 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|recall@10` | 0.8413 | 0.7925 | -0.0488 | 0.0000 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=fast_lane` | 0.3006 | 0.7065 | 0.4059 | 0.0471 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=rerank` | 417.8948 | 534.6035 | 116.7087 | 0.0207 | 400 | candidate_worse |
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
| `hotpotqa_hybrid_dag|stage8|latency_mean@0` | 0.2047 | 0.2746 | 0.0698 | 0.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|map@0` | 0.7472 | 0.7492 | 0.0020 | 0.8951 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|mrr@0` | 0.9523 | 0.9520 | -0.0003 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|ndcg@10` | 0.8292 | 0.8244 | -0.0048 | 0.4380 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|precision@10` | 0.1750 | 0.1707 | -0.0043 | 0.0013 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|recall@10` | 0.8750 | 0.8538 | -0.0212 | 0.0074 | 400 | candidate_worse |

## Most affected queries

Candidate minus baseline for `hotpotqa_hybrid_dag|stage-1|latency_mean@0`.

| Query | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `5a7d7deb5542995f4f402282` | 197.6235 | 8328.5682 | 8130.9448 |
| `5a7b24fe55429931da12c9f7` | 167.4888 | 8204.6210 | 8037.1322 |
| `5ae0968955429924de1b7105` | 133.2212 | 8039.7307 | 7906.5095 |
| `5a848b5c5542997175ce1ef2` | 8303.6425 | 1674.7939 | -6628.8487 |
| `5abcff225542993a06baf9ea` | 8223.6581 | 1631.0552 | -6592.6029 |
| `5a8f9c3f554299458435d69a` | 8029.6779 | 1637.3590 | -6392.3189 |
| `5ab4314955429942dd415ecd` | 94.9115 | 1641.8625 | 1546.9510 |
| `5ab9812d554299753720f821` | 521.8323 | 1835.9715 | 1314.1393 |
| `5ae829ea5542997ec2727738` | 421.8705 | 1720.0659 | 1298.1954 |
| `5adf076f5542992d7e9f9277` | 415.8154 | 1648.4145 | 1232.5991 |
| `5ae789615542997ec2727695` | 378.5158 | 1585.3361 | 1206.8203 |
| `5a7a6c1a5542994f819ef1d5` | 386.3763 | 1580.0181 | 1193.6418 |
| `5a7363ec5542991f29ee2dd7` | 443.3988 | 1628.6016 | 1185.2027 |
| `5aba943c554299232ef4a33e` | 390.0281 | 1561.9414 | 1171.9133 |
| `5ab4f7fc5542991779162d43` | 340.6075 | 1500.6358 | 1160.0284 |
| `5abae3205542996cc5e49edc` | 599.8516 | 1731.8896 | 1132.0380 |
| `5a852cd05542997b5ce3ffb0` | 379.1418 | 1482.4085 | 1103.2667 |
| `5a78ed6855429970f5fffdd9` | 377.2357 | 1472.2163 | 1094.9806 |
| `5a8501915542997175ce1f5a` | 348.1357 | 1434.9331 | 1086.7975 |
| `5a83eaae55429933447460b4` | 406.5861 | 1481.4865 | 1074.9004 |
