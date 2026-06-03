export const METRIC_GLOSSARY: Record<string, string> = {
  ndcg: 'NDCG@K — Normalized Discounted Cumulative Gain. Measures ranking quality: are the most relevant documents near the top of results? A score of 1.0 means perfect ranking. Graded relevance (0/1/2) is used for BEIR datasets, matching the published benchmark methodology.',
  recall: 'Recall@K — fraction of ALL relevant documents in the dataset that appear in the top-K retrieved results. 1.0 means every relevant document was found. Low recall means the retriever is missing relevant content entirely.',
  precision: 'Precision@K — fraction of the top-K retrieved results that are relevant (|relevant ∩ top-K| / K). High precision means few false positives in the shortlist. Unlike recall, precision does not penalize missing relevant docs outside the top-K.',
  temporal_recall: 'Temporal Recall@K — time-aware variant of Recall@K. A retrieved document only counts as relevant if it was published before or near the query\'s temporal anchor. Ordinary recall rewards stale documents equally; temporal recall penalises pipelines that surface outdated results for time-sensitive queries.',
  mrr: 'MRR — Mean Reciprocal Rank. Average of 1/(rank of the first relevant document). A score of 1.0 means the system always returns a relevant document in position 1. Most useful for single-answer retrieval (e.g., question answering).',
  map: 'MAP — Mean Average Precision. Average area under the precision-recall curve, computed per query and then averaged. Rewards both finding all relevant documents and ranking them highly. Penalizes retrievers that find relevant docs late in the list.',
  latency_p50: 'P50 — Median latency. Half of all queries complete faster than this value, half slower. Best represents the typical user experience.',
  latency_p95: 'P95 — 95th percentile latency. 95% of queries complete within this time. High P95 relative to P50 indicates occasional slow outliers (tail latency), which degrade real-world user experience.',
  latency_p99: 'P99 — 99th percentile tail latency. The slowest 1% of queries. Critical for SLA evaluation and for detecting timeout-prone queries.',
  latency_percentile_summary:
    'Percentile summary across per-query latencies — not a bootstrap mean. Std and 95% CI are not shown because these rows are scalar percentiles (P50/P95/P99), not distributions over queries.',
  zero_pct: '% Zero Scores — percentage of queries where this metric scored exactly 0. For recall/NDCG: zero means no relevant documents were retrieved at all for those queries. High zero% reveals that the retriever completely fails on a subset of queries, which a simple mean hides.',
  ci: '95% Confidence Interval — computed via bootstrap resampling (1000 iterations). If two CIs overlap substantially, the difference between runs may not be statistically meaningful. Narrow CIs indicate stable, consistent performance.',
  stage: 'Pipeline Stage — Stage 0 is the initial retriever (e.g. BM25, dense bi-encoder) that searches the full corpus. Stage 1+ are rerankers that re-score the candidates from Stage 0 for higher precision. Each stage\'s metrics are evaluated independently against the ground truth.',
  p_value: 'Significance (paired bootstrap test, 1000 iterations). p < 0.05 means the performance difference between the two runs is statistically significant at the 95% confidence level. Requires both runs to have processed the same query set.',
  ref_bm25: 'Published BM25 baseline from the BEIR benchmark (Thakur et al. 2021, Table 2), using BM25 on Elasticsearch. Use this as a reference point — your results running the same BM25 logic should be close to this value.',
  underpowered: 'Fewer than 30 queries — bootstrap confidence intervals are unreliable. Smoke runs (n=20) always show this badge. Run full sweeps for stable CIs.',
  wide_ci: 'Relative CI width ≥ 35% of the mean — high variance across queries; treat the mean as directional only.',
  wide_ci_abs:
    'Absolute CI width ≥ 0.05 on a low mean (< 0.2) — common for sparse metrics like Recall@1; the mean understates how often queries fail completely. Check % Zero.',
  high_zero_pct:
    'More than 20% of queries scored 0 on this metric — no relevant documents in top-K for that fraction of queries. The mean overstates typical performance.',
  stable: 'Relative CI width < 15% — consistent performance across queries.',
  profile_compute_ms: 'Local compute time (ms) per query — CPU/GPU work in-process (BM25, bi-encoder, cross-encoder). 100% zero on network is normal for local adapters.',
  profile_network_ms: 'Network/API time (ms) per query — HTTP round-trips (Cohere, remote vector DB). 100% zero on compute is normal for API-only adapters.',
  failure_labels_intro: 'Post-hoc labels per query×pipeline from retrieval diagnostics. They explain why a query failed for a pipeline — not aggregate metric values.',
  candidate_miss: 'Stage 0 retrieved zero relevant documents. Retrieval failure — a reranker cannot recover missed candidates.',
  reranker_drop: 'Stage 0 had relevant hits but the final stage lost them all. Indicates reranker regression or over-aggressive truncation.',
  lexical_mismatch: 'BM25 missed but a dense retriever found relevant docs. Lexical/query-vocabulary gap.',
  semantic_mismatch: 'Dense retriever missed but BM25 found relevant docs. Semantic/embedding gap.',
  id_or_qrel_issue: 'No pipeline retrieved any relevant doc. Possible qrel/corpus ID mismatch — check corpus loading.',
  unstable: 'Query has high cross-pipeline variance (unstable difficulty bucket).',
  actual_difficulty: 'Post-hoc difficulty from mean recall across all pipelines after the benchmark. Five diagnostic buckets map to easy/medium/hard for classifier agreement.',
  predicted_difficulty: 'Pre-retrieval prediction from query text features (trained on prior benchmark diagnostics). Can differ from post-hoc actual when the model is undertrained.',
}

/** Look up a glossary entry by a metric name fragment (case-insensitive). Returns undefined if not found. */
export function lookupGlossary(metricName: string): string | undefined {
  const lower = metricName.toLowerCase()
  if (lower.includes('ndcg')) return METRIC_GLOSSARY.ndcg
  if (lower.startsWith('temporal_recall')) return METRIC_GLOSSARY.temporal_recall
  if (lower.includes('recall')) return METRIC_GLOSSARY.recall
  if (lower.includes('precision')) return METRIC_GLOSSARY.precision
  if (lower.includes('mrr')) return METRIC_GLOSSARY.mrr
  if (lower === 'map' || lower.startsWith('map@')) return METRIC_GLOSSARY.map
  if (lower.includes('p50')) return METRIC_GLOSSARY.latency_p50
  if (lower.includes('p95')) return METRIC_GLOSSARY.latency_p95
  if (lower.includes('p99')) return METRIC_GLOSSARY.latency_p99
  if (lower.includes('profile_compute')) return METRIC_GLOSSARY.profile_compute_ms
  if (lower.includes('profile_network')) return METRIC_GLOSSARY.profile_network_ms
  return undefined
}

export function lookupFailureLabel(label: string): string | undefined {
  return METRIC_GLOSSARY[label as keyof typeof METRIC_GLOSSARY]
}
