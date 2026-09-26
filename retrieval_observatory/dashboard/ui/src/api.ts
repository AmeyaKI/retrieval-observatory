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
}

export interface RunSelection {
  dbId: string
  runId: string
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
  affected_query_ids?: string[]
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

// ── Release audit (`audit-1`): the one artifact shared by `POST /compare`, the CLI and CI ──
export type AuditStatus = 'PASS' | 'FAIL' | 'BLOCK' | 'HOLD'

export interface AuditSourceRun {
  db_id: string | null
  run_id: string
  experiment_name: string | null
  manifest_schema_version: number | null
  dataset: { name?: string; query_hash?: string; corpus_hash?: string; qrel_hash?: string }
  judgment_digest: string | null
  release_identity: Record<string, unknown> | null
  evaluation: Record<string, unknown> | null
  counts: Record<string, unknown> | null
}

export interface AuditFieldComparison {
  field: string
  baseline: unknown
  candidate: unknown
  equal: boolean
  classification: 'invariant' | 'expected' | 'unexpected' | 'evidence_invalid' | 'unknown'
  finding_code: string | null
}

export interface AuditFinding {
  code: string
  scope: string
  status: string
  observed: unknown
  required: unknown
  detail: string
  next_action: string
}

export interface AuditCheck {
  id: string
  check_id?: string
  metric: string
  target?: string
  status: AuditStatus
  direction: 'higher_is_better' | 'lower_is_better'
  estimator: string
  effect: number | null
  ci_low: number | null
  ci_high: number | null
  tolerance: number
  boundary: number
  max_regression: number
  paired_n: number
  attempted_n: number
  min_paired_n: number
  pair_coverage: number | null
  confidence_level: number
  adjusted_confidence_level: number
  resamples: number
  seed: number
  interval_method: string
  sample_limitation: string | null
  affected_query_ids: string[]
  resolution_status?: string
  metric_key_by_run?: Record<string, string | null>
}

export interface AuditOperationalRun {
  run_id: string
  attempted_n: number | null
  failed_n: number
  failure_rate: number | null
}

export interface ReleaseAudit {
  schema_version: 'audit-1'
  generated_at: string
  tool: { retrieval_observatory: string; python: string }
  decision: { status: AuditStatus; reasons: string[]; next_action: string; exit_code: 0 | 1 | 2 | 3 }
  sources: { baseline: AuditSourceRun; candidate: AuditSourceRun }
  policy: {
    configured: boolean
    id: string | null
    schema_version: number | null
    digest: string | null
    source: string | null
    resolution: Record<string, unknown> | null
    conversion: Record<string, unknown> | null
  }
  evaluation: { unit: string | null; boundary: string | null; k: number | null; relevance_threshold: number | null; comparison_scope: string | null }
  compatibility: {
    status: 'READY' | 'HOLD' | 'BLOCK'
    findings: AuditFinding[]
    provenance: {
      invariants: AuditFieldComparison[]
      interventions: AuditFieldComparison[]
      consistency: AuditFieldComparison[]
      unknown_fields: string[]
    }
    validity: Record<string, unknown>
  }
  readiness: Record<string, { scope: string; status: string; findings: { code: string; detail: string; next_action: string; status: string }[] }>
  coverage: {
    expected_query_count: number | null
    min_pair_coverage: number | null
    per_check: Record<string, { attempted_n: number; paired_n: number; pair_coverage: number | null }>
  }
  checks: AuditCheck[]
  slices: { id: string; field: string; value: unknown; status: string; paired_n: number; sample_limitation: string | null; guards: AuditCheck[] }[]
  operational: {
    status: 'PASS' | 'BLOCK' | 'FAIL'
    code: string | null
    max_failure_rate: number
    baseline: AuditOperationalRun
    candidate: AuditOperationalRun
    detail: string
  } | null
  statistics: {
    confidence_level: number | null
    familywise_alpha: number | null
    resamples: number | null
    seed: number | null
    interval_method: string | null
    family_size: number | null
    adjusted_confidence_level: number | null
  }
  investigation: {
    scope: { db_id: string | null; baseline_run_id: string; candidate_run_id: string; pipeline_id: string | null }
    changed_queries: { query_id: string; metric: string; baseline: number; candidate: number; delta: number; link: string }[]
    dashboard_base_url: string
    requires_local_dashboard: boolean
  }
  metrics: Record<string, { baseline_mean: number | null; candidate_mean: number | null; effect: number | null; q_value: number | null; paired_n: number; decision: string }>
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
  /** delta = b - a (candidate minus baseline): positive means the candidate scored higher. */
  orientation?: {
    a: 'baseline'
    b: 'candidate'
    effect: 'candidate_minus_baseline'
    baseline: { db_id: string; run_id: string }
    candidate: { db_id: string; run_id: string }
  }
  rows: QueryDiffRow[]
}

export async function fetchComparison(
  selections: RunSelection[],
  policyPath?: string,
): Promise<{
  comparison: ComparisonEntry[]
  selections: Array<{ db_id: string; run_id: string }>
  run_ids: string[]
  warnings: string[]
  comparability?: ComparabilityReport
  query_diffs?: QueryDiffs | null
  release_decision?: ReleaseDecision | null
  audit?: ReleaseAudit | null
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
      ...(policyPath ? { policy_path: policyPath } : {}),
    }),
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`Failed to fetch comparison (${res.status}): ${body || res.statusText}`)
  }
  return res.json()
}

// ── PipelineGraph render contract (mirrors dashboard/pipeline_graph.schema.json) ──
export interface GraphMetricValue {
  mean: number | null
  ci_low: number | null
  ci_high: number | null
  k?: number | null
  /** Queries the aggregate covers; smaller than the run total for a gate-skipped branch. */
  n?: number | null
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

export interface DemoContext {
  baseline_run_id?: string
  candidate_run_id?: string
  validation_run_id?: string
  ablation_run_id?: string
  sample_query_id?: string
  /** Registry id of the database the demo manifest belongs to; apply the run ids there. */
  db_id?: string
  db_path?: string
  experiment_names?: Record<string, string>
}

export async function fetchDemoContext(): Promise<DemoContext> {
  const res = await fetch(`${BASE}/demo/context`)
  if (!res.ok) throw new Error('Failed to fetch demo context')
  return res.json()
}

export interface InvestigationScope {
  run_id: string
  pipeline_id: string
  boundary: string
  unit: 'document' | 'chunk'
  k: number | null
  relevance_threshold: number
  evaluation_digest: string
  judgment_digest: string
  query_id?: string
  trace_id?: string
  entity?: string
  /** What `rows` holds: stored per-query summaries (unfiltered queries list), document summaries, or candidate pairs. */
  rows_kind?: 'query_summaries' | 'document_summaries' | 'pairs'
}

export interface InvestigationCapabilities {
  projection: 'ready' | 'partial' | 'unavailable'
  judgments: 'ready' | 'unavailable'
  capture: { complete_rows: number; partial_rows: number }
}

export interface InvestigationCoverage {
  queries_attempted: number | null
  queries_with_traces: number | null
  queries_projected: number | null
  pairs: number | null
  events: number | null
}

export interface JourneyEvent {
  op_id: string
  operator_id: string
  invocation_id: string | null
  branch: string | null
  occurrence_entity_id: string
  candidate_id: string
  kind: 'introduced' | 'retained' | 'promoted' | 'demoted' | 'removed' | 'recovered' | 'transformed' | 'unknown'
  input_present: boolean
  output_present: boolean
  input_rank: number | null
  output_rank: number | null
  input_occurrences: number
  reason: string | null
  reason_evidence: 'recorded' | 'inferred' | 'unavailable'
  boundary_complete: boolean
  input_evidence: string
  source_occurrences: string[]
  /** Optional captured content (`text`, `title`, `preview`); absent from the projection today. */
  metadata?: Record<string, unknown> | null
}

export interface JourneyRow {
  schema_version: number
  derivation_version: string
  run_id: string | null
  pipeline_id: string
  trace_id: string
  query_id: string
  namespace: string
  entity_id: string
  unit: 'document' | 'chunk'
  entity_revision: string | null
  judgment: 'relevant' | 'nonrelevant' | 'unjudged' | 'unmapped'
  grade: number | null
  judgment_source: string | null
  final_membership: 'included' | 'excluded' | 'unknown'
  in_final_output: boolean | null
  final_rank: number | null
  outcome:
    | 'relevant_delivered'
    | 'relevant_excluded'
    | 'retained_below_cutoff'
    | 'not_observed'
    | 'judged_nonrelevant'
    | 'unjudged'
    | 'insufficient_evidence'
  confusion: 'TP' | 'FP' | 'FN' | 'TN' | 'unknown'
  capture_state: 'complete' | 'partial'
  observed: boolean
  loss_boundary: string | null
  priority: number
  events: JourneyEvent[]
  occurrence_entity_ids: string[]
  evaluation_digest: string
  judgment_digest: string
  trace_digest: string
  investigation_link: string
  /** Optional captured content (`text`, `title`, `preview`); absent from the projection today. */
  metadata?: Record<string, unknown> | null
}

export interface InvestigationStage {
  op_id: string
  operator_id: string
  invocation_id: string | null
  op_type: string
  status: string
  branch: string | null
  parent_ids: string[]
  input_capture: string
  output_capture: string
  received: number
  emitted: number
  removed: number
  introduced: number
  source_ref?: string | null
  params?: Record<string, unknown>
  gate_values?: Record<string, unknown>
  error?: string | null
}

/** Stored per-operator aggregate over every trace of the scope (list envelopes only). */
export interface StageSummary {
  op_id: string
  operator_id: string
  queries_served: number
  queries_skipped: number
  candidates_received: number
  removal_events: number
  introduced: number
  partial_boundaries: number
}

export function isStageSummary(stage: InvestigationStage | StageSummary): stage is StageSummary {
  return 'queries_served' in stage
}

export interface InvestigationFinding {
  code: string
  detail: string
  action: string
}

/** Document-view rows are entity summaries; query views carry JourneyRow. */
export interface InvestigationDocumentRow {
  entity: string
  queries: number
  delivered: number
  excluded: number
  not_observed: number
  unknown: number
  judged_relevant_queries: string[]
}

/** Queries-view rows once the projection is complete and no pair-level filter is set: the stored per-query summaries. */
export interface QuerySummaryRow {
  query_id: string
  query_text: string | null
  pairs: number
  TP: number
  FP: number
  FN: number
  TN: number
  unknown: number
  relevant_excluded: number
  insufficient: number
  capture_partial: number
  relevant_delivered: number
  relevant_missed: number
  unjudged_included: number
  unknown_capture: number
  /** Final loss boundary → pair count, including `not_observed` and `unknown` when present. */
  loss_boundaries: Record<string, number>
  trace_ids: string[]
}

export interface InvestigationEnvelope<Row = JourneyRow> {
  schema_version: number
  scope: InvestigationScope
  capabilities: InvestigationCapabilities
  coverage: InvestigationCoverage
  rows: Row[]
  total: number | null
  next_cursor: string | null
  summary: Record<string, unknown> | null
  /** Per-trace spans on a query envelope; stored aggregates on a list envelope; null when unavailable. */
  stages: InvestigationStage[] | StageSummary[] | null
  findings: InvestigationFinding[]
}

// Run comparison (paired journey rows): .../investigation/runs/{candidate}/compare[/{query}]?against={baseline}

export type JourneyChangeKind = 'lost' | 'gained' | 'membership_changed' | 'rank_changed' | 'path_changed' | 'unchanged' | 'unaligned'
export type JourneyAlignment =
  | 'aligned'
  | 'query_unaligned'
  | 'entity_revision_changed'
  | 'missing_in_baseline'
  | 'missing_in_candidate'
  | 'corpus_changed'

export interface JourneySide {
  trace_id: string
  outcome: JourneyRow['outcome']
  final_membership: JourneyRow['final_membership']
  in_final_output: boolean | null
  final_rank: number | null
  loss_boundary: string | null
  capture_state: 'complete' | 'partial'
  judgment: JourneyRow['judgment']
  grade: number | null
  /** `op_id:kind` per event, e.g. `select:removed`. */
  events_summary: string[]
  investigation_link: string
}

export interface JourneyDiffRow {
  query_id: string
  namespace: string
  entity_id: string
  unit: 'document' | 'chunk'
  alignment: JourneyAlignment
  change: JourneyChangeKind
  /** e.g. `included at rank 3 → excluded (select)` */
  detail: string
  /** null when the entity has no row in that run */
  baseline: JourneySide | null
  candidate: JourneySide | null
  capture_limited: boolean
  /** 0 lost, 1 gained, 2 membership_changed, 3 rank_changed, 4 path_changed, 5 unaligned, 6 unchanged */
  priority: number
}

export interface StageAlignment {
  /** [baseline op_id, candidate op_id] */
  matched: [string, string][]
  baseline_only: string[]
  candidate_only: string[]
}

export interface ProvenanceFieldComparison {
  field: string
  baseline: unknown
  candidate: unknown
  equal: boolean
  classification: 'invariant' | 'expected' | 'unexpected' | 'evidence_invalid' | 'unknown'
  finding_code: string | null
}

export interface ComparisonCompatibility {
  provenance: {
    invariants: ProvenanceFieldComparison[]
    interventions: ProvenanceFieldComparison[]
    consistency: ProvenanceFieldComparison[]
    unknown_fields: string[]
  }
  findings: EvidenceFinding[]
  corpus_changed: boolean
  query_inputs_identical: boolean | null
}

export interface ComparisonSummary {
  pairs: number
  by_change: Record<string, number>
  by_alignment: Record<string, number>
  capture_limited: number
}

export interface ComparisonEnvelope extends InvestigationEnvelope<JourneyDiffRow> {
  comparison: {
    baseline_run_id: string
    candidate_run_id: string
    compatibility: ComparisonCompatibility
    /** Only on the single-query route. */
    stage_alignment: StageAlignment | null
    summary: ComparisonSummary
  }
}

export interface InvestigationProjection {
  status: 'building' | 'complete' | 'failed' | 'unavailable'
  run_id?: string
  pipeline_id?: string
  evaluation_digest?: string
  derivation_version?: string
  judgment_digest?: string
  trace_count?: number
  row_count?: number
  started_at?: string
  finished_at?: string | null
  error?: string | null
}

export type InvestigationParams = Record<string, string | number | undefined | null>

function investigationBase(dbId: string, runId: string): string {
  return `${dbBase(dbId)}/investigation/runs/${encodeURIComponent(runId)}`
}

function investigationQuery(params: InvestigationParams): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

export async function fetchInvestigationQueries(dbId: string, runId: string, params: InvestigationParams = {}): Promise<InvestigationEnvelope<JourneyRow | QuerySummaryRow>> {
  const res = await fetch(`${investigationBase(dbId, runId)}/queries${investigationQuery(params)}`)
  return parseJson<InvestigationEnvelope<JourneyRow | QuerySummaryRow>>(res, 'fetchInvestigationQueries')
}

export async function fetchInvestigationQuery(dbId: string, runId: string, queryId: string, params: InvestigationParams = {}): Promise<InvestigationEnvelope> {
  const res = await fetch(`${investigationBase(dbId, runId)}/queries/${encodeURIComponent(queryId)}${investigationQuery(params)}`)
  return parseJson<InvestigationEnvelope>(res, 'fetchInvestigationQuery')
}

/** `runId` is the candidate run; `params.against` names the baseline run. */
export async function fetchInvestigationComparison(dbId: string, runId: string, params: InvestigationParams = {}): Promise<ComparisonEnvelope> {
  const res = await fetch(`${investigationBase(dbId, runId)}/compare${investigationQuery(params)}`)
  return parseJson<ComparisonEnvelope>(res, 'fetchInvestigationComparison')
}

export async function fetchInvestigationComparisonQuery(dbId: string, runId: string, queryId: string, params: InvestigationParams = {}): Promise<ComparisonEnvelope> {
  const res = await fetch(`${investigationBase(dbId, runId)}/compare/${encodeURIComponent(queryId)}${investigationQuery(params)}`)
  return parseJson<ComparisonEnvelope>(res, 'fetchInvestigationComparisonQuery')
}

export async function fetchInvestigationDocuments(dbId: string, runId: string, params: InvestigationParams = {}): Promise<InvestigationEnvelope<InvestigationDocumentRow>> {
  const res = await fetch(`${investigationBase(dbId, runId)}/documents${investigationQuery(params)}`)
  return parseJson<InvestigationEnvelope<InvestigationDocumentRow>>(res, 'fetchInvestigationDocuments')
}

export async function fetchInvestigationDocument(dbId: string, runId: string, entity: string, params: InvestigationParams = {}): Promise<InvestigationEnvelope> {
  const res = await fetch(`${investigationBase(dbId, runId)}/documents/${encodeURIComponent(entity)}${investigationQuery(params)}`)
  return parseJson<InvestigationEnvelope>(res, 'fetchInvestigationDocument')
}

export async function buildInvestigationProjection(
  dbId: string,
  runId: string,
  body: { pipeline_id?: string; unit?: 'document' | 'chunk'; k?: number } = {},
): Promise<InvestigationProjection> {
  const res = await fetch(`${investigationBase(dbId, runId)}/projection`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return parseJson<InvestigationProjection>(res, 'buildInvestigationProjection')
}

// ---------------------------------------------------------------------------
// Connect: persisted integration verification records (dashboard/integration_api.py).
// ---------------------------------------------------------------------------

export const CAPABILITY_NAMES = [
  'topology_observed',
  'actual_input_output_capture',
  'candidate_identity',
  'query_identity',
  'final_output_capture',
  'judgment_mapping',
  'declared_route_coverage',
  'cross_run_entity_alignment',
] as const

export type CapabilityName = (typeof CAPABILITY_NAMES)[number]
export type IntegrationStatus = 'ready' | 'partial' | 'failed'
export type IntegrationDepth = 'internal' | 'final_only'
export type CapabilityStatus = 'ready' | 'partial' | 'unavailable'

export interface IntegrationSummary {
  integration_id: string
  service_id: string
  pipeline_id: string
  plan_id: string
  status: IntegrationStatus
  depth: IntegrationDepth
  verified_at: string
  version: number
}

export interface CapabilityFailure {
  code: string
  detail: string
  fix: string
  op_id: string | null
}

export interface CapabilityReport {
  status: CapabilityStatus
  evidence: Record<string, unknown>
  scope: string
  failures: CapabilityFailure[]
}

export interface IntegrationOperator {
  op_id: string
  op_type: string
  symbol: string
  relative_path: string
  parent_ids: string[]
  confidence: number
  input_mapping: string
  output_mapping: string
  capture: string | null
  invocation: 'sync' | 'async'
}

export interface IntegrationScenario {
  scenario_id: string
  query_text: string
  expected_operator_ids: string[]
  expected_edges: [string, string][]
  command: string | null
  route: string | null
}

export interface PlannedAction {
  kind: 'install' | 'source_edit' | 'benchmark_setup' | 'scenario_execution'
  description: string
  command: string | null
  performed_by: 'apply' | 'user'
}

export interface IntegrationRecord extends IntegrationSummary {
  schema_version: number
  project_root: string
  db_path: string
  created_at: string
  capabilities: Record<CapabilityName, CapabilityReport>
  errors: string[]
  observed_operator_ids: string[]
  operators: IntegrationOperator[]
  scenarios: IntegrationScenario[]
  boundary: { kind: 'entrypoint_return' | 'operator_output' | 'unresolved'; symbol: string | null; relative_path: string | null; op_id: string | null }
  identity: {
    candidate_id_field: string
    unit: 'document' | 'chunk'
    namespace: string
    corpus_revision: string | null
    query_id: string
    query_text_parameter: string | null
  }
  judgments: { queries?: string | null; qrels?: string | null; corpus?: string | null; status?: 'resolved' | 'unresolved'; notes?: string[] }
  expected_capabilities: Record<string, CapabilityStatus>
  actions: PlannedAction[]
  open_questions: string[]
  unresolved: string[]
  telemetry_health: Record<string, unknown>
  release_readiness: Record<string, unknown>
  /** The newest run carrying this pipeline, or null before the benchmark has been run. */
  investigation: { run_id: string; pipeline_id: string } | null
}

export async function fetchIntegrations(dbId: string): Promise<IntegrationSummary[]> {
  const res = await fetch(`${dbBase(dbId)}/integrations`)
  const body = await parseJson<{ integrations: IntegrationSummary[] }>(res, 'fetchIntegrations')
  return body.integrations ?? []
}

export async function fetchIntegration(dbId: string, integrationId: string): Promise<IntegrationRecord> {
  const res = await fetch(`${dbBase(dbId)}/integrations/${encodeURIComponent(integrationId)}`)
  return parseJson<IntegrationRecord>(res, 'fetchIntegration')
}
