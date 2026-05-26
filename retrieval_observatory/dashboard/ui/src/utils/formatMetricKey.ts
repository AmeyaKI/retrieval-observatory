/**
 * Converts an internal storage key into a human-readable label.
 *
 * Examples:
 *   "bm25_baseline|stage0|recall@10"      → "Recall@10  ·  BM25 Baseline"
 *   "dense_minilm|stage1|ndcg@10"         → "NDCG@10  ·  Dense Minilm (Stage 1)"
 *   "bm25_baseline|stage0|latency_p95@0"  → "Latency P95  ·  BM25 Baseline"
 *   "bm25_baseline|stage0|mrr@0"          → "MRR  ·  BM25 Baseline"
 */
export function formatMetricKey(key: string): string {
  const parts = key.split('|')
  if (parts.length !== 3) return key

  const [pipelineId, stageStr, metricAtK] = parts
  const stageIndex = parseInt(stageStr.replace('stage', ''), 10)

  // Format metric name + k
  const atIdx = metricAtK.lastIndexOf('@')
  const metricName = atIdx >= 0 ? metricAtK.slice(0, atIdx) : metricAtK
  const k = atIdx >= 0 ? parseInt(metricAtK.slice(atIdx + 1), 10) : 0
  const metricLabel = formatMetricName(metricName, k)

  // Format pipeline label (snake_case → Title Case)
  const pipelineLabel = pipelineId
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')

  // Only append stage number if it's a non-zero (multi-stage pipeline)
  const stageLabel = stageIndex > 0 ? ` (Stage ${stageIndex})` : ''

  return `${metricLabel}  ·  ${pipelineLabel}${stageLabel}`
}

function formatMetricName(name: string, k: number): string {
  // Latency percentiles: "latency_p50" → "Latency P50"
  if (name.startsWith('latency_p')) {
    const pct = name.slice('latency_p'.length)
    return `Latency P${pct}`
  }

  const upper = name.toUpperCase()

  // Metrics with a meaningful K value
  if (k > 0) {
    return `${upper}@${k}`
  }

  // Metrics with k=0 sentinel (MRR, MAP, latency) — display name only
  return upper
}

/** Shorter label for chart legends (no pipeline prefix). */
export function formatSeriesKey(pipelineId: string, stageIndex: number): string {
  const pipelineLabel = pipelineId
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
  return stageIndex > 0 ? `${pipelineLabel} (Stage ${stageIndex})` : pipelineLabel
}
