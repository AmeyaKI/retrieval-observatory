# Run Comparison

**Verdict:** `PASS`  
**Validity:** `warning`  
**Baseline:** `a1389d37`  
**Candidate:** `cb269926`

The recorded evidence proves non-inferiority for every declared policy guard.

## Release decision

Artifact schema: `1`  
**Status:** `PASS`  
**Policy:** `hotpotqa-flagship-demo`  
**Policy schema:** `2`  
**Policy digest:** `sha256:bd04cd6c200a334c090ae570a2350e1d1c0ccdadf9291e4d1cc6e8a8dcf954f6`

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

- `5ae2dd2055429928c423950d` — `#/runs/cb269926/queries/5ae2dd2055429928c423950d/diff?against=a1389d37`
- `5ae352285542994393b9e685` — `#/runs/cb269926/queries/5ae352285542994393b9e685/diff?against=a1389d37`
- `5ac1f4495542991316484bd2` — `#/runs/cb269926/queries/5ac1f4495542991316484bd2/diff?against=a1389d37`
- `5ab4475c5542996a3a969f6c` — `#/runs/cb269926/queries/5ab4475c5542996a3a969f6c/diff?against=a1389d37`
- `5a88e605554299206df2b39c` — `#/runs/cb269926/queries/5a88e605554299206df2b39c/diff?against=a1389d37`
- `5a7d7deb5542995f4f402282` — `#/runs/cb269926/queries/5a7d7deb5542995f4f402282/diff?against=a1389d37`
- `5a848b5c5542997175ce1ef2` — `#/runs/cb269926/queries/5a848b5c5542997175ce1ef2/diff?against=a1389d37`
- `5abd2eab5542992ac4f38210` — `#/runs/cb269926/queries/5abd2eab5542992ac4f38210/diff?against=a1389d37`
- `5ab4314955429942dd415ecd` — `#/runs/cb269926/queries/5ab4314955429942dd415ecd/diff?against=a1389d37`
- `5a7c6fde55429907fabeef87` — `#/runs/cb269926/queries/5a7c6fde55429907fabeef87/diff?against=a1389d37`
- `5ae0968955429924de1b7105` — `#/runs/cb269926/queries/5ae0968955429924de1b7105/diff?against=a1389d37`
- `5a8f9c3f554299458435d69a` — `#/runs/cb269926/queries/5a8f9c3f554299458435d69a/diff?against=a1389d37`
- `5ab2b666554299194fa934ca` — `#/runs/cb269926/queries/5ab2b666554299194fa934ca/diff?against=a1389d37`
- `5adfb60655429942ec259b08` — `#/runs/cb269926/queries/5adfb60655429942ec259b08/diff?against=a1389d37`
- `5ab7f97a5542991d322237ef` — `#/runs/cb269926/queries/5ab7f97a5542991d322237ef/diff?against=a1389d37`
- `5abcff225542993a06baf9ea` — `#/runs/cb269926/queries/5abcff225542993a06baf9ea/diff?against=a1389d37`
- `5a84e61b5542997b5ce3ff86` — `#/runs/cb269926/queries/5a84e61b5542997b5ce3ff86/diff?against=a1389d37`
- `5a7b24fe55429931da12c9f7` — `#/runs/cb269926/queries/5a7b24fe55429931da12c9f7/diff?against=a1389d37`
- `5a86399e5542994775f60733` — `#/runs/cb269926/queries/5a86399e5542994775f60733/diff?against=a1389d37`
- `5ae164685542997b2ef7d1cb` — `#/runs/cb269926/queries/5ae164685542997b2ef7d1cb/diff?against=a1389d37`

## Next action

Review the bounded evidence and proceed through the normal deployment approval process.

## Reproduce and inspect

- `retobs compare a1389d37 cb269926 --db .retobs/demo_fixed.db --policy release-policy.yaml`
- Dashboard: http://127.0.0.1:4000/#/compare

## Provenance

- **Baseline:** run `a1389d37`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "baseline", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`
- **Candidate:** run `cb269926`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "candidate-no-bm25", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`

## Validity evidence

- `git_commit`: Runs differ on optional comparison axis 'git_commit'.

## Paired results

| Metric | Baseline | Candidate | Effect | q-value | n | Decision |
|---|---:|---:|---:|---:|---:|---|
| `hotpotqa_hybrid_dag|stage-1|dropout_count@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure@0` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_mean@0` | 792.5806 | 880.0912 | 87.5105 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage-1|timeout@0` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|timeout_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=bm25_lane` | 14.2828 | 0.0132 | -14.2696 | 0.0023 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=dense_lane` | 216.1733 | 194.8344 | -21.3389 | 0.0023 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=bm25_lane` | 0.6069 | 0.0000 | -0.6069 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=dense_lane` | 0.6444 | 0.6444 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=bm25_lane` | 0.8279 | 0.0000 | -0.8279 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=dense_lane` | 0.8668 | 0.8668 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=bm25_lane` | 0.6991 | 0.0000 | -0.6991 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=dense_lane` | 0.7299 | 0.7299 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=bm25_lane` | 0.1552 | 0.0000 | -0.1552 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=dense_lane` | 0.1573 | 0.1573 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=bm25_lane` | 0.7762 | 0.0000 | -0.7762 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=dense_lane` | 0.7863 | 0.7863 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|latency_mean@0` | 0.6795 | 0.4678 | -0.2117 | 0.0023 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|map@0` | 0.6684 | 0.6444 | -0.0240 | 0.0289 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|mrr@0` | 0.8778 | 0.8668 | -0.0110 | 0.4498 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|ndcg@10` | 0.7583 | 0.7299 | -0.0284 | 0.0036 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|precision@10` | 0.1682 | 0.1573 | -0.0110 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|recall@10` | 0.8413 | 0.7863 | -0.0550 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|latency_mean@0` | 0.7666 | 0.4670 | -0.2997 | 0.0023 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|map@0` | 0.6684 | 0.6444 | -0.0240 | 0.0289 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|mrr@0` | 0.8778 | 0.8668 | -0.0110 | 0.4498 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|ndcg@10` | 0.7583 | 0.7299 | -0.0284 | 0.0036 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|precision@10` | 0.1682 | 0.1573 | -0.0110 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|recall@10` | 0.8413 | 0.7863 | -0.0550 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=bridge_hop2` | 229.7962 | 205.6964 | -24.0998 | 0.0023 | 312 | candidate_better |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=comparison_widen` | 233.6091 | 204.9683 | -28.6407 | 0.0071 | 88 | candidate_better |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=bridge_hop2` | 0.6364 | 0.5955 | -0.0409 | 0.0036 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=comparison_widen` | 0.7833 | 0.8210 | 0.0377 | 0.1122 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=bridge_hop2` | 0.8597 | 0.8424 | -0.0173 | 0.3171 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=comparison_widen` | 0.9418 | 0.9536 | 0.0118 | 0.6663 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=bridge_hop2` | 0.7309 | 0.6863 | -0.0446 | 0.0023 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=comparison_widen` | 0.8552 | 0.8844 | 0.0292 | 0.0731 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=bridge_hop2` | 0.1635 | 0.1484 | -0.0151 | 0.0023 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=comparison_widen` | 0.1852 | 0.1886 | 0.0034 | 0.2029 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=bridge_hop2` | 0.8173 | 0.7420 | -0.0753 | 0.0023 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=comparison_widen` | 0.9261 | 0.9432 | 0.0170 | 0.2029 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_mean@0` | 1.7310 | 1.5947 | -0.1363 | 0.0023 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|map@0` | 0.6380 | 0.6004 | -0.0376 | 0.0036 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|mrr@0` | 0.8597 | 0.8424 | -0.0173 | 0.3171 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|ndcg@10` | 0.7309 | 0.6863 | -0.0446 | 0.0023 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|precision@10` | 0.1635 | 0.1484 | -0.0151 | 0.0023 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|recall@10` | 0.8173 | 0.7420 | -0.0753 | 0.0023 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|latency_mean@0` | 0.6451 | 0.7528 | 0.1077 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|map@0` | 0.6684 | 0.6485 | -0.0198 | 0.0718 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|mrr@0` | 0.8778 | 0.8669 | -0.0109 | 0.4498 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|ndcg@10` | 0.7583 | 0.7299 | -0.0284 | 0.0036 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|precision@10` | 0.1682 | 0.1573 | -0.0110 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|recall@10` | 0.8413 | 0.7863 | -0.0550 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|latency_mean@0` | 0.7424 | 0.5408 | -0.2016 | 0.0423 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|map@0` | 0.6684 | 0.6485 | -0.0198 | 0.0718 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|mrr@0` | 0.8778 | 0.8669 | -0.0109 | 0.4498 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|ndcg@10` | 0.7583 | 0.7299 | -0.0284 | 0.0036 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|precision@10` | 0.1682 | 0.1573 | -0.0110 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|recall@10` | 0.8413 | 0.7863 | -0.0550 | 0.0023 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=fast_lane` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=rerank` | 660.8856 | 461.8102 | -199.0754 | 0.0023 | 187 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=fast_lane` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=rerank` | 0.7970 | 0.7689 | -0.0281 | 0.0138 | 187 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=fast_lane` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=rerank` | 0.9355 | 0.9190 | -0.0165 | 0.0731 | 187 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=fast_lane` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=rerank` | 0.8623 | 0.8375 | -0.0248 | 0.0202 | 187 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=fast_lane` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=rerank` | 0.1834 | 0.1781 | -0.0053 | 0.0689 | 187 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=fast_lane` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=rerank` | 0.9171 | 0.8904 | -0.0267 | 0.0689 | 187 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_mean@0` | 0.2069 | 0.1560 | -0.0510 | 0.0023 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|map@0` | 0.7472 | 0.7924 | 0.0452 | 0.0023 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage8|mrr@0` | 0.9523 | 0.9553 | 0.0030 | 0.7921 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|ndcg@10` | 0.8292 | 0.8607 | 0.0315 | 0.0023 | 400 | candidate_better |
| `hotpotqa_hybrid_dag|stage8|precision@10` | 0.1750 | 0.1810 | 0.0060 | 0.0036 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|recall@10` | 0.8750 | 0.9050 | 0.0300 | 0.0036 | 400 | candidate_better |

## Most affected queries

Candidate minus baseline for `hotpotqa_hybrid_dag|stage-1|latency_mean@0`.

| Query | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `5ae2dd2055429928c423950d` | 3074.5756 | 901.1317 | -2173.4439 |
| `5ae352285542994393b9e685` | 3030.7795 | 910.7210 | -2120.0585 |
| `5ac1f4495542991316484bd2` | 2818.1921 | 1123.1621 | -1695.0300 |
| `5ab4475c5542996a3a969f6c` | 3063.7375 | 1458.0469 | -1605.6906 |
| `5a88e605554299206df2b39c` | 2966.4317 | 1465.5838 | -1500.8479 |
| `5a7d7deb5542995f4f402282` | 203.5360 | 1615.7934 | 1412.2574 |
| `5a848b5c5542997175ce1ef2` | 2623.3077 | 1224.4724 | -1398.8354 |
| `5abd2eab5542992ac4f38210` | 204.1555 | 1334.4356 | 1130.2801 |
| `5ab4314955429942dd415ecd` | 202.3169 | 1306.2228 | 1103.9059 |
| `5a7c6fde55429907fabeef87` | 138.9727 | 1229.3345 | 1090.3618 |
| `5ae0968955429924de1b7105` | 129.4888 | 1218.1208 | 1088.6321 |
| `5a8f9c3f554299458435d69a` | 2289.5982 | 1397.4783 | -892.1198 |
| `5ab2b666554299194fa934ca` | 581.9643 | 1418.5564 | 836.5922 |
| `5adfb60655429942ec259b08` | 609.5005 | 1437.5555 | 828.0550 |
| `5ab7f97a5542991d322237ef` | 621.9993 | 1448.0877 | 826.0884 |
| `5abcff225542993a06baf9ea` | 2280.7008 | 1456.9337 | -823.7671 |
| `5a84e61b5542997b5ce3ff86` | 223.5685 | 978.3082 | 754.7398 |
| `5a7b24fe55429931da12c9f7` | 169.0113 | 916.5141 | 747.5027 |
| `5a86399e5542994775f60733` | 522.3352 | 1266.4930 | 744.1578 |
| `5ae164685542997b2ef7d1cb` | 1291.3043 | 562.0672 | -729.2371 |
