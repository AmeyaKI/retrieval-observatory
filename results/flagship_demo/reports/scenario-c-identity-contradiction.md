# Run Comparison

**Verdict:** `BLOCK`  
**Validity:** `warning`  
**Baseline:** `a1389d37`  
**Candidate:** `53e6bc51`

Required promotion evidence is missing or invalid; metric deltas are not decision-bearing.

## Release decision

Artifact schema: `1`  
**Status:** `BLOCK`  
**Policy:** `hotpotqa-flagship-demo`  
**Policy schema:** `2`  
**Policy digest:** `sha256:bd04cd6c200a334c090ae570a2350e1d1c0ccdadf9291e4d1cc6e8a8dcf954f6`

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

- `5ab4475c5542996a3a969f6c` — `#/runs/53e6bc51/queries/5ab4475c5542996a3a969f6c/diff?against=a1389d37`
- `5ae352285542994393b9e685` — `#/runs/53e6bc51/queries/5ae352285542994393b9e685/diff?against=a1389d37`
- `5a77309d55429972597f1487` — `#/runs/53e6bc51/queries/5a77309d55429972597f1487/diff?against=a1389d37`
- `5a77a65b5542992a6e59df57` — `#/runs/53e6bc51/queries/5a77a65b5542992a6e59df57/diff?against=a1389d37`
- `5a7b3ec95542995eb53be8d3` — `#/runs/53e6bc51/queries/5a7b3ec95542995eb53be8d3/diff?against=a1389d37`
- `5a77897f55429949eeb29edc` — `#/runs/53e6bc51/queries/5a77897f55429949eeb29edc/diff?against=a1389d37`
- `5adda7585542997dc790700c` — `#/runs/53e6bc51/queries/5adda7585542997dc790700c/diff?against=a1389d37`
- `5a7ed2c655429930675135e5` — `#/runs/53e6bc51/queries/5a7ed2c655429930675135e5/diff?against=a1389d37`
- `5ab9379a554299753720f79d` — `#/runs/53e6bc51/queries/5ab9379a554299753720f79d/diff?against=a1389d37`
- `5a8457835542990548d0b28a` — `#/runs/53e6bc51/queries/5a8457835542990548d0b28a/diff?against=a1389d37`
- `5a80707e5542992bc0c4a70e` — `#/runs/53e6bc51/queries/5a80707e5542992bc0c4a70e/diff?against=a1389d37`
- `5a873ec75542996432c57244` — `#/runs/53e6bc51/queries/5a873ec75542996432c57244/diff?against=a1389d37`
- `5a8f799d55429918e830d22d` — `#/runs/53e6bc51/queries/5a8f799d55429918e830d22d/diff?against=a1389d37`
- `5ac1f4495542991316484bd2` — `#/runs/53e6bc51/queries/5ac1f4495542991316484bd2/diff?against=a1389d37`
- `5ab84f2c55429934fafe6d54` — `#/runs/53e6bc51/queries/5ab84f2c55429934fafe6d54/diff?against=a1389d37`
- `5a74f5155542993748c89750` — `#/runs/53e6bc51/queries/5a74f5155542993748c89750/diff?against=a1389d37`
- `5ae00a27554299025d62a3bb` — `#/runs/53e6bc51/queries/5ae00a27554299025d62a3bb/diff?against=a1389d37`
- `5a77d65055429949eeb29f7b` — `#/runs/53e6bc51/queries/5a77d65055429949eeb29f7b/diff?against=a1389d37`
- `5a7a6c1a5542994f819ef1d5` — `#/runs/53e6bc51/queries/5a7a6c1a5542994f819ef1d5/diff?against=a1389d37`
- `5ae528ed5542993aec5ec16e` — `#/runs/53e6bc51/queries/5ae528ed5542993aec5ec16e/diff?against=a1389d37`

## Next action

Resolve missing or invalid required evidence, then rerun the comparison.

## Reproduce and inspect

- `retobs compare a1389d37 53e6bc51 --db .retobs/demo_fixed.db --policy release-policy.yaml`
- Dashboard: http://127.0.0.1:4000/#/compare

## Provenance

- **Baseline:** run `a1389d37`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "baseline", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`
- **Candidate:** run `53e6bc51`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "candidate-swapped-embedding", "embedding_model_revision": "sentence-transformers/all-MiniLM-L12-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`

## Validity evidence

- `git_commit`: Runs differ on optional comparison axis 'git_commit'.

## Paired results

| Metric | Baseline | Candidate | Effect | q-value | n | Decision |
|---|---:|---:|---:|---:|---:|---|
| `hotpotqa_hybrid_dag|stage-1|dropout_count@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure@0` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_mean@0` | 792.5806 | 897.1431 | 104.5624 | 0.0107 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage-1|timeout@0` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|timeout_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=bm25_lane` | 14.2828 | 14.2308 | -0.0520 | 0.6119 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=dense_lane` | 216.1733 | 303.2571 | 87.0838 | 0.0107 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=bm25_lane` | 0.6069 | 0.6069 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=dense_lane` | 0.6444 | 0.6538 | 0.0094 | 0.4988 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=bm25_lane` | 0.8279 | 0.8279 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=dense_lane` | 0.8668 | 0.8789 | 0.0121 | 0.4914 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=bm25_lane` | 0.6991 | 0.6991 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=dense_lane` | 0.7299 | 0.7421 | 0.0122 | 0.3318 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=bm25_lane` | 0.1552 | 0.1552 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=dense_lane` | 0.1573 | 0.1600 | 0.0028 | 0.3844 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=bm25_lane` | 0.7762 | 0.7762 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=dense_lane` | 0.7863 | 0.8000 | 0.0138 | 0.3844 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_mean@0` | 0.6795 | 0.6798 | 0.0003 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|map@0` | 0.6684 | 0.6795 | 0.0111 | 0.2563 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|mrr@0` | 0.8778 | 0.8851 | 0.0073 | 0.5722 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|ndcg@10` | 0.7583 | 0.7677 | 0.0095 | 0.2563 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|precision@10` | 0.1682 | 0.1695 | 0.0013 | 0.5722 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|recall@10` | 0.8413 | 0.8475 | 0.0062 | 0.7097 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_mean@0` | 0.7666 | 1.0357 | 0.2691 | 0.8255 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|map@0` | 0.6684 | 0.6795 | 0.0111 | 0.2563 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|mrr@0` | 0.8778 | 0.8851 | 0.0073 | 0.5722 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|ndcg@10` | 0.7583 | 0.7677 | 0.0095 | 0.2563 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|precision@10` | 0.1682 | 0.1695 | 0.0013 | 0.5722 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|recall@10` | 0.8413 | 0.8475 | 0.0062 | 0.7097 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=bridge_hop2` | 229.7962 | 322.5941 | 92.7979 | 0.0107 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=comparison_widen` | 233.6091 | 312.9071 | 79.2980 | 0.0107 | 88 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=bridge_hop2` | 0.6364 | 0.6466 | 0.0102 | 0.4467 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=comparison_widen` | 0.7833 | 0.7982 | 0.0149 | 0.4914 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=bridge_hop2` | 0.8597 | 0.8716 | 0.0119 | 0.4914 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=comparison_widen` | 0.9418 | 0.9331 | -0.0086 | 0.5744 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=bridge_hop2` | 0.7309 | 0.7391 | 0.0081 | 0.4702 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=comparison_widen` | 0.8552 | 0.8693 | 0.0141 | 0.4376 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=bridge_hop2` | 0.1635 | 0.1635 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=comparison_widen` | 0.1852 | 0.1909 | 0.0057 | 0.4690 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=bridge_hop2` | 0.8173 | 0.8173 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=comparison_widen` | 0.9261 | 0.9545 | 0.0284 | 0.2563 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_mean@0` | 1.7310 | 1.9473 | 0.2163 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|map@0` | 0.6380 | 0.6483 | 0.0104 | 0.4376 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|mrr@0` | 0.8597 | 0.8716 | 0.0119 | 0.4914 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|ndcg@10` | 0.7309 | 0.7391 | 0.0081 | 0.4702 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|precision@10` | 0.1635 | 0.1635 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|recall@10` | 0.8173 | 0.8173 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_mean@0` | 0.6451 | 0.6488 | 0.0037 | 0.5851 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|map@0` | 0.6684 | 0.6795 | 0.0111 | 0.2563 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|mrr@0` | 0.8778 | 0.8851 | 0.0073 | 0.5722 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|ndcg@10` | 0.7583 | 0.7677 | 0.0095 | 0.2563 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|precision@10` | 0.1682 | 0.1695 | 0.0013 | 0.5722 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|recall@10` | 0.8413 | 0.8475 | 0.0062 | 0.7097 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_mean@0` | 0.7424 | 0.5466 | -0.1958 | 0.3109 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|map@0` | 0.6684 | 0.6795 | 0.0111 | 0.2563 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|mrr@0` | 0.8778 | 0.8851 | 0.0073 | 0.5722 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|ndcg@10` | 0.7583 | 0.7677 | 0.0095 | 0.2563 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|precision@10` | 0.1682 | 0.1695 | 0.0013 | 0.5722 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|recall@10` | 0.8413 | 0.8475 | 0.0062 | 0.7097 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=fast_lane` | 0.5627 | 0.5651 | 0.0024 | 0.8966 | 195 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=rerank` | 647.5216 | 529.2582 | -118.2634 | 0.0107 | 166 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=fast_lane` | 0.7189 | 0.7167 | -0.0022 | 0.8940 | 195 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=rerank` | 0.7974 | 0.8057 | 0.0083 | 0.2563 | 166 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=fast_lane` | 0.9791 | 0.9774 | -0.0017 | 0.4914 | 195 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=rerank` | 0.9374 | 0.9389 | 0.0015 | 0.0107 | 166 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=fast_lane` | 0.8030 | 0.8000 | -0.0031 | 0.8034 | 195 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=rerank` | 0.8617 | 0.8711 | 0.0094 | 0.2563 | 166 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=fast_lane` | 0.1667 | 0.1651 | -0.0015 | 0.8397 | 195 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=rerank` | 0.1825 | 0.1861 | 0.0036 | 0.2563 | 166 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=fast_lane` | 0.8333 | 0.8256 | -0.0077 | 0.5722 | 195 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=rerank` | 0.9127 | 0.9307 | 0.0181 | 0.0107 | 166 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_mean@0` | 0.2069 | 0.2101 | 0.0032 | 0.5851 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|map@0` | 0.7472 | 0.7501 | 0.0029 | 0.8255 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|mrr@0` | 0.9523 | 0.9571 | 0.0048 | 0.6422 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|ndcg@10` | 0.8292 | 0.8316 | 0.0024 | 0.8255 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|precision@10` | 0.1750 | 0.1750 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|recall@10` | 0.8750 | 0.8750 | 0.0000 | 1.0000 | 400 | no_decision |

## Most affected queries

Candidate minus baseline for `hotpotqa_hybrid_dag|stage-1|latency_mean@0`.

| Query | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `5ab4475c5542996a3a969f6c` | 3063.7375 | 933.0661 | -2130.6713 |
| `5ae352285542994393b9e685` | 3030.7795 | 921.7151 | -2109.0644 |
| `5a77309d55429972597f1487` | 461.6749 | 1237.2043 | 775.5295 |
| `5a77a65b5542992a6e59df57` | 531.3585 | 1296.5488 | 765.1903 |
| `5a7b3ec95542995eb53be8d3` | 420.6595 | 1106.3760 | 685.7165 |
| `5a77897f55429949eeb29edc` | 484.6303 | 1164.4308 | 679.8005 |
| `5adda7585542997dc790700c` | 442.4784 | 1099.8115 | 657.3332 |
| `5a7ed2c655429930675135e5` | 414.5082 | 1069.6158 | 655.1075 |
| `5ab9379a554299753720f79d` | 471.3868 | 1120.2678 | 648.8810 |
| `5a8457835542990548d0b28a` | 506.5657 | 1150.3482 | 643.7825 |
| `5a80707e5542992bc0c4a70e` | 496.7181 | 1137.5996 | 640.8815 |
| `5a873ec75542996432c57244` | 525.0676 | 1126.3915 | 601.3239 |
| `5a8f799d55429918e830d22d` | 1285.8140 | 685.4344 | -600.3795 |
| `5ac1f4495542991316484bd2` | 2818.1921 | 2227.8520 | -590.3401 |
| `5ab84f2c55429934fafe6d54` | 498.0902 | 1084.1648 | 586.0747 |
| `5a74f5155542993748c89750` | 358.5152 | 942.2369 | 583.7218 |
| `5ae00a27554299025d62a3bb` | 417.1378 | 994.1380 | 577.0002 |
| `5a77d65055429949eeb29f7b` | 1114.0858 | 538.1041 | -575.9818 |
| `5a7a6c1a5542994f819ef1d5` | 503.1148 | 1069.3970 | 566.2822 |
| `5ae528ed5542993aec5ec16e` | 475.4542 | 1021.4003 | 545.9461 |
