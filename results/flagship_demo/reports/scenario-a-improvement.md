# Run Comparison

**Verdict:** `PASS`  
**Validity:** `warning`  
**Baseline:** `a1389d37`  
**Candidate:** `0e39c15f`

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
| `hotpotqa_hybrid_dag|stage8|recall@10` | `PASS` | 0.0088 | 0.0019 to 0.0181 | 400 | 0.9875 |

### Declared slices

- `type-bridge` (`type='bridge'`): `PASS`, paired n=312, label coverage=1.0000
- `type-comparison` (`type='comparison'`): `PASS`, paired n=88, label coverage=1.0000
- `level-hard` (`level='hard'`): `PASS`, paired n=400, label coverage=1.0000

### Investigation references

- `5adccf645542990d50227d32` — `#/runs/0e39c15f/queries/5adccf645542990d50227d32/diff?against=a1389d37`
- `5a7cb94f554299683c1c6353` — `#/runs/0e39c15f/queries/5a7cb94f554299683c1c6353/diff?against=a1389d37`
- `5ae835f25542997ec272776f` — `#/runs/0e39c15f/queries/5ae835f25542997ec272776f/diff?against=a1389d37`
- `5a7140585542994082a3e6fa` — `#/runs/0e39c15f/queries/5a7140585542994082a3e6fa/diff?against=a1389d37`
- `5abde4595542991f66106095` — `#/runs/0e39c15f/queries/5abde4595542991f66106095/diff?against=a1389d37`
- `5ae08a0455429924de1b70fc` — `#/runs/0e39c15f/queries/5ae08a0455429924de1b70fc/diff?against=a1389d37`
- `5a72a9ab5542992359bc315a` — `#/runs/0e39c15f/queries/5a72a9ab5542992359bc315a/diff?against=a1389d37`
- `5ab2d3df554299194fa9352c` — `#/runs/0e39c15f/queries/5ab2d3df554299194fa9352c/diff?against=a1389d37`
- `5a75f0bf5542994ccc91866b` — `#/runs/0e39c15f/queries/5a75f0bf5542994ccc91866b/diff?against=a1389d37`
- `5ae6860e5542991bbc976112` — `#/runs/0e39c15f/queries/5ae6860e5542991bbc976112/diff?against=a1389d37`
- `5a7f697c5542992097ad2f59` — `#/runs/0e39c15f/queries/5a7f697c5542992097ad2f59/diff?against=a1389d37`
- `5a837d9a554299123d8c213e` — `#/runs/0e39c15f/queries/5a837d9a554299123d8c213e/diff?against=a1389d37`
- `5ab64285554299637185c67c` — `#/runs/0e39c15f/queries/5ab64285554299637185c67c/diff?against=a1389d37`
- `5a85ab905542994c784ddb35` — `#/runs/0e39c15f/queries/5a85ab905542994c784ddb35/diff?against=a1389d37`
- `5ae7ba7a5542993210983f12` — `#/runs/0e39c15f/queries/5ae7ba7a5542993210983f12/diff?against=a1389d37`
- `5adf4a275542993a75d26498` — `#/runs/0e39c15f/queries/5adf4a275542993a75d26498/diff?against=a1389d37`
- `5ab1d7ac554299449642c7e6` — `#/runs/0e39c15f/queries/5ab1d7ac554299449642c7e6/diff?against=a1389d37`
- `5a7cffb755429907fabef09f` — `#/runs/0e39c15f/queries/5a7cffb755429907fabef09f/diff?against=a1389d37`
- `5a7319e755429901807daf86` — `#/runs/0e39c15f/queries/5a7319e755429901807daf86/diff?against=a1389d37`
- `5a726b0f5542997f827839be` — `#/runs/0e39c15f/queries/5a726b0f5542997f827839be/diff?against=a1389d37`

## Next action

Review the bounded evidence and proceed through the normal deployment approval process.

## Reproduce and inspect

- `retobs compare a1389d37 0e39c15f --db .retobs/demo_fixed.db --policy release-policy.yaml`
- Dashboard: http://127.0.0.1:4000/#/compare

## Provenance

- **Baseline:** run `a1389d37`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "baseline", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`
- **Candidate:** run `0e39c15f`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "candidate-wider-merge", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`

## Validity evidence

- `git_commit`: Runs differ on optional comparison axis 'git_commit'.

## Paired results

| Metric | Baseline | Candidate | Effect | q-value | n | Decision |
|---|---:|---:|---:|---:|---:|---|
| `hotpotqa_hybrid_dag|stage-1|dropout_count@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure@0` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_mean@0` | 792.5806 | 925.0587 | 132.4781 | 0.0047 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage-1|timeout@0` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|timeout_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=bm25_lane` | 14.2828 | 14.4664 | 0.1836 | 0.0264 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=dense_lane` | 216.1733 | 245.7418 | 29.5685 | 0.0047 | 400 | candidate_worse |
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
| `hotpotqa_hybrid_dag|stage1|latency_mean@0` | 0.6795 | 0.7055 | 0.0260 | 0.0047 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|map@0` | 0.6684 | 0.6684 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|mrr@0` | 0.8778 | 0.8778 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|ndcg@10` | 0.7583 | 0.7583 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|precision@10` | 0.1682 | 0.1682 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|recall@10` | 0.8413 | 0.8413 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|latency_mean@0` | 0.7666 | 0.5775 | -0.1891 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|map@0` | 0.6684 | 0.6684 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|mrr@0` | 0.8778 | 0.8778 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|ndcg@10` | 0.7583 | 0.7583 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|precision@10` | 0.1682 | 0.1682 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|recall@10` | 0.8413 | 0.8413 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=bridge_hop2` | 229.7962 | 267.2211 | 37.4249 | 0.0047 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=comparison_widen` | 233.6091 | 266.1616 | 32.5525 | 0.0047 | 88 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=bridge_hop2` | 0.6364 | 0.6364 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=comparison_widen` | 0.7833 | 0.7833 | 0.0000 | 1.0000 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=bridge_hop2` | 0.8597 | 0.8597 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=comparison_widen` | 0.9418 | 0.9418 | 0.0000 | 1.0000 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=bridge_hop2` | 0.7309 | 0.7309 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=comparison_widen` | 0.8552 | 0.8552 | 0.0000 | 1.0000 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=bridge_hop2` | 0.1635 | 0.1635 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=comparison_widen` | 0.1852 | 0.1852 | 0.0000 | 1.0000 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=bridge_hop2` | 0.8173 | 0.8173 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=comparison_widen` | 0.9261 | 0.9261 | 0.0000 | 1.0000 | 88 | no_decision |
| `hotpotqa_hybrid_dag|stage4|latency_mean@0` | 1.7310 | 2.3858 | 0.6549 | 0.0047 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|map@0` | 0.6380 | 0.6380 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|mrr@0` | 0.8597 | 0.8597 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|ndcg@10` | 0.7309 | 0.7309 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|precision@10` | 0.1635 | 0.1635 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|recall@10` | 0.8173 | 0.8173 | 0.0000 | 1.0000 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage5|latency_mean@0` | 0.6451 | 1.0755 | 0.4304 | 0.0047 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|map@0` | 0.6684 | 0.6700 | 0.0016 | 0.0047 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|mrr@0` | 0.8778 | 0.8778 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|ndcg@10` | 0.7583 | 0.7583 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|precision@10` | 0.1682 | 0.1682 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|recall@10` | 0.8413 | 0.8413 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|latency_mean@0` | 0.7424 | 1.0986 | 0.3563 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|map@0` | 0.6684 | 0.6700 | 0.0016 | 0.0047 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|mrr@0` | 0.8778 | 0.8778 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|ndcg@10` | 0.7583 | 0.7583 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|precision@10` | 0.1682 | 0.1682 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|recall@10` | 0.8413 | 0.8413 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=fast_lane` | 0.5621 | 0.8649 | 0.3029 | 0.0047 | 213 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=rerank` | 660.8856 | 810.2953 | 149.4097 | 0.0047 | 187 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=fast_lane` | 0.7153 | 0.7171 | 0.0018 | 0.0047 | 213 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=rerank` | 0.7970 | 0.8030 | 0.0060 | 0.1336 | 187 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=fast_lane` | 0.9671 | 0.9671 | 0.0000 | 1.0000 | 213 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=rerank` | 0.9355 | 0.9329 | -0.0027 | 0.0047 | 187 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=fast_lane` | 0.8001 | 0.8001 | 0.0000 | 1.0000 | 213 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=rerank` | 0.8623 | 0.8699 | 0.0076 | 0.1158 | 187 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=fast_lane` | 0.1676 | 0.1676 | 0.0000 | 1.0000 | 213 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=rerank` | 0.1834 | 0.1872 | 0.0037 | 0.0710 | 187 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=fast_lane` | 0.8380 | 0.8380 | 0.0000 | 1.0000 | 213 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=rerank` | 0.9171 | 0.9358 | 0.0187 | 0.0710 | 187 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_mean@0` | 0.2069 | 0.2431 | 0.0361 | 0.0047 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|map@0` | 0.7472 | 0.7500 | 0.0028 | 0.0963 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|mrr@0` | 0.9523 | 0.9511 | -0.0012 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|ndcg@10` | 0.8292 | 0.8327 | 0.0035 | 0.0787 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|precision@10` | 0.1750 | 0.1768 | 0.0018 | 0.0047 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|recall@10` | 0.8750 | 0.8838 | 0.0088 | 0.0047 | 400 | no_decision |

## Most affected queries

Candidate minus baseline for `hotpotqa_hybrid_dag|stage-1|latency_mean@0`.

| Query | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `5adccf645542990d50227d32` | 943.0471 | 1729.1758 | 786.1287 |
| `5a7cb94f554299683c1c6353` | 985.4965 | 1726.6071 | 741.1106 |
| `5ae835f25542997ec272776f` | 1082.3951 | 1777.9166 | 695.5215 |
| `5a7140585542994082a3e6fa` | 958.2822 | 1635.4634 | 677.1811 |
| `5abde4595542991f66106095` | 1109.4489 | 1780.8957 | 671.4469 |
| `5ae08a0455429924de1b70fc` | 1116.8130 | 1775.9671 | 659.1541 |
| `5a72a9ab5542992359bc315a` | 990.1614 | 1596.8098 | 606.6485 |
| `5ab2d3df554299194fa9352c` | 943.8552 | 1545.9020 | 602.0468 |
| `5a75f0bf5542994ccc91866b` | 869.0595 | 1460.1952 | 591.1358 |
| `5ae6860e5542991bbc976112` | 1213.6141 | 1783.9425 | 570.3284 |
| `5a7f697c5542992097ad2f59` | 957.7865 | 1475.1037 | 517.3172 |
| `5a837d9a554299123d8c213e` | 1139.8838 | 1655.9763 | 516.0925 |
| `5ab64285554299637185c67c` | 1100.6693 | 1607.5663 | 506.8970 |
| `5a85ab905542994c784ddb35` | 1141.3293 | 1646.7967 | 505.4673 |
| `5ae7ba7a5542993210983f12` | 1060.0840 | 1561.9203 | 501.8362 |
| `5adf4a275542993a75d26498` | 1183.9449 | 1684.2205 | 500.2756 |
| `5ab1d7ac554299449642c7e6` | 858.8756 | 1357.4109 | 498.5353 |
| `5a7cffb755429907fabef09f` | 861.2561 | 1356.3419 | 495.0858 |
| `5a7319e755429901807daf86` | 928.1869 | 1422.6548 | 494.4679 |
| `5a726b0f5542997f827839be` | 1100.0552 | 1594.0700 | 494.0148 |
