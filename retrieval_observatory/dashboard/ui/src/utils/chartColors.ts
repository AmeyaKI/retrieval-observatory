/** Okabe-Ito colorblind-safe palette — well-separated hues. */
export const CHART_PALETTE = [
  '#0072B2', // blue
  '#E69F00', // orange
  '#009E73', // green
  '#D55E00', // vermillion
  '#CC79A7', // pink
  '#56B4E9', // sky blue
  '#F0E442', // yellow
  '#000000', // black
]

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

/** Apply alpha to a #RRGGBB hex color (for latency P95/P99 tiers). */
export function withAlpha(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  if (h.length !== 6) return hex
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
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
