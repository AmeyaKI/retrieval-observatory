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
  paired_n?: number
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

export interface StageDelta {
  before: number
  after: number
  absolute: number
  pct: number
  q_value: number | null
  significant: boolean
}

export interface StageContribution {
  from_pipeline: string
  to_pipeline: string
  deltas: Record<string, StageDelta>
  latency_p50_before_ms: number | null
  latency_p50_after_ms: number | null
  latency_delta_ms: number | null
}

export interface RunOverview {
  headline_winner: null | (MetricEntry & { metric: string })
  diagnostics: { difficulty_buckets: Record<string, number>; failure_labels: Record<string, number>; n: number }
  manifest: Record<string, unknown> | null
  warnings: string[]
  stage_contributions: StageContribution[]
}

export async function fetchRunOverview(runId: string): Promise<RunOverview> {
  const res = await fetch(`${BASE}/runs/${runId}/overview`)
  if (!res.ok) throw new Error(`Failed to fetch overview for run ${runId}`)
  return res.json()
}

export interface QueryDiagnostic {
  query_id: string
  pipeline_id: string
  difficulty_bucket: string
  failure_labels: string[]
  missing_relevant_ids: string[]
  stage_hits: Record<string, string[]>
}

export async function fetchDiagnostics(runId: string): Promise<{ summary: RunOverview['diagnostics']; items: QueryDiagnostic[] }> {
  const res = await fetch(`${BASE}/runs/${runId}/diagnostics`)
  if (!res.ok) throw new Error(`Failed to fetch diagnostics for run ${runId}`)
  return res.json()
}

export async function fetchStageMatrix(runId: string): Promise<{ run_id: string; cells: Array<MetricEntry & { metric: string; estimated_cost_per_1k: number }> }> {
  const res = await fetch(`${BASE}/runs/${runId}/stage-matrix`)
  if (!res.ok) throw new Error(`Failed to fetch stage matrix for run ${runId}`)
  return res.json()
}
