export const METRIC_GLOSSARY: Record<string, string> = {
  ndcg: 'NDCG@K — Normalized Discounted Cumulative Gain. Measures ranking quality: are the most relevant documents near the top of results? A score of 1.0 means perfect ranking. Graded relevance (0/1/2) is used for BEIR datasets, matching the published benchmark methodology.',
  recall: 'Recall@K — fraction of ALL relevant documents in the dataset that appear in the top-K retrieved results. 1.0 means every relevant document was found. Low recall means the retriever is missing relevant content entirely.',
  temporal_recall: 'Temporal Recall@K — time-aware variant of Recall@K. A retrieved document only counts as relevant if it was published before or near the query\'s temporal anchor. Ordinary recall rewards stale documents equally; temporal recall penalises pipelines that surface outdated results for time-sensitive queries.',
  mrr: 'MRR — Mean Reciprocal Rank. Average of 1/(rank of the first relevant document). A score of 1.0 means the system always returns a relevant document in position 1. Most useful for single-answer retrieval (e.g., question answering).',
  map: 'MAP — Mean Average Precision. Average area under the precision-recall curve, computed per query and then averaged. Rewards both finding all relevant documents and ranking them highly. Penalizes retrievers that find relevant docs late in the list.',
  latency_p50: 'P50 — Median latency. Half of all queries complete faster than this value, half slower. Best represents the typical user experience.',
  latency_p95: 'P95 — 95th percentile latency. 95% of queries complete within this time. High P95 relative to P50 indicates occasional slow outliers (tail latency), which degrade real-world user experience.',
  latency_p99: 'P99 — 99th percentile tail latency. The slowest 1% of queries. Critical for SLA evaluation and for detecting timeout-prone queries.',
  zero_pct: '% Zero Scores — percentage of queries where this metric scored exactly 0. For recall/NDCG: zero means no relevant documents were retrieved at all for those queries. High zero% reveals that the retriever completely fails on a subset of queries, which a simple mean hides.',
  ci: '95% Confidence Interval — computed via bootstrap resampling (1000 iterations). If two CIs overlap substantially, the difference between runs may not be statistically meaningful. Narrow CIs indicate stable, consistent performance.',
  stage: 'Pipeline Stage — Stage 0 is the initial retriever (e.g. BM25, dense bi-encoder) that searches the full corpus. Stage 1+ are rerankers that re-score the candidates from Stage 0 for higher precision. Each stage\'s metrics are evaluated independently against the ground truth.',
  p_value: 'Significance (paired bootstrap test, 1000 iterations). p < 0.05 means the performance difference between the two runs is statistically significant at the 95% confidence level. Requires both runs to have processed the same query set.',
  ref_bm25: 'Published BM25 baseline from the BEIR benchmark (Thakur et al. 2021, Table 2), using BM25 on Elasticsearch. Use this as a reference point — your results running the same BM25 logic should be close to this value.',
}

/** Look up a glossary entry by a metric name fragment (case-insensitive). Returns undefined if not found. */
export function lookupGlossary(metricName: string): string | undefined {
  const lower = metricName.toLowerCase()
  if (lower.includes('ndcg')) return METRIC_GLOSSARY.ndcg
  if (lower.startsWith('temporal_recall')) return METRIC_GLOSSARY.temporal_recall
  if (lower.includes('recall')) return METRIC_GLOSSARY.recall
  if (lower.includes('mrr')) return METRIC_GLOSSARY.mrr
  if (lower === 'map' || lower.startsWith('map@')) return METRIC_GLOSSARY.map
  if (lower.includes('p50')) return METRIC_GLOSSARY.latency_p50
  if (lower.includes('p95')) return METRIC_GLOSSARY.latency_p95
  if (lower.includes('p99')) return METRIC_GLOSSARY.latency_p99
  return undefined
}
