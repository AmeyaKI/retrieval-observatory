const BASE = window.location.origin

export interface DbSource {
  db_id: string
  label: string
  path: string
  run_count: number
}

export interface Run {
  run_id: string
  db_id?: string
  experiment_name: string
  started_at: string
  finished_at: string | null
  config_json: string
}

export interface RunSelection {
  dbId: string
  runId: string
}

export function selectionKey(sel: RunSelection): string {
  return `${sel.dbId}:${sel.runId}`
}

function runBase(dbId: string, runId: string): string {
  return `${BASE}/dbs/${encodeURIComponent(dbId)}/runs/${encodeURIComponent(runId)}`
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
  [runKey: string]: RunMetricValues | string | number | undefined
}

export async function fetchDbs(): Promise<DbSource[]> {
  const res = await fetch(`${BASE}/dbs`)
  if (!res.ok) throw new Error('Failed to fetch databases')
  return res.json()
}

export async function fetchRuns(dbId: string): Promise<Run[]> {
  const res = await fetch(`${BASE}/dbs/${encodeURIComponent(dbId)}/runs`)
  if (!res.ok) throw new Error(`Failed to fetch runs for database ${dbId}`)
  return res.json()
}

export async function fetchMetrics(dbId: string, runId: string): Promise<MetricsMap> {
  const res = await fetch(`${runBase(dbId, runId)}/metrics`)
  if (!res.ok) throw new Error(`Failed to fetch metrics for run ${runId}`)
  return res.json()
}

export async function fetchComparison(
  selections: RunSelection[],
): Promise<{
  comparison: ComparisonEntry[]
  selections: Array<{ db_id: string; run_id: string }>
  run_ids: string[]
  warnings: string[]
}> {
  const res = await fetch(`${BASE}/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      selections: selections.map((s) => ({ db_id: s.dbId, run_id: s.runId })),
    }),
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
export async function fetchSegmentMetrics(
  dbId: string,
  runId: string,
  field: string = 'n_relevant',
): Promise<SegmentMetrics> {
  const res = await fetch(
    `${runBase(dbId, runId)}/metrics/by-segment?field=${encodeURIComponent(field)}`,
  )
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

export interface PipelineDiagnostics {
  n: number
  labels: Record<string, number>
  difficulty_buckets: Record<string, number>
}

export interface RunOverview {
  headline_winner: null | (MetricEntry & { metric: string })
  diagnostics: {
    difficulty_buckets: Record<string, number>
    failure_labels: Record<string, number>
    by_pipeline: Record<string, PipelineDiagnostics>
    n: number
  }
  manifest: Record<string, unknown> | null
  warnings: string[]
  stage_contributions: StageContribution[]
}

export async function fetchRunOverview(dbId: string, runId: string): Promise<RunOverview> {
  const res = await fetch(`${runBase(dbId, runId)}/overview`)
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

export async function fetchDiagnostics(
  dbId: string,
  runId: string,
): Promise<{ summary: RunOverview['diagnostics']; items: QueryDiagnostic[] }> {
  const res = await fetch(`${runBase(dbId, runId)}/diagnostics`)
  if (!res.ok) throw new Error(`Failed to fetch diagnostics for run ${runId}`)
  return res.json()
}

export async function fetchStageMatrix(
  dbId: string,
  runId: string,
): Promise<{ run_id: string; cells: Array<MetricEntry & { metric: string; estimated_cost_per_1k: number }> }> {
  const res = await fetch(`${runBase(dbId, runId)}/stage-matrix`)
  if (!res.ok) throw new Error(`Failed to fetch stage matrix for run ${runId}`)
  return res.json()
}

export interface ParetoPipelineMetrics {
  'ndcg@10': number
  'recall@10': number
  latency_p50: number
  latency_p95: number
  cost_per_1k: number | null
}

export interface ParetoPipelineEntry {
  pipeline_id: string
  stage_index: number
  label: string
  metrics: ParetoPipelineMetrics
  is_pareto_optimal: boolean
  dominated_by: string[]
}

export interface ParetoFrontierResponse {
  run_id: string
  objectives: string[]
  cost_included: boolean
  cost_excluded_reason: string | null
  latency_budget_ms: number | null
  pipelines: ParetoPipelineEntry[]
  frontier_order: string[]
}

export async function fetchParetoFrontier(dbId: string, runId: string): Promise<ParetoFrontierResponse> {
  const res = await fetch(`${runBase(dbId, runId)}/pareto-frontier`)
  if (!res.ok) throw new Error(`Failed to fetch Pareto frontier for run ${runId}`)
  return res.json()
}

export interface QueryLabelRow {
  query_id: string
  query_text: string
  actual_bucket: string
  actual_class: string
  predicted_difficulty: string | null
  predicted_difficulty_proba: Record<string, number> | null
  agreement: 'match' | 'adjacent' | 'mismatch' | null
}

export async function fetchQueryLabels(dbId: string, runId: string): Promise<{ items: QueryLabelRow[] }> {
  const res = await fetch(`${runBase(dbId, runId)}/query-labels`)
  if (!res.ok) throw new Error(`Failed to fetch query labels for run ${runId}`)
  return res.json()
}

export interface ClassifierCalibrationClass {
  class: string
  n: number
  mean_recall10: number | null
  ci_low: number | null
  ci_high: number | null
  agreement_rate: number | null
}

export interface ClassifierCalibrationResponse {
  run_id: string
  has_predictions: boolean
  classes: ClassifierCalibrationClass[]
  actual_classes?: ClassifierCalibrationClass[]
  all_same_prediction?: boolean
}

export async function fetchClassifierCalibration(
  dbId: string,
  runId: string,
): Promise<ClassifierCalibrationResponse> {
  const res = await fetch(`${runBase(dbId, runId)}/classifier-calibration`)
  if (!res.ok) throw new Error(`Failed to fetch classifier calibration for run ${runId}`)
  return res.json()
}
