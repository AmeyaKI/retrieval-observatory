/** Okabe-Ito colorblind-safe palette — well-separated hues. */
export const CHART_PALETTE = [
  '#0072B2', // blue
  '#E69F00', // orange
  '#009E73', // green
  '#D55E00', // vermillion
  '#CC79A7', // pink
  '#56B4E9', // sky blue
  '#F0E442', // yellow
  '#949494', // neutral gray (fallback — avoid black in charts/legends)
]

/** Fixed colors for latency percentile grouped bars (legend color = bar color). */
export const LATENCY_PERCENTILE_SERIES = [
  { dataKey: 'p50', metricName: 'latency_p50', label: 'P50 (median)', color: CHART_PALETTE[0] },
  { dataKey: 'p95', metricName: 'latency_p95', label: 'P95 (tail)', color: CHART_PALETTE[1] },
  { dataKey: 'p99', metricName: 'latency_p99', label: 'P99 (worst-case)', color: CHART_PALETTE[2] },
] as const

export type LatencyPercentileSeries = (typeof LATENCY_PERCENTILE_SERIES)[number]

/** Return percentile series present in aggregated metrics (e.g. skip P99 when not configured). */
export function detectLatencyPercentiles(
  metrics: Record<string, { metric_name: string }>,
): LatencyPercentileSeries[] {
  const present = new Set<string>()
  for (const entry of Object.values(metrics)) {
    if (entry.metric_name.startsWith('latency_p')) present.add(entry.metric_name)
  }
  return LATENCY_PERCENTILE_SERIES.filter((s) => present.has(s.metricName))
}

/** Stable pipeline → color map (sorted by pipeline_id). */
export function buildPipelineColorMap(pipelineIds: Iterable<string>): Map<string, string> {
  const sorted = [...new Set(pipelineIds)].sort((a, b) => a.localeCompare(b))
  const map = new Map<string, string>()
  sorted.forEach((id, i) => {
    map.set(id, CHART_PALETTE[i % CHART_PALETTE.length])
  })
  return map
}

export function getPipelineColor(pipelineId: string, colorMap: Map<string, string>): string {
  return colorMap.get(pipelineId) ?? CHART_PALETTE[0]
}

/** Collect distinct pipeline IDs from aggregated metrics (stage_index >= 0). */
export function collectPipelineIds(
  metrics: Record<string, { pipeline_id: string; stage_index: number }>,
): string[] {
  const ids = new Set<string>()
  for (const entry of Object.values(metrics)) {
    if (entry.stage_index >= 0) ids.add(entry.pipeline_id)
  }
  return [...ids].sort((a, b) => a.localeCompare(b))
}

/** @deprecated Use buildPipelineColorMap on pipeline IDs instead of display labels. */
export function buildColorMap(seriesKeys: string[]): Map<string, string> {
  return buildPipelineColorMap(seriesKeys)
}

/** @deprecated Use getPipelineColor(pipelineId, colorMap). */
export function getSeriesColor(seriesKey: string, colorMap: Map<string, string>, fallbackIndex = 0): string {
  return colorMap.get(seriesKey) ?? CHART_PALETTE[fallbackIndex % CHART_PALETTE.length]
}
