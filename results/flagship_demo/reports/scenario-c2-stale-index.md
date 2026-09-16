# Run Comparison

**Verdict:** `BLOCK`  
**Validity:** `warning`  
**Baseline:** `a1389d37`  
**Candidate:** `58d239bb`

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
| `hotpotqa_hybrid_dag|stage8|recall@10` | `HOLD` | -0.0212 | -0.0394 to -0.0025 | 400 | 0.9875 |

### Declared slices

- `type-bridge` (`type='bridge'`): `HOLD`, paired n=312, label coverage=1.0000
- `type-comparison` (`type='comparison'`): `HOLD`, paired n=88, label coverage=1.0000
- `level-hard` (`level='hard'`): `HOLD`, paired n=400, label coverage=1.0000

### Investigation references

- `5a7b24fe55429931da12c9f7` — `#/runs/58d239bb/queries/5a7b24fe55429931da12c9f7/diff?against=a1389d37`
- `5a7d7deb5542995f4f402282` — `#/runs/58d239bb/queries/5a7d7deb5542995f4f402282/diff?against=a1389d37`
- `5ae0968955429924de1b7105` — `#/runs/58d239bb/queries/5ae0968955429924de1b7105/diff?against=a1389d37`
- `5ab4314955429942dd415ecd` — `#/runs/58d239bb/queries/5ab4314955429942dd415ecd/diff?against=a1389d37`
- `5a848b5c5542997175ce1ef2` — `#/runs/58d239bb/queries/5a848b5c5542997175ce1ef2/diff?against=a1389d37`
- `5ab5ecd75542992aa134a3e6` — `#/runs/58d239bb/queries/5ab5ecd75542992aa134a3e6/diff?against=a1389d37`
- `5ae789615542997ec2727695` — `#/runs/58d239bb/queries/5ae789615542997ec2727695/diff?against=a1389d37`
- `5a8f9c3f554299458435d69a` — `#/runs/58d239bb/queries/5a8f9c3f554299458435d69a/diff?against=a1389d37`
- `5a8457835542990548d0b28a` — `#/runs/58d239bb/queries/5a8457835542990548d0b28a/diff?against=a1389d37`
- `5abcff225542993a06baf9ea` — `#/runs/58d239bb/queries/5abcff225542993a06baf9ea/diff?against=a1389d37`
- `5a873ec75542996432c57244` — `#/runs/58d239bb/queries/5a873ec75542996432c57244/diff?against=a1389d37`
- `5a859a755542992a431d1b6d` — `#/runs/58d239bb/queries/5a859a755542992a431d1b6d/diff?against=a1389d37`
- `5abf931f5542990832d3a158` — `#/runs/58d239bb/queries/5abf931f5542990832d3a158/diff?against=a1389d37`
- `5a83eaae55429933447460b4` — `#/runs/58d239bb/queries/5a83eaae55429933447460b4/diff?against=a1389d37`
- `5ae5e62455429929b0807a07` — `#/runs/58d239bb/queries/5ae5e62455429929b0807a07/diff?against=a1389d37`
- `5a7c6fde55429907fabeef87` — `#/runs/58d239bb/queries/5a7c6fde55429907fabeef87/diff?against=a1389d37`
- `5ae4c5595542990ba0bbb123` — `#/runs/58d239bb/queries/5ae4c5595542990ba0bbb123/diff?against=a1389d37`
- `5a85fa815542996432c57155` — `#/runs/58d239bb/queries/5a85fa815542996432c57155/diff?against=a1389d37`
- `5ac1b8ee5542994d76dccedc` — `#/runs/58d239bb/queries/5ac1b8ee5542994d76dccedc/diff?against=a1389d37`
- `5a87411d5542994846c1cd37` — `#/runs/58d239bb/queries/5a87411d5542994846c1cd37/diff?against=a1389d37`

## Next action

Resolve missing or invalid required evidence, then rerun the comparison.

## Reproduce and inspect

- `retobs compare a1389d37 58d239bb --db .retobs/demo_fixed.db --policy release-policy.yaml`
- Dashboard: http://127.0.0.1:4000/#/compare

## Provenance

- **Baseline:** run `a1389d37`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "baseline", "embedding_model_revision": "sentence-transformers/all-MiniLM-L6-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`
- **Candidate:** run `58d239bb`, manifest schema `3`, release identity `{"chunking_revision": "title-prefixed-paragraph-v1", "corpus_revision": "sha256:59dfe0f6d7a564413d2f0269bd5a5e39403434cbcb8a05acc9d0a2a582e707ca", "deployment_revision": "candidate-stale-index", "embedding_model_revision": "sentence-transformers/all-MiniLM-L12-v2", "index_build_id": "faiss-flatip-7f2133a73273", "reranker_model_revision": "cross-encoder/ms-marco-MiniLM-L-6-v2", "service_id": "retobs-flagship-demo"}`

## Validity evidence

- `git_commit`: Runs differ on optional comparison axis 'git_commit'.

## Paired results

| Metric | Baseline | Candidate | Effect | q-value | n | Decision |
|---|---:|---:|---:|---:|---:|---|
| `hotpotqa_hybrid_dag|stage-1|dropout_count@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure@0` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|failure_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|latency_mean@0` | 792.5806 | 993.5505 | 200.9699 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage-1|timeout@0` | 0.0000 | 0.0000 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage-1|timeout_rate@0` | unavailable | unavailable | unavailable | unavailable | 0 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=bm25_lane` | 14.2828 | 14.5974 | 0.3146 | 0.0018 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|latency_mean@0|branch=dense_lane` | 216.1733 | 317.3241 | 101.1508 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=bm25_lane` | 0.6069 | 0.6069 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|map@0|branch=dense_lane` | 0.6444 | 0.4723 | -0.1721 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=bm25_lane` | 0.8279 | 0.8279 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|mrr@0|branch=dense_lane` | 0.8668 | 0.6974 | -0.1694 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=bm25_lane` | 0.6991 | 0.6991 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|ndcg@10|branch=dense_lane` | 0.7299 | 0.5558 | -0.1741 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=bm25_lane` | 0.1552 | 0.1552 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|precision@10|branch=dense_lane` | 0.1573 | 0.1225 | -0.0348 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=bm25_lane` | 0.7762 | 0.7762 | 0.0000 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage0|recall@10|branch=dense_lane` | 0.7863 | 0.6125 | -0.1737 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|latency_mean@0` | 0.6795 | 0.7000 | 0.0205 | 0.0018 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|map@0` | 0.6684 | 0.6216 | -0.0467 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|mrr@0` | 0.8778 | 0.8222 | -0.0556 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|ndcg@10` | 0.7583 | 0.7091 | -0.0492 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage1|precision@10` | 0.1682 | 0.1585 | -0.0097 | 0.0018 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage1|recall@10` | 0.8413 | 0.7925 | -0.0488 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|latency_mean@0` | 0.7666 | 0.8814 | 0.1148 | 0.6065 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|map@0` | 0.6684 | 0.6216 | -0.0467 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|mrr@0` | 0.8778 | 0.8222 | -0.0556 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|ndcg@10` | 0.7583 | 0.7091 | -0.0492 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage2|precision@10` | 0.1682 | 0.1585 | -0.0097 | 0.0018 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage2|recall@10` | 0.8413 | 0.7925 | -0.0488 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=bridge_hop2` | 229.7962 | 333.0922 | 103.2960 | 0.0018 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|latency_mean@0|branch=comparison_widen` | 233.6091 | 330.6675 | 97.0584 | 0.0018 | 88 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=bridge_hop2` | 0.6364 | 0.5953 | -0.0411 | 0.0018 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|map@0|branch=comparison_widen` | 0.7833 | 0.7175 | -0.0658 | 0.0045 | 88 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=bridge_hop2` | 0.8597 | 0.8048 | -0.0549 | 0.0018 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|mrr@0|branch=comparison_widen` | 0.9418 | 0.8840 | -0.0577 | 0.0389 | 88 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=bridge_hop2` | 0.7309 | 0.6873 | -0.0436 | 0.0018 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|ndcg@10|branch=comparison_widen` | 0.8552 | 0.7863 | -0.0688 | 0.0018 | 88 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=bridge_hop2` | 0.1635 | 0.1554 | -0.0080 | 0.0031 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage3|precision@10|branch=comparison_widen` | 0.1852 | 0.1693 | -0.0159 | 0.0031 | 88 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=bridge_hop2` | 0.8173 | 0.7772 | -0.0401 | 0.0031 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage3|recall@10|branch=comparison_widen` | 0.9261 | 0.8466 | -0.0795 | 0.0031 | 88 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|latency_mean@0` | 1.7310 | 1.8412 | 0.1102 | 0.0018 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|map@0` | 0.6380 | 0.5971 | -0.0409 | 0.0018 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|mrr@0` | 0.8597 | 0.8048 | -0.0549 | 0.0018 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|ndcg@10` | 0.7309 | 0.6873 | -0.0436 | 0.0018 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage4|precision@10` | 0.1635 | 0.1554 | -0.0080 | 0.0031 | 312 | no_decision |
| `hotpotqa_hybrid_dag|stage4|recall@10` | 0.8173 | 0.7772 | -0.0401 | 0.0031 | 312 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|latency_mean@0` | 0.6451 | 0.6811 | 0.0360 | 0.0018 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|map@0` | 0.6684 | 0.6216 | -0.0467 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|mrr@0` | 0.8778 | 0.8222 | -0.0556 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|ndcg@10` | 0.7583 | 0.7091 | -0.0492 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage5|precision@10` | 0.1682 | 0.1585 | -0.0097 | 0.0018 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage5|recall@10` | 0.8413 | 0.7925 | -0.0488 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|latency_mean@0` | 0.7424 | 0.5694 | -0.1730 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|map@0` | 0.6684 | 0.6216 | -0.0467 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|mrr@0` | 0.8778 | 0.8222 | -0.0556 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|ndcg@10` | 0.7583 | 0.7091 | -0.0492 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage6|precision@10` | 0.1682 | 0.1585 | -0.0097 | 0.0018 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage6|recall@10` | 0.8413 | 0.7925 | -0.0488 | 0.0018 | 400 | candidate_worse |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=fast_lane` | 0.5604 | 0.5745 | 0.0141 | 0.0682 | 143 | no_decision |
| `hotpotqa_hybrid_dag|stage7|latency_mean@0|branch=rerank` | 671.7836 | 526.4241 | -145.3594 | 0.0018 | 164 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=fast_lane` | 0.7387 | 0.7261 | -0.0126 | 0.2223 | 143 | no_decision |
| `hotpotqa_hybrid_dag|stage7|map@0|branch=rerank` | 0.7934 | 0.7824 | -0.0111 | 0.1262 | 164 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=fast_lane` | 0.9909 | 0.9897 | -0.0012 | 1.0000 | 143 | no_decision |
| `hotpotqa_hybrid_dag|stage7|mrr@0|branch=rerank` | 0.9326 | 0.9265 | -0.0061 | 0.0018 | 164 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=fast_lane` | 0.8173 | 0.8009 | -0.0165 | 0.0518 | 143 | no_decision |
| `hotpotqa_hybrid_dag|stage7|ndcg@10|branch=rerank` | 0.8584 | 0.8490 | -0.0095 | 0.1408 | 164 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=fast_lane` | 0.1678 | 0.1601 | -0.0077 | 0.0240 | 143 | no_decision |
| `hotpotqa_hybrid_dag|stage7|precision@10|branch=rerank` | 0.1823 | 0.1805 | -0.0018 | 0.1499 | 164 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=fast_lane` | 0.8392 | 0.8007 | -0.0385 | 0.0240 | 143 | no_decision |
| `hotpotqa_hybrid_dag|stage7|recall@10|branch=rerank` | 0.9116 | 0.9024 | -0.0091 | 0.1499 | 164 | no_decision |
| `hotpotqa_hybrid_dag|stage8|latency_mean@0` | 0.2069 | 0.4579 | 0.2509 | 0.9717 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|map@0` | 0.7472 | 0.7492 | 0.0020 | 0.9342 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|mrr@0` | 0.9523 | 0.9520 | -0.0003 | 1.0000 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|ndcg@10` | 0.8292 | 0.8244 | -0.0048 | 0.4580 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|precision@10` | 0.1750 | 0.1707 | -0.0043 | 0.0031 | 400 | no_decision |
| `hotpotqa_hybrid_dag|stage8|recall@10` | 0.8750 | 0.8538 | -0.0212 | 0.0103 | 400 | candidate_worse |

## Most affected queries

Candidate minus baseline for `hotpotqa_hybrid_dag|stage-1|latency_mean@0`.

| Query | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| `5a7b24fe55429931da12c9f7` | 169.0113 | 2355.5380 | 2186.5266 |
| `5a7d7deb5542995f4f402282` | 203.5360 | 2339.5715 | 2136.0354 |
| `5ae0968955429924de1b7105` | 129.4888 | 2113.2586 | 1983.7698 |
| `5ab4314955429942dd415ecd` | 202.3169 | 1464.0368 | 1261.7200 |
| `5a848b5c5542997175ce1ef2` | 2623.3077 | 1656.2909 | -967.0168 |
| `5ab5ecd75542992aa134a3e6` | 493.6080 | 1434.0176 | 940.4096 |
| `5ae789615542997ec2727695` | 393.8685 | 1333.8522 | 939.9837 |
| `5a8f9c3f554299458435d69a` | 2289.5982 | 1419.7851 | -869.8131 |
| `5a8457835542990548d0b28a` | 506.5657 | 1343.2121 | 836.6465 |
| `5abcff225542993a06baf9ea` | 2280.7008 | 1467.4284 | -813.2725 |
| `5a873ec75542996432c57244` | 525.0676 | 1330.8730 | 805.8055 |
| `5a859a755542992a431d1b6d` | 425.5534 | 1193.7497 | 768.1963 |
| `5abf931f5542990832d3a158` | 481.8807 | 1249.0248 | 767.1440 |
| `5a83eaae55429933447460b4` | 561.8082 | 1326.7350 | 764.9268 |
| `5ae5e62455429929b0807a07` | 409.2377 | 1166.6535 | 757.4159 |
| `5a7c6fde55429907fabeef87` | 138.9727 | 894.9871 | 756.0145 |
| `5ae4c5595542990ba0bbb123` | 426.9515 | 1182.2874 | 755.3359 |
| `5a85fa815542996432c57155` | 444.9893 | 1197.3330 | 752.3436 |
| `5ac1b8ee5542994d76dccedc` | 504.3310 | 1254.2730 | 749.9420 |
| `5a87411d5542994846c1cd37` | 552.6242 | 1302.2873 | 749.6631 |
