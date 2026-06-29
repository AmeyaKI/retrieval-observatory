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
  golden_set?: string
  forge_dataset_id?: string
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
  branch_id?: string | null
  metric_name: string
  k: number
  mean: number
  std: number | null
  ci_low: number | null
  ci_high: number | null
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
  indeterminate?: boolean
  indeterminate_reason?: string | null
  n_pairs?: number | null
}

export interface StageContribution {
  comparison_tier?: 'cross_pipeline_prefix' | 'within_pipeline_stage' | 'within_stage_arm'
  from_pipeline: string
  to_pipeline: string
  pipeline_id?: string
  stage_index?: number
  branch_id?: string
  deltas: Record<string, StageDelta>
  latency_p50_before_ms: number | null
  latency_p50_after_ms: number | null
  latency_delta_ms: number | null
  indeterminate?: boolean
}

export interface TopologyStageMetrics {
  'ndcg@10': number | null
  recall: { k: number | null; mean: number | null }
  latency_p50: number | null
}

export interface TopologyArm {
  arm_id: string
  candidate_count: number
  metrics: TopologyStageMetrics
}

export interface TopologyStage {
  stage_index: number
  stage_id: string
  kind: 'single' | 'fused' | 'rerank'
  candidate_count: number
  metrics: TopologyStageMetrics
  arms: TopologyArm[]
}

export type PipelineTopology = Record<string, TopologyStage[]>

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
  pipeline_topology?: PipelineTopology
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
  predicted_risks?: string[]
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

// ───────────────────────── Forge ─────────────────────────

export interface ForgeDatasetSummary {
  total_queries?: number
  total_scenarios?: number
  corpus_size?: number
  validated?: number
  by_difficulty?: Record<string, number>
  by_query_type?: Record<string, number>
  by_scenario_type?: Record<string, number>
}

export interface ForgeDataset {
  dataset_id: string
  created_at: string
  corpus_path: string
  output_dir: string
  summary: ForgeDatasetSummary
}

export interface ForgeScenario {
  scenario_id: string
  scenario_type: string
  anchor_doc_ids: string[]
  evidence_summary: string
}

export interface ForgeDatasetDetail extends ForgeDataset {
  scenarios: ForgeScenario[]
  validation_coverage: number
}

export interface ForgeQuery {
  query_id: string
  text: string
  scenario_id: string
  query_type: string
  difficulty_label: string
  failure_category: string | null
  validated: boolean
  positive_doc_ids: string[]
}

export interface ForgeRunRef {
  run_id: string
  experiment_name: string
  started_at: string
}

export async function fetchForgeDatasets(): Promise<ForgeDataset[]> {
  const res = await fetch(`${BASE}/forge/datasets`)
  if (!res.ok) throw new Error('Failed to fetch Forge datasets')
  return res.json()
}

export async function fetchForgeDataset(datasetId: string): Promise<ForgeDatasetDetail> {
  const res = await fetch(`${BASE}/forge/datasets/${encodeURIComponent(datasetId)}`)
  if (!res.ok) throw new Error(`Failed to fetch Forge dataset ${datasetId}`)
  return res.json()
}

export async function fetchForgeQueries(
  datasetId: string,
  filters: { scenario_type?: string; difficulty?: string; query_type?: string; validated_only?: boolean } = {},
): Promise<ForgeQuery[]> {
  const params = new URLSearchParams()
  if (filters.scenario_type) params.set('scenario_type', filters.scenario_type)
  if (filters.difficulty) params.set('difficulty', filters.difficulty)
  if (filters.query_type) params.set('query_type', filters.query_type)
  if (filters.validated_only) params.set('validated_only', 'true')
  const qs = params.toString()
  const res = await fetch(`${BASE}/forge/datasets/${encodeURIComponent(datasetId)}/queries${qs ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error(`Failed to fetch queries for Forge dataset ${datasetId}`)
  return res.json()
}

export async function fetchForgeDatasetRuns(datasetId: string): Promise<ForgeRunRef[]> {
  const res = await fetch(`${BASE}/forge/datasets/${encodeURIComponent(datasetId)}/runs`)
  if (!res.ok) throw new Error(`Failed to fetch runs for Forge dataset ${datasetId}`)
  return res.json()
}

// ───────────────────────── TraceLens ─────────────────────────

export interface TraceService {
  service: string
  trace_count: number
  last_seen: string
}

export interface TraceRow {
  trace_id: string
  service: string
  query_id: string
  query_text: string
  pipeline_id: string
  status: string
  total_latency_ms: number
  timestamp: string
  predicted_difficulty: string | null
  suspected_failures: string[]
  metadata: Record<string, unknown>
}

export interface TraceStage {
  stage_index: number
  stage_id: string
  latency_ms: number
  candidate_count: number
  documents: { id: string; text?: string; score: number; rank: number; title?: string }[]
}

export interface TraceDetail extends TraceRow {
  stages: TraceStage[]
}

export interface TraceSummary {
  trace_count: number
  ok_rate: number
  error_rate: number
  latency_p50: number
  latency_p95: number
  suspected_failure_rate: number
}

export interface TraceDistribution {
  n: number
  by_difficulty: Record<string, number>
  by_status: Record<string, number>
  by_length_bin: Record<string, number>
  by_failure_label: Record<string, number>
  latency_percentiles: Record<string, number>
}

export interface DriftFinding {
  feature: string
  method: string
  statistic: number
  drifted: boolean
  severity: string
  baseline: Record<string, number>
  recent: Record<string, number>
}

export interface FailureHotspot {
  segment: string
  difficulty: string
  label: string
  pipeline: string
  count: number
  rate: number
}

export interface QueryClusterRow {
  cluster: string
  size: number
  share: number
  examples: string[]
  suspected_rate: number
  latency_p50: number
}

function windowParams(service: string, since?: string): string {
  const p = new URLSearchParams({ service })
  if (since) p.set('since', since)
  return p.toString()
}

export async function fetchTraceServices(): Promise<TraceService[]> {
  const res = await fetch(`${BASE}/tracelens/services`)
  if (!res.ok) throw new Error('Failed to fetch trace services')
  return res.json()
}

export async function fetchTraceSummary(service: string, since?: string): Promise<TraceSummary> {
  const res = await fetch(`${BASE}/tracelens/summary?${windowParams(service, since)}`)
  if (!res.ok) throw new Error('Failed to fetch trace summary')
  return res.json()
}

export async function fetchTraces(
  service: string,
  filters: { since?: string; status?: string; difficulty?: string; suspected_only?: boolean } = {},
): Promise<TraceRow[]> {
  const p = new URLSearchParams({ service })
  if (filters.since) p.set('since', filters.since)
  if (filters.status) p.set('status', filters.status)
  if (filters.difficulty) p.set('difficulty', filters.difficulty)
  if (filters.suspected_only) p.set('suspected_only', 'true')
  const res = await fetch(`${BASE}/tracelens/traces?${p.toString()}`)
  if (!res.ok) throw new Error('Failed to fetch traces')
  return res.json()
}

export async function fetchTraceDetail(traceId: string): Promise<TraceDetail> {
  const res = await fetch(`${BASE}/tracelens/traces/${encodeURIComponent(traceId)}`)
  if (!res.ok) throw new Error(`Failed to fetch trace ${traceId}`)
  return res.json()
}

export async function fetchTraceDistribution(service: string, since?: string): Promise<TraceDistribution> {
  const res = await fetch(`${BASE}/tracelens/distribution?${windowParams(service, since)}`)
  if (!res.ok) throw new Error('Failed to fetch trace distribution')
  return res.json()
}

export async function fetchTraceDrift(service: string, baseline?: string, recent?: string): Promise<DriftFinding[]> {
  const p = new URLSearchParams({ service })
  if (baseline) p.set('baseline', baseline)
  if (recent) p.set('recent', recent)
  const res = await fetch(`${BASE}/tracelens/drift?${p.toString()}`)
  if (!res.ok) throw new Error('Failed to fetch drift findings')
  return res.json()
}

export async function fetchTraceHotspots(service: string, since?: string): Promise<FailureHotspot[]> {
  const res = await fetch(`${BASE}/tracelens/hotspots?${windowParams(service, since)}`)
  if (!res.ok) throw new Error('Failed to fetch failure hotspots')
  return res.json()
}

export async function fetchTraceClusters(service: string, since?: string): Promise<QueryClusterRow[]> {
  const res = await fetch(`${BASE}/tracelens/clusters?${windowParams(service, since)}`)
  if (!res.ok) throw new Error('Failed to fetch query clusters')
  return res.json()
}

export interface QueryLineageOrigin {
  source: 'forge' | 'dataset'
  query_text: string | null
  dataset_name: string | null
  forge: {
    dataset_id: string
    scenario_id: string
    scenario_type: string
    query_type: string
    difficulty_label: string
    failure_category: string | null
    validated: boolean
    positive_doc_ids: string[]
    evidence_summary: string | null
  } | null
}

export interface QueryLineageEvaluation {
  run_id: string
  experiment_name: string
  started_at: string
  dataset_name: string
  metrics: Array<Record<string, unknown>>
  diagnostics: Array<Record<string, unknown>>
}

export interface QueryLineageTrace {
  trace_id: string
  service: string
  query_id: string
  query_text: string
  predicted_difficulty: string | null
  suspected_failures: string[]
}

export interface QueryLineage {
  query_id: string
  origin: QueryLineageOrigin
  evaluations: QueryLineageEvaluation[]
  production_matches: {
    match_type: string
    note: string
    match_difficulty: string | null
    match_failure_labels: string[]
    traces: QueryLineageTrace[]
  }
}

export async function fetchQueryLineage(queryId: string): Promise<QueryLineage> {
  const res = await fetch(`${BASE}/query/${encodeURIComponent(queryId)}/lineage`)
  if (!res.ok) throw new Error(`Failed to fetch lineage for ${queryId}`)
  return res.json()
}

export interface Recommendation {
  action: string
  rationale: string
  evidence: string[]
  priority: number
}

export interface RegressionFinding {
  metric: string
  before: number
  after: number
  delta: number
  q_value: number
  severity: string
  n_pairs: number
}

export interface ReliabilityScore {
  value: number
  components: Record<string, number>
  notes: string[]
}

export interface DemoContext {
  baseline_run_id?: string
  candidate_run_id?: string
  ablation_run_id?: string
  sample_query_id?: string
  tracelens_service?: string
  forge_dataset_id?: string
  db_path?: string
  experiment_names?: Record<string, string>
}

export async function fetchDemoContext(): Promise<DemoContext> {
  const res = await fetch(`${BASE}/demo/context`)
  if (!res.ok) throw new Error('Failed to fetch demo context')
  return res.json()
}

export async function fetchAdvisorRecommendations(runId: string): Promise<{ run_id: string; recommendations: Recommendation[] }> {
  const res = await fetch(`${BASE}/advisor/recommendations?run_id=${encodeURIComponent(runId)}`)
  if (!res.ok) throw new Error('Failed to fetch recommendations')
  return res.json()
}

export async function fetchAdvisorRegressions(baseline: string, candidate: string): Promise<{ regressions: RegressionFinding[] }> {
  const p = new URLSearchParams({ baseline, candidate })
  const res = await fetch(`${BASE}/advisor/regressions?${p.toString()}`)
  if (!res.ok) throw new Error('Failed to fetch regressions')
  return res.json()
}

export async function fetchAdvisorReliability(runId: string): Promise<ReliabilityScore & { run_id: string }> {
  const res = await fetch(`${BASE}/advisor/reliability?run_id=${encodeURIComponent(runId)}`)
  if (!res.ok) throw new Error('Failed to fetch reliability score')
  return res.json()
}

export interface ReliabilityHistoryPoint {
  run_id: string
  recorded_at: string
  value: number
  components: Record<string, number>
}

export async function fetchAdvisorReliabilityHistory(runId?: string): Promise<{ history: ReliabilityHistoryPoint[] }> {
  const p = new URLSearchParams()
  if (runId) p.set('run_id', runId)
  const res = await fetch(`${BASE}/advisor/reliability/history?${p.toString()}`)
  if (!res.ok) throw new Error('Failed to fetch reliability history')
  return res.json()
}
