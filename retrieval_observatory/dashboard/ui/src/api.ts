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
  if (!res.ok) throw new Error('Failed to fetch comparison')
  return res.json()
}
