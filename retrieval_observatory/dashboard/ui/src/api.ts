const BASE = window.location.origin

export interface Run {
  run_id: string
  experiment_name: string
  started_at: string
  finished_at: string | null
  config_json: string
}

export interface MetricEntry {
  pipeline_id: string
  stage_index: number
  metric_name: string
  k: number
  mean: number
  std: number
  ci_low: number
  ci_high: number
  n: number
  zero_count: number
  zero_pct: number
}

export type MetricsMap = Record<string, MetricEntry>

export interface RunMetricValues {
  mean: number | null
  std: number | null
  ci_low: number | null
  ci_high: number | null
}

export interface ComparisonEntry {
  metric: string
  p_value?: number
  [runId: string]: RunMetricValues | string | number | undefined
}

export async function fetchRuns(): Promise<Run[]> {
  const res = await fetch(`${BASE}/runs`)
  if (!res.ok) throw new Error('Failed to fetch runs')
  return res.json()
}

export async function fetchMetrics(runId: string): Promise<MetricsMap> {
  const res = await fetch(`${BASE}/runs/${runId}/metrics`)
  if (!res.ok) throw new Error(`Failed to fetch metrics for run ${runId}`)
  return res.json()
}

export async function fetchComparison(runIds: string[]): Promise<{ comparison: ComparisonEntry[]; run_ids: string[] }> {
  const res = await fetch(`${BASE}/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_ids: runIds }),
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`Failed to fetch comparison (${res.status}): ${body || res.statusText}`)
  }
  return res.json()
}

/** Returns published BEIR BM25 baselines for a dataset, e.g. {"ndcg@10": 0.326}. */
export async function fetchBaselines(datasetName: string): Promise<Record<string, number>> {
  const res = await fetch(`${BASE}/datasets/${encodeURIComponent(datasetName)}/baselines`)
  if (!res.ok) return {}
  return res.json()
}

export interface SegmentMetrics {
  field: string
  segments: Record<string, Record<string, MetricEntry>>
}

/** Returns per-segment aggregated metrics grouped by a query metadata field. */
export async function fetchSegmentMetrics(runId: string, field: string = 'n_relevant'): Promise<SegmentMetrics> {
  const res = await fetch(`${BASE}/runs/${runId}/metrics/by-segment?field=${encodeURIComponent(field)}`)
  if (!res.ok) throw new Error(`Failed to fetch segment metrics for run ${runId}`)
  return res.json()
}
