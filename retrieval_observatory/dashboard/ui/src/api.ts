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

function dbBase(dbId: string): string {
  return `${BASE}/dbs/${encodeURIComponent(dbId)}`
}

/** Parse JSON from a fetch Response; fail clearly when SPA HTML is returned instead of an API payload. */
async function parseJson<T>(res: Response, label: string): Promise<T> {
  const contentType = res.headers.get('content-type') || ''
  const text = await res.text()
  const trimmed = text.trimStart()
  if (
    contentType.includes('text/html') ||
    trimmed.startsWith('<!DOCTYPE') ||
    trimmed.startsWith('<!doctype') ||
    trimmed.startsWith('<html')
  ) {
    throw new Error(
      `${label}: got HTML instead of JSON (likely a missing API route; SPA fallback served index.html)`,
    )
  }
  if (!res.ok) {
    throw new Error(`${label}: ${res.status} ${res.statusText}${trimmed ? ` — ${trimmed.slice(0, 200)}` : ''}`)
  }
  try {
    return JSON.parse(text) as T
  } catch {
    throw new Error(`${label}: response was not valid JSON`)
  }
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
  p_value?: number | null
  q_value?: number | null
  paired_n?: number
  statistics?: {
    baseline_mean: number | null
    candidate_mean: number | null
    effect: number | null
    effect_threshold: number | null
    p_value: number | null
    q_value: number | null
    paired_n: number
    low_power: boolean
    significant: boolean | null
    decision: 'candidate_better' | 'candidate_worse' | 'no_decision'
    reason: string
  }
  [runKey: string]: RunMetricValues | ComparisonEntry['statistics'] | string | number | null | undefined
}

export type ReleaseStatus = 'PASS' | 'HOLD' | 'BLOCK' | 'FAIL'
export type ReadinessStatus = 'READY' | 'HOLD' | 'BLOCK'

export interface EvidenceFinding {
  code: string
  scope: string
  status: ReadinessStatus
  observed: unknown
  required: unknown
  detail: string
  next_action: string
}

export interface ClaimReadiness {
  scope: string
  status: ReadinessStatus
  findings: EvidenceFinding[]
}

export interface ReleaseGuardResult {
  metric: string
  status: ReleaseStatus
  direction: 'higher_is_better' | 'lower_is_better'
  max_regression: number
  estimator: 'mean' | 'p50' | 'p95' | 'p99'
  baseline_estimate: number | null
  candidate_estimate: number | null
  effect: number | null
  ci_low: number | null
  ci_high: number | null
  paired_n: number
  min_paired_n: number
  seed: number
  resamples: number
  confidence_level: number
  adjusted_confidence_level: number
  interval_method: 'paired_percentile_bootstrap'
  sample_limitation: string | null
}

export interface ReleaseSliceResult {
  id: string
  field: string
  value: unknown
  status: ReleaseStatus
  paired_n: number
  label_coverage: number | null
  adjusted_confidence_level: number
  sample_limitation: string | null
  guards: ReleaseGuardResult[]
}

export interface ReleaseDecision {
  schema_version: number
  status: ReleaseStatus
  reasons: string[]
  readiness: Record<string, ClaimReadiness>
  aggregate_guards: ReleaseGuardResult[]
  slices: ReleaseSliceResult[]
  next_action: string
  policy: {
    configured: boolean
    id?: string | null
    schema_version?: number | null
    digest?: string | null
  }
  investigation: {
    affected_query_ids: string[]
    query_route_template: string
    diff_route_template: string
  }
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

export async function fetchMetrics(dbId: string, runId: string, includeBranches = false): Promise<MetricsMap> {
  const query = includeBranches ? '?include_branches=true' : ''
  const res = await fetch(`${runBase(dbId, runId)}/metrics${query}`)
  if (!res.ok) throw new Error(`Failed to fetch metrics for run ${runId}`)
  return res.json()
}

// ── Item D: Run Comparison deeper diffs ──
export interface QueryDiffRow {
  query_id: string
  a: number
  b: number
  delta: number
}

export interface QueryDiffs {
  metric: string
  run_a: string
  run_b: string
  rows: QueryDiffRow[]
}

export async function fetchComparison(
  selections: RunSelection[],
): Promise<{
  comparison: ComparisonEntry[]
  selections: Array<{ db_id: string; run_id: string }>
  run_ids: string[]
  warnings: string[]
  comparability?: ComparabilityReport
  query_diffs?: QueryDiffs | null
  release_decision?: ReleaseDecision | null
}> {
  const res = await fetch(`${BASE}/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      selections: selections.map((s, index) => ({
        db_id: s.dbId,
        run_id: s.runId,
        role: index === 0 ? 'baseline' : index === 1 ? 'candidate' : 'reference',
      })),
    }),
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`Failed to fetch comparison (${res.status}): ${body || res.statusText}`)
  }
  return res.json()
}

export interface StageDiffEntry {
  index: number
  change: 'added' | 'removed' | 'changed' | 'unchanged'
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
}

export interface PipelineDiffEntry {
  pipeline_id: string
  change: 'added' | 'removed' | 'changed' | 'unchanged'
  stage_diffs: StageDiffEntry[]
}

export interface ConfigDiffResult {
  dataset_changed: boolean
  metrics_changed: boolean
  has_changes: boolean
  pipeline_diffs: PipelineDiffEntry[]
}

export async function fetchConfigDiff(selections: RunSelection[]): Promise<ConfigDiffResult> {
  const res = await fetch(`${BASE}/compare/config-diff`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      selections: selections.map((s) => ({ db_id: s.dbId, run_id: s.runId })),
    }),
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`Failed to fetch config diff (${res.status}): ${body || res.statusText}`)
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

// ── PipelineGraph render contract (mirrors dashboard/pipeline_graph.schema.json) ──
export interface GraphMetricValue {
  mean: number | null
  ci_low: number | null
  ci_high: number | null
  k?: number | null
}

export interface PipelineGraphNodeMetrics {
  'ndcg@10': GraphMetricValue | null
  recall: GraphMetricValue | null
  latency_p50: GraphMetricValue | null
}

export type EvidenceClass = 'measured' | 'statistical' | 'replayed' | 'heuristic' | 'inferred' | 'unavailable'

export interface GraphLatencyStats {
  count: number
  mean_ms: number | null
  p50_ms: number | null
  p95_ms: number | null
}

export interface PipelineGraphNode {
  node_id: string
  label: string
  op_type: string
  depth: number
  branch_id: string | null
  candidate_count: number
  metrics: PipelineGraphNodeMetrics
  is_merge: boolean
  source: EvidenceClass
  input_candidate_count: number
  observed_count: number
  trace_coverage: number
  fire_rate: number
  status_counts: Record<string, number>
  cache_hits: number
  latency: GraphLatencyStats
  is_final_output: boolean
  final_output_count: number
  configured: boolean | null
  availability: Record<string, EvidenceClass>
}

export interface PipelineGraphEdge {
  source: string
  target: string
  kind: 'flow' | 'fan_in'
  observed_count: number
  trace_coverage: number
  conditional: boolean
  source_evidence: EvidenceClass
}

export interface PipelineGraph {
  pipeline_id: string
  contract_version: 2
  projection_mode: 'run_union' | 'trace'
  trace_count: number
  complete_trace_count: number
  status_counts: Record<string, number>
  final_output_ids: string[]
  timing_semantics: Record<string, string>
  warnings: string[]
  nodes: PipelineGraphNode[]
  edges: PipelineGraphEdge[]
}

export async function fetchPipelineGraphs(dbId: string, runId: string, traceId?: string): Promise<PipelineGraph[]> {
  const query = traceId ? `?trace_id=${encodeURIComponent(traceId)}` : ''
  const res = await fetch(`${runBase(dbId, runId)}/pipeline-graph${query}`)
  if (!res.ok) throw new Error(`Failed to fetch pipeline graph for run ${runId}`)
  const body = await res.json()
  return body.pipelines ?? []
}

export interface PipelineDiagnostics {
  n: number
  labels: Record<string, number>
  difficulty_buckets: Record<string, number>
}

export interface RunOverview {
  report: RunReport
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

export interface RunReport {
  schema_version: number
  kind: 'run' | 'comparison'
  run_id: string
  title: string
  verdict: 'needs_attention' | 'no_diagnosed_failures' | 'partial' | string
  conclusion: string
  evidence_health: 'ready' | 'limited' | string
  evidence_reasons: string[]
  dominant_issue: { label: string; query_count: number } | null
  affected_queries: Array<{ query_id: string; pipeline_id: string; failure_labels: string[] }>
  next_action: string
  reproduce: string
  dashboard_url: string
}

export async function fetchRunOverview(dbId: string, runId: string): Promise<RunOverview> {
  const res = await fetch(`${runBase(dbId, runId)}/overview`)
  if (!res.ok) throw new Error(`Failed to fetch overview for run ${runId}`)
  return res.json()
}

export async function fetchRunReport(dbId: string, runId: string): Promise<RunReport> {
  const res = await fetch(`${runBase(dbId, runId)}/report`)
  if (!res.ok) throw new Error(`Failed to fetch report for run ${runId}`)
  return res.json()
}

export interface QueryDiagnostic {
  query_id: string
  pipeline_id: string
  difficulty_bucket: string
  failure_labels: string[]
  diagnostic_evidence: Array<{
    label: string
    evidence_class: EvidenceClass
    method: string
    reason: string
    doc_ids: string[]
    threshold: string | null
  }>
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

export interface OperatorAttributionRow {
  op_id: string
  segment: string
  metric: string
  k: number
  delta: number | null
  ci_low: number | null
  ci_high: number | null
  n_pairs: number
  replay_policy: 'EXACT' | 'OBSERVED_ABLATION' | 'NOT_REPLAYABLE'
  result_status: string
  low_power?: boolean
  fire_rate?: number
  significant?: boolean | null
  p_value?: number | null
  q_value?: number | null
  evidence_class: EvidenceClass
  reason?: string | null
  unsupported_descendants: string[]
  assumptions?: Record<string, unknown> | null
}

// ── Candidate Flow Visualization (Pillar 2) ──
export interface CandidateEvent {
  op_id: string
  op_name: string
  op_type: string
  status: string
  event: 'introduced' | 'passed' | 'dropped' | 'incomplete'
  input_rank: number | null
  output_rank: number | null
  score: number | null
  score_delta: number | null
  add_reason: string | null
  drop_reason: string | null
  drop_reason_inferred: boolean
  origin_op_ids: string[]
  lineage_evidence: LineageEvidence
  note: string
}

export interface CandidateHistory {
  doc_id: string
  trace_id: string
  query_id: string
  introduced_at: string | null
  introduced_by_arms: string[]
  dropped_at: string | null
  dropped_reason: string | null
  survived: boolean
  final_rank: number | null
  lineage_evidence: LineageEvidence
  events: CandidateEvent[]
}

export type LineageEvidence = 'recorded' | 'legacy_inferred' | 'partial' | 'unavailable'
export type CandidateOutcomeKind =
  | 'relevant_retained'
  | 'irrelevant_removed'
  | 'irrelevant_retained'
  | 'relevant_lost_upstream'
  | 'relevant_dropped_at_stage'
  | 'unknown_relevance'
  | 'lineage_incomplete'

export interface CandidateSource {
  document_id: string | null
  document_revision: string | null
  content_hash: string | null
  char_start: number | null
  char_end: number | null
  preview: string | null
}

export interface CandidateLineageStage {
  op_id: string
  op_type: string
  branch_id: string | null
  rank: number
  score: number
  score_components: Record<string, number>
}

export interface CandidateRoute {
  candidate_ids: string[]
  operator_ids: string[]
  branch_ids: string[]
  stages: CandidateLineageStage[]
  lineage_evidence: LineageEvidence
}

export interface CandidateRelevance {
  kind: 'relevant' | 'irrelevant' | 'unknown'
  grade: number | null
  evidence: 'validated' | 'unavailable'
}

export interface CandidateOutcome {
  kind: CandidateOutcomeKind
  evidence: LineageEvidence
  operator_id: string | null
  branch_id: string | null
  reason: string | null
}

export interface CandidatePassport {
  candidate_id: string
  logical_chunk_id: string | null
  source: CandidateSource
  parent_candidate_ids: string[]
  routes: CandidateRoute[]
  relevance: CandidateRelevance
  outcome: CandidateOutcome
  lineage_evidence: LineageEvidence
  final_context_member: boolean
  removed_at: string | null
  removal_branch_id: string | null
  removal_reason: string | null
  removal_evidence: LineageEvidence
  derived_child_ids: string[]
}

export interface LineageReadiness {
  scope: 'lineage_diagnosis'
  status: 'READY' | 'HOLD' | 'BLOCK'
  findings: Array<Record<string, unknown>>
}

export interface CandidateLineageNode extends CandidatePassport {
  node_id: string
  trace_id: string
  pipeline_id: string
}

export interface CandidateLineageEdge {
  source_candidate_id: string
  target_candidate_id: string
  op_id: string
  evidence: LineageEvidence
  trace_id: string
  pipeline_id: string
  source_node_id: string
  target_node_id: string
}

export interface OutcomeCounts {
  relevant_retained: number
  irrelevant_removed: number
  irrelevant_retained: number
  relevant_lost_upstream: number
  relevant_dropped_at_stage: number
  unknown_relevance: number
  lineage_incomplete: number
  unknown_relevance_count?: number
  incomplete_lineage_count?: number
}

export interface StageLossAccounting extends OutcomeCounts {
  by_operator: Record<string, OutcomeCounts>
  by_branch: Record<string, OutcomeCounts>
  by_evidence: Record<string, OutcomeCounts>
  unknown_relevance_count: number
  incomplete_lineage_count: number
}

export interface CandidateLineageResponse {
  run_id: string
  query_id: string
  readiness: LineageReadiness
  evidence_warnings: Array<Record<string, unknown>>
  graph: {
    nodes: CandidateLineageNode[]
    edges: CandidateLineageEdge[]
    candidate_ids: Array<{ trace_id: string; pipeline_id: string; candidate_id: string }>
  }
  accounting: StageLossAccounting
  traces: Array<{
    trace_id: string
    pipeline_id: string
    graph: Record<string, unknown>
    accounting: StageLossAccounting
  }>
}

export interface LineageAccountingResponse {
  run_id: string
  query_id: string
  readiness: LineageReadiness
  evidence_warnings: Array<Record<string, unknown>>
  accounting: StageLossAccounting
  traces: Array<{
    trace_id: string
    pipeline_id: string
    accounting: StageLossAccounting
  }>
}

export async function fetchCandidateLineage(
  dbId: string,
  runId: string,
  queryId: string,
): Promise<CandidateLineageResponse> {
  const res = await fetch(
    `${runBase(dbId, runId)}/queries/${encodeURIComponent(queryId)}/candidate-lineage`,
  )
  if (!res.ok) throw new Error(`Failed to fetch candidate lineage for ${queryId}`)
  return res.json()
}

export type LineageChangeKind =
  | 'newly_surfaced'
  | 'newly_dropped'
  | 'newly_retained'
  | 'rank_shifted'
  | 'branch_changed'
  | 'exit_changed'

export interface CandidateLineageGraphSnapshot {
  trace_id: string
  run_id: string | null
  query_id: string
  pipeline_id: string
  topology_hash: string
  candidates: Record<string, CandidatePassport>
  edges: Array<{
    source_candidate_id: string
    target_candidate_id: string
    op_id: string
    evidence: LineageEvidence
  }>
}

export interface CandidateLineageDiffEntry {
  status: ReadinessStatus
  reasons: string[]
  baseline: CandidateLineageGraphSnapshot
  candidate: CandidateLineageGraphSnapshot
  changed: Array<{
    kind: LineageChangeKind
    logical_chunk_id: string
    document_identity: string
    baseline_candidate_id: string | null
    candidate_candidate_id: string | null
    detail: string
  }>
}

export interface CandidateLineageDiffResponse {
  baseline_run_id: string
  candidate_run_id: string
  query_id: string
  readiness: ClaimReadiness
  diffs: CandidateLineageDiffEntry[]
}

export async function fetchCandidateLineageDiff(
  dbId: string,
  candidateRunId: string,
  baselineRunId: string,
  queryId: string,
): Promise<CandidateLineageDiffResponse> {
  const res = await fetch(
    `${runBase(dbId, candidateRunId)}/queries/${encodeURIComponent(queryId)}/candidate-lineage-diff?against=${encodeURIComponent(baselineRunId)}`,
  )
  if (!res.ok) throw new Error(`Failed to fetch candidate lineage diff for ${queryId}`)
  return res.json()
}

export async function fetchLineageAccounting(
  dbId: string,
  runId: string,
  queryId: string,
): Promise<LineageAccountingResponse> {
  const res = await fetch(
    `${runBase(dbId, runId)}/queries/${encodeURIComponent(queryId)}/lineage-accounting`,
  )
  if (!res.ok) throw new Error(`Failed to fetch lineage accounting for ${queryId}`)
  return res.json()
}

export interface ReplayAssumptions {
  op_id: string
  op_type: string
  strategy: string
  rrf_recomputed: boolean
  rrf_k: number | null
  replay_policy: string
  caveats: string[]
}

export interface CandidateFlowPipeline {
  pipeline_id: string
  trace_id: string
  history: CandidateHistory
  drop_replay_assumptions: ReplayAssumptions | null
}

export interface CandidateFlow extends CandidatePassport {
  run_id: string
  query_id: string
  doc_id: string
  relevant?: boolean | null
  grade?: number | null
  readiness: LineageReadiness
  evidence_warnings: Array<Record<string, unknown>>
  trace_passports: CandidateLineageNode[]
  pipelines: CandidateFlowPipeline[]
}

export async function fetchCandidateFlow(
  dbId: string,
  runId: string,
  queryId: string,
  docId: string,
): Promise<CandidateFlow> {
  const res = await fetch(
    `${runBase(dbId, runId)}/queries/${encodeURIComponent(queryId)}/candidates/${encodeURIComponent(docId)}`,
  )
  if (!res.ok) throw new Error(`Failed to fetch candidate flow for ${docId}`)
  return res.json()
}

export interface CandidateJourneyRow {
  query_id: string
  query_text: string | null
  doc_id: string
  doc_preview: string | null
  pipeline_id: string
  trace_id: string
  relevant: boolean | null
  grade: number | null
  survived: boolean
  final_rank: number | null
  introduced_at: string | null
  dropped_at: string | null
  drop_reason: string | null
  drop_reason_inferred: boolean
  miss_type: string | null
  outcome?: CandidateOutcomeKind
  outcome_evidence?: LineageEvidence
  evidence_class: string
}

export interface CandidateJourneys {
  run_id: string
  query_id: string
  query_text: string | null
  k: number
  rows: CandidateJourneyRow[]
}

export async function fetchCandidateJourneys(
  dbId: string,
  runId: string,
  queryId: string,
  k: number = 10,
): Promise<CandidateJourneys> {
  const res = await fetch(
    `${runBase(dbId, runId)}/queries/${encodeURIComponent(queryId)}/candidate-journeys?k=${k}`,
  )
  if (!res.ok) throw new Error(`Failed to fetch candidate journeys for ${queryId}`)
  return res.json()
}

// ── Comparability guard (Pillar 6) ──
export interface ComparabilityDifference {
  axis: string
  severity: 'high' | 'medium' | 'low'
  status: 'invalid' | 'warning' | 'unknown'
  detail: string
  values: unknown[]
}

export interface ComparabilityReport {
  outcome: 'valid' | 'warning' | 'invalid'
  comparable: boolean
  decision_allowed: boolean
  differences: ComparabilityDifference[]
  required_axes: string[]
}

export interface OperatorDagNode {
  op_id: string
  op_type: string
  op_name: string
  fire_rate: number
  avg_latency_ms: number
}

export interface OperatorDagEdge {
  source: string
  target: string
}

export interface OperatorDag {
  nodes: OperatorDagNode[]
  edges: OperatorDagEdge[]
}

export async function fetchOperatorDag(dbId: string, runId: string): Promise<OperatorDag> {
  const res = await fetch(`${runBase(dbId, runId)}/operator-dag`)
  if (!res.ok) throw new Error(`Failed to fetch operator DAG for run ${runId}`)
  return res.json()
}

export interface OperatorDiff {
  op_id: string
  op_type: string
  replay_policy: string
  result_status: 'replayed' | 'indeterminate'
  evidence_class: EvidenceClass
  reason: string | null
  unsupported_descendants: string[]
  assumptions: ReplayAssumptions
  inputs: Array<{ doc_id: string; score: number; rank: number }>
  outputs: Array<{ doc_id: string; score: number; rank: number }>
  without_operator: Array<{ doc_id: string; score: number; rank: number }>
}

export async function fetchOperatorDiff(
  dbId: string,
  runId: string,
  traceId: string,
  opId: string,
): Promise<OperatorDiff> {
  const res = await fetch(
    `${runBase(dbId, runId)}/traces/${encodeURIComponent(traceId)}/operator/${encodeURIComponent(opId)}/diff`,
  )
  if (!res.ok) throw new Error(`Failed to fetch operator diff`)
  return res.json()
}

// ── Per-query unified timeline (Item C) ──
export interface TraceCandidate {
  doc_id: string
  score: number
  rank: number
  input_rank: number | null
  output_rank: number | null
  origin_op_ids: string[]
  score_components: Record<string, number>
  add_reason: string
  drop_reason: string | null
}

export interface TraceOperatorSpan {
  op_id: string
  op_type: string
  op_name: string
  parent_ids: string[]
  status: 'FIRED' | 'SKIPPED_BY_GATE' | 'ERROR' | 'TIMEOUT'
  deterministic: boolean
  replay_policy: 'EXACT' | 'OBSERVED_ABLATION' | 'NOT_REPLAYABLE'
  latency_ms: number
  inputs?: TraceCandidate[]
  outputs: TraceCandidate[]
  params: Record<string, unknown>
  gate_values: Record<string, unknown>
  input_variant: string
  error: string | null
  inputs_total?: number
  inputs_truncated?: boolean
  outputs_total?: number
  outputs_truncated?: boolean
}

export interface RetrievalTrace {
  trace_id: string
  run_id: string
  query_id: string
  query_text: string
  pipeline_id: string
  spans: TraceOperatorSpan[]
  total_latency_ms?: number
  timing?: { wall_clock_ms: number; critical_path_ms: number; operator_sum_ms: number }
  status: 'OK' | 'TIMEOUT' | 'ERROR'
  timestamp: string
  metadata: Record<string, unknown>
  error_traceback: string | null
  final_op_id: string | null
}

/** All V2 traces for a run. Used to build the per-query unified timeline (Item C) --
 * there is no per-query filter on the backend, so callers filter client-side by query_id. */
export async function fetchRunTraces(dbId: string, runId: string, limit = 50): Promise<RetrievalTrace[]> {
  const res = await fetch(`${runBase(dbId, runId)}/traces?limit=${limit}`)
  if (!res.ok) throw new Error(`Failed to fetch traces for run ${runId}`)
  return res.json()
}

export interface QueryEvidence {
  schema_version: 1
  scope: { db_id: string; run_id: string; query_id: string }
  query: { query_id: string; text: string | null; dataset_name: string | null }
  ground_truth: { relevant_doc_ids: string[]; grades: Record<string, number>; evidence_class: EvidenceClass }
  diagnostics: QueryDiagnostic[]
  traces: RetrievalTrace[]
  trace_pagination: {
    limit: number
    offset: number
    returned: number
    has_more: boolean
    next_offset: number | null
  }
  origin: QueryLineage['origin'] | null
  regression_history: QueryLineage['evaluations']
  production_matches: QueryLineage['production_matches'] | null
  findings: Recommendation[]
  availability: Record<string, EvidenceClass>
  evidence_health: {
    status: 'ok' | 'warning'
    complete_trace_count: number
    partial_trace_count: number
    warnings: string[]
  }
}

export async function fetchQueryEvidence(
  dbId: string,
  runId: string,
  queryId: string,
  traceOffset = 0,
): Promise<QueryEvidence> {
  const params = new URLSearchParams({ trace_limit: '20', trace_offset: String(traceOffset), candidate_limit: '100' })
  const res = await fetch(`${runBase(dbId, runId)}/queries/${encodeURIComponent(queryId)}/evidence?${params.toString()}`)
  if (!res.ok) throw new Error(`Failed to fetch query evidence for ${queryId}`)
  return res.json()
}

export interface MissAttributionRow {
  query_id: string
  doc_id: string
  miss_type: string
  op_id: string | null
  confidence: string
  note: string
}

export async function fetchMissAttribution(
  dbId: string,
  runId: string,
  traceId: string,
  k: number = 10,
): Promise<MissAttributionRow[]> {
  const res = await fetch(
    `${runBase(dbId, runId)}/traces/${encodeURIComponent(traceId)}/miss-attribution?k=${k}`,
  )
  if (!res.ok) throw new Error(`Failed to fetch miss attribution`)
  return res.json()
}

export async function fetchOperatorAttribution(
  dbId: string,
  runId: string,
  metric: string = 'recall',
  k: number = 10,
): Promise<OperatorAttributionRow[]> {
  const res = await fetch(
    `${runBase(dbId, runId)}/operator-attribution?metric=${encodeURIComponent(metric)}&k=${k}`,
  )
  if (!res.ok) throw new Error(`Failed to fetch operator attribution for run ${runId}`)
  return res.json()
}

export interface QueryWinnerRow {
  query_id: string
  winner_pipeline_id: string | null
  score?: number
  status: 'measured' | 'not_judged'
}

export async function fetchQueryWinners(
  dbId: string,
  runId: string,
  metric: string = 'recall',
  k: number = 10,
): Promise<{ run_id: string; metric: string; k: number; items: QueryWinnerRow[] }> {
  const res = await fetch(
    `${runBase(dbId, runId)}/query-winners?metric=${encodeURIComponent(metric)}&k=${k}`,
  )
  if (!res.ok) throw new Error(`Failed to fetch query winners for run ${runId}`)
  return res.json()
}

export interface ParetoPipelineMetrics {
  'ndcg@10': number
  'recall@10': number
  latency_p50: number
  latency_p95: number
  cost_per_1k: number | null
  'ndcg@10_ci_low'?: number | null
  'ndcg@10_ci_high'?: number | null
  'recall@10_ci_low'?: number | null
  'recall@10_ci_high'?: number | null
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
  omitted_pipelines?: string[]
  omitted_reason?: string | null
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

export interface QueryResultDocument {
  id: string
  score: number
  rank: number
}

export interface QueryResultStage {
  stage_index: number
  stage_id: string
  latency_ms: number
  profiling?: unknown
  candidate_count: number | null
  documents: QueryResultDocument[]
}

export interface QueryResultPipeline {
  pipeline_id: string
  status: string
  total_latency_ms: number
  stages: QueryResultStage[]
}

export interface QueryResult {
  run_id: string
  query_id: string
  diagnostics: Record<string, unknown>[]
  results: QueryResultPipeline[]
}

/** Full per-pipeline/per-stage/per-document result for one query -- the "raw documents"
 * disclosure level, and the data source for Item C's unified query timeline. */
export async function fetchQueryResult(dbId: string, runId: string, queryId: string): Promise<QueryResult> {
  const res = await fetch(`${runBase(dbId, runId)}/queries/${encodeURIComponent(queryId)}`)
  if (!res.ok) throw new Error(`Failed to fetch query result for ${queryId}`)
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

// ───────────────────────── Test Sets ─────────────────────────

export interface ForgeDatasetSummary {
  schema_version: 1
  dataset_id: string
  total_queries: number
  total_scenarios: number
  corpus_size: number
  validated: number
  validation_coverage: number
  by_difficulty: Record<string, number>
  by_query_type: Record<string, number>
  by_scenario_type: Record<string, number>
  created_at: string | null
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
  provenance: {
    generation_method?: string
    generation_model?: string | null
    label_method?: string
    judge_model?: string | null
  }
}

export interface ForgeRunRef {
  run_id: string
  experiment_name: string
  started_at: string
}

export async function fetchForgeDatasets(dbId: string): Promise<ForgeDataset[]> {
  const res = await fetch(`${dbBase(dbId)}/forge/datasets`)
  if (!res.ok) throw new Error('Failed to fetch Test Sets')
  return res.json()
}

export async function fetchForgeDataset(dbId: string, datasetId: string): Promise<ForgeDatasetDetail> {
  const res = await fetch(`${dbBase(dbId)}/forge/datasets/${encodeURIComponent(datasetId)}`)
  if (!res.ok) throw new Error(`Failed to fetch Test Set ${datasetId}`)
  return res.json()
}

export async function fetchForgeQueries(
  dbId: string,
  datasetId: string,
  filters: { scenario_type?: string; difficulty?: string; query_type?: string; validated_only?: boolean; limit?: number; offset?: number } = {},
): Promise<ForgeQuery[]> {
  const params = new URLSearchParams()
  if (filters.scenario_type) params.set('scenario_type', filters.scenario_type)
  if (filters.difficulty) params.set('difficulty', filters.difficulty)
  if (filters.query_type) params.set('query_type', filters.query_type)
  if (filters.validated_only) params.set('validated_only', 'true')
  if (filters.limit) params.set('limit', String(filters.limit))
  if (filters.offset) params.set('offset', String(filters.offset))
  const qs = params.toString()
  const res = await fetch(`${dbBase(dbId)}/forge/datasets/${encodeURIComponent(datasetId)}/queries${qs ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error(`Failed to fetch queries for Test Set ${datasetId}`)
  const page: { items: ForgeQuery[] } = await res.json()
  return page.items
}

export async function fetchForgeDatasetRuns(dbId: string, datasetId: string): Promise<ForgeRunRef[]> {
  const res = await fetch(`${dbBase(dbId)}/forge/datasets/${encodeURIComponent(datasetId)}/runs`)
  if (!res.ok) throw new Error(`Failed to fetch runs for Test Set ${datasetId}`)
  return res.json()
}

// ───────────────────────── Production ─────────────────────────

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

export interface Page<T> { items: T[]; total: number; limit: number; offset: number; next_offset: number | null }
export interface TopologyVariant { topology_hash?: string; variant_id?: string; trace_count?: number; count?: number; operator_ids?: string[]; first_seen?: string; last_seen?: string }

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
  threshold: number
  baseline_n: number
  recent_n: number
  evidence_class: 'statistical'
  supporting_trace_ids: string[]
  baseline_window: { since: string; until: string }
  recent_window: { since: string; until: string | null }
  sample_limited: boolean
}

export interface FailureHotspot {
  segment: string
  difficulty: string
  label: string
  pipeline: string
  count: number
  rate: number
  evidence_class: 'heuristic'
  method: string
  sample_size: number
  denominator: number
  baseline: string
  threshold: null
  supporting_trace_ids: string[]
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
  const p = new URLSearchParams({ service_id: service })
  if (since) p.set('since', since)
  return p.toString()
}

export async function fetchTraceServices(dbId: string): Promise<TraceService[]> {
  const res = await fetch(`${dbBase(dbId)}/production/services`)
  return parseJson(res, 'Failed to fetch trace services')
}

export async function fetchTraceSummary(dbId: string, service: string, since?: string): Promise<TraceSummary> {
  const res = await fetch(`${dbBase(dbId)}/production/summary?${windowParams(service, since)}`)
  return parseJson(res, 'Failed to fetch trace summary')
}

export async function fetchTraces(
  dbId: string,
  service: string,
  filters: { since?: string; status?: string; difficulty?: string; suspected_only?: boolean; limit?: number; offset?: number } = {},
): Promise<Page<TraceRow>> {
  const p = new URLSearchParams({ service_id: service })
  if (filters.since) p.set('since', filters.since)
  if (filters.status) p.set('status', filters.status)
  if (filters.difficulty) p.set('difficulty', filters.difficulty)
  if (filters.suspected_only) p.set('suspected_only', 'true')
  p.set('limit', String(filters.limit ?? 100))
  p.set('offset', String(filters.offset ?? 0))
  const res = await fetch(`${dbBase(dbId)}/production/traces?${p.toString()}`)
  return parseJson(res, 'Failed to fetch traces')
}

export async function fetchTopologyVariants(dbId: string, service: string, limit = 50, offset = 0): Promise<Page<TopologyVariant>> {
  const p = new URLSearchParams({ service_id: service, limit: String(limit), offset: String(offset) })
  const res = await fetch(`${dbBase(dbId)}/production/topology-variants?${p.toString()}`)
  return parseJson(res, 'Failed to fetch topology variants')
}

export async function fetchTraceDetail(dbId: string, traceId: string): Promise<TraceDetail> {
  const res = await fetch(`${dbBase(dbId)}/production/traces/${encodeURIComponent(traceId)}`)
  return parseJson(res, `Failed to fetch trace ${traceId}`)
}

export async function fetchTraceDistribution(dbId: string, service: string, since?: string): Promise<TraceDistribution> {
  const res = await fetch(`${dbBase(dbId)}/production/distribution?${windowParams(service, since)}`)
  return parseJson(res, 'Failed to fetch trace distribution')
}

export async function fetchTraceDrift(dbId: string, service: string, baseline?: string, recent?: string): Promise<DriftFinding[]> {
  const p = new URLSearchParams({ service_id: service })
  if (baseline) p.set('baseline', baseline)
  if (recent) p.set('recent', recent)
  const res = await fetch(`${dbBase(dbId)}/production/drift?${p.toString()}`)
  return parseJson(res, 'Failed to fetch drift findings')
}

export async function fetchTraceHotspots(dbId: string, service: string, since?: string): Promise<FailureHotspot[]> {
  const res = await fetch(`${dbBase(dbId)}/production/hotspots?${windowParams(service, since)}`)
  return parseJson(res, 'Failed to fetch failure hotspots')
}

export async function fetchTraceClusters(dbId: string, service: string, since?: string): Promise<QueryClusterRow[]> {
  const res = await fetch(`${dbBase(dbId)}/production/clusters?${windowParams(service, since)}`)
  return parseJson(res, 'Failed to fetch query clusters')
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
    summary: { trace_count: number; service_count: number; failure_labels: string[] }
    traces: QueryLineageTrace[]
  }
}

export async function fetchQueryLineage(dbId: string, queryId: string): Promise<QueryLineage> {
  const res = await fetch(`${dbBase(dbId)}/query/${encodeURIComponent(queryId)}/lineage`)
  if (!res.ok) throw new Error(`Failed to fetch lineage for ${queryId}`)
  return res.json()
}

export interface Recommendation {
  action: string
  rationale: string
  evidence: string[]
  priority: number
  estimated_quality_improvement?: number | null
  quality_metric?: string | null
  estimated_quality_ci?: [number, number] | null
  estimated_latency_increase_ms?: number | null
  implementation_effort?: 'S' | 'M' | 'L' | null
  confidence?: number | null
  affected_query_categories?: string[]
  expected_value?: number | null
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
  validation_run_id?: string
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

export async function fetchAdvisorRecommendations(dbId: string, runId: string): Promise<{ run_id: string; recommendations: Recommendation[] }> {
  const res = await fetch(`${dbBase(dbId)}/advisor/recommendations?run_id=${encodeURIComponent(runId)}`)
  if (!res.ok) throw new Error('Failed to fetch recommendations')
  return res.json()
}

export async function fetchAdvisorRegressions(dbId: string, baseline: string, candidate: string): Promise<{ regressions: RegressionFinding[] }> {
  const p = new URLSearchParams({ baseline, candidate })
  const res = await fetch(`${dbBase(dbId)}/advisor/regressions?${p.toString()}`)
  if (!res.ok) throw new Error('Failed to fetch regressions')
  return res.json()
}

export async function fetchAdvisorReliability(dbId: string, runId: string): Promise<ReliabilityScore & { run_id: string }> {
  const res = await fetch(`${dbBase(dbId)}/advisor/reliability?run_id=${encodeURIComponent(runId)}`)
  if (!res.ok) throw new Error('Failed to fetch reliability score')
  return res.json()
}

export interface ReliabilityHistoryPoint {
  run_id: string
  recorded_at: string
  value: number
  components: Record<string, number>
}

export async function fetchAdvisorReliabilityHistory(dbId: string, runId?: string): Promise<{ history: ReliabilityHistoryPoint[] }> {
  const p = new URLSearchParams()
  if (runId) p.set('run_id', runId)
  const res = await fetch(`${dbBase(dbId)}/advisor/reliability/history?${p.toString()}`)
  if (!res.ok) throw new Error('Failed to fetch reliability history')
  return res.json()
}
