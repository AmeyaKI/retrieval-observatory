/**
 * Converts an internal storage key into a human-readable label.
 *
 * When the key belongs to a multi-stage pipeline, stage role labels are shown:
 *   "bm25_plus_reranker|stage0|ndcg@10"  → "NDCG@10  ·  BM25 Plus Reranker (Retrieval)"
 *   "bm25_plus_reranker|stage1|ndcg@10"  → "NDCG@10  ·  BM25 Plus Reranker (Reranking)"
 *   "bm25_baseline|stage0|recall@10"      → "Recall@10  ·  BM25 Baseline"
 *   "bm25_baseline|stage0|latency_p95@0"  → "Latency P95  ·  BM25 Baseline"
 *
 * Pass a set of all pipeline IDs present in the MetricsMap so the function can
 * detect whether a pipeline has multiple stages. If omitted, falls back to the
 * old behaviour (shows "Stage N" for stageIndex > 0).
 */
export function formatMetricKey(key: string, multiStagePipelines?: Set<string>): string {
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
  const pipelineLabel = toPipelineLabel(pipelineId)

  // Stage role label — only when the pipeline is actually multi-stage
  const isMulti = multiStagePipelines ? multiStagePipelines.has(pipelineId) : stageIndex > 0
  let stageLabel = ''
  if (isMulti) {
    stageLabel = stageIndex === 0 ? ' (Retrieval)' : ' (Reranking)'
  }

  return `${metricLabel}  ·  ${pipelineLabel}${stageLabel}`
}

function toPipelineLabel(pipelineId: string): string {
  return pipelineId
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
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

/**
 * Shorter label for chart legends (no metric prefix).
 *
 * @param isMultiStage - when true, append stage role ("Retrieval"/"Reranking") instead of stage number
 */
export function formatSeriesKey(pipelineId: string, stageIndex: number, isMultiStage = false): string {
  const pipelineLabel = toPipelineLabel(pipelineId)
  if (!isMultiStage) return pipelineLabel
  const role = stageIndex === 0 ? 'Retrieval' : 'Reranking'
  return `${pipelineLabel} (${role})`
}
