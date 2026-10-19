import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'
// api.ts reads window.location.origin at import time; the node test environment has no window.
vi.hoisted(() => {
  ;(globalThis as { window?: unknown }).window = { location: { origin: 'http://localhost' } }
})
import type { FlowStep, InvestigationDocumentRow, InvestigationFlow, InvestigationStage, JourneyEvent, JourneyRow, PipelineGraph, PipelineGraphNode, QuerySummaryRow, StageSummary } from '../api'
import { DEFAULT_SELECTION } from '../context/dashboardQuery'
import { nextIndexForKey } from '../utils/queryDebugger'
import InvestigationDetail from './InvestigationDetail'
import InvestigationGraph, { FlowTable, StepCard } from './InvestigationGraph'
import InvestigationTable from './InvestigationTable'
import { modeFor, settleBuild, singleFlight } from './InvestigateWorkspace'
import OperatorInspector from './OperatorInspector'

// Fixtures mirror tests/fixtures/investigation_cases.py (golden-hybrid).

const BRANCH: Record<string, string> = { dense: 'dense', 'rerank@dense': 'dense', lexical: 'lexical', recency_filter: 'lexical', 'rerank@lexical': 'lexical' }

function event(op_id: string, kind: JourneyEvent['kind'], input_rank: number | null, output_rank: number | null, extra: Partial<JourneyEvent> = {}): JourneyEvent {
  return {
    op_id,
    operator_id: op_id.startsWith('rerank@') ? 'rerank' : op_id,
    invocation_id: `inv-${op_id}`,
    branch: BRANCH[op_id] ?? null,
    occurrence_entity_id: 'chunk-1',
    candidate_id: 'chunk-1',
    kind,
    input_present: input_rank != null,
    output_present: output_rank != null,
    input_rank,
    output_rank,
    input_occurrences: input_rank != null ? 1 : 0,
    reason: kind === 'introduced' ? 'retrieved' : null,
    reason_evidence: 'recorded',
    boundary_complete: true,
    input_evidence: 'recorded',
    source_occurrences: [],
    ...extra,
  }
}

function row(overrides: Partial<JourneyRow>): JourneyRow {
  return {
    schema_version: 1,
    derivation_version: 'journeys-v1',
    run_id: 'golden-run',
    pipeline_id: 'golden-hybrid',
    trace_id: 'trace-q-refund',
    query_id: 'q-refund',
    namespace: 'kb',
    entity_id: 'doc-policy',
    unit: 'document',
    entity_revision: null,
    judgment: 'relevant',
    grade: 2,
    judgment_source: 'qrels',
    final_membership: 'included',
    in_final_output: true,
    final_rank: 2,
    outcome: 'relevant_delivered',
    confusion: 'TP',
    capture_state: 'complete',
    observed: true,
    loss_boundary: null,
    priority: 10,
    events: [],
    occurrence_entity_ids: ['kb:doc-policy/chunk-1'],
    evaluation_digest: 'eval-digest',
    judgment_digest: 'judg-digest',
    trace_digest: 'trace-digest',
    investigation_link: '#/investigate?run=golden-run&pipeline=golden-hybrid&view=queries&query=q-refund&trace=trace-q-refund&entity=kb%3Adoc-policy',
    ...overrides,
  }
}

const policy = row({
  events: [
    event('dense', 'introduced', null, 1),
    event('lexical', 'introduced', null, 1),
    event('recency_filter', 'removed', 1, null, { reason: 'min_score' }),
    event('rerank@dense', 'retained', 1, 1),
    event('fuse', 'demoted', 1, 2),
    event('expand_gate', 'retained', 2, 2),
    event('select', 'retained', 2, 2),
  ],
})

const legal = row({
  entity_id: 'doc-legal',
  grade: 1,
  final_membership: 'excluded',
  final_rank: 4,
  outcome: 'retained_below_cutoff',
  confusion: 'FN',
  loss_boundary: 'select',
  events: [event('lexical', 'introduced', null, 4), event('recency_filter', 'promoted', 4, 2), event('rerank@lexical', 'demoted', 2, 3), event('fuse', 'demoted', 3, 5), event('expand_gate', 'retained', 5, 5), event('select', 'promoted', 5, 4)],
})

const news = row({
  entity_id: 'doc-news',
  judgment: 'unjudged',
  grade: null,
  judgment_source: null,
  final_membership: 'excluded',
  in_final_output: false,
  final_rank: null,
  outcome: 'unjudged',
  confusion: 'unknown',
  loss_boundary: 'recency_filter',
  events: [event('lexical', 'introduced', null, 2), event('recency_filter', 'removed', 2, null, { reason: 'stale_year' })],
})

const faqOutage = row({
  trace_id: 'trace-q-outage',
  query_id: 'q-outage',
  entity_id: 'doc-faq',
  judgment: 'nonrelevant',
  grade: 0,
  final_rank: 1,
  outcome: 'judged_nonrelevant',
  confusion: 'FP',
  capture_state: 'partial',
  events: [
    event('dense', 'introduced', null, 1),
    event('lexical', 'introduced', null, 2),
    event('recency_filter', 'retained', 2, 2),
    event('rerank@dense', 'retained', 1, 1),
    event('rerank@lexical', 'unknown', 2, null, { reason_evidence: 'unavailable', boundary_complete: false, output_present: false }),
    event('fuse', 'retained', 1, 1, { reason: 'deduplicated' }),
    event('expand_gate', 'retained', 1, 1),
    event('select', 'retained', 1, 1),
  ],
})

const archive = row({
  trace_id: 'trace-q-invoice',
  query_id: 'q-invoice',
  entity_id: 'doc-archive',
  final_membership: 'excluded',
  in_final_output: false,
  final_rank: null,
  outcome: 'not_observed',
  confusion: 'FN',
  observed: false,
  loss_boundary: 'not_observed',
})

const emptyMetrics = { 'ndcg@10': null, recall: null, latency_p50: null }
const emptyLatency = { count: 0, mean_ms: null, p50_ms: null, p95_ms: null }

function node(node_id: string, op_type: string, depth: number, extra: Partial<PipelineGraphNode> = {}): PipelineGraphNode {
  return {
    node_id,
    label: node_id,
    op_type,
    depth,
    branch_id: BRANCH[node_id] ?? null,
    candidate_count: 3,
    metrics: emptyMetrics,
    is_merge: op_type === 'FUSE',
    source: 'measured',
    input_candidate_count: 3,
    observed_count: 3,
    trace_coverage: 1,
    fire_rate: 1,
    status_counts: { FIRED: 3 },
    cache_hits: 0,
    latency: emptyLatency,
    is_final_output: node_id === 'select',
    final_output_count: node_id === 'select' ? 3 : 0,
    configured: null,
    availability: {},
    ...extra,
  }
}

function edge(source: string, target: string, kind: 'flow' | 'fan_in' = 'flow'): PipelineGraph['edges'][number] {
  return { source, target, kind, observed_count: 3, trace_coverage: 1, conditional: false, source_evidence: 'measured' }
}

const GRAPH: PipelineGraph = {
  pipeline_id: 'golden-hybrid',
  contract_version: 2,
  projection_mode: 'run_union',
  trace_count: 3,
  complete_trace_count: 2,
  status_counts: { OK: 3 },
  final_output_ids: ['select'],
  timing_semantics: {},
  warnings: [],
  nodes: [
    node('dense', 'SOURCE', 0),
    node('lexical', 'SOURCE', 0),
    node('recency_filter', 'FILTER', 1),
    node('rerank@dense', 'RERANK', 1),
    node('rerank@lexical', 'RERANK', 2),
    node('fuse', 'FUSE', 3),
    node('expand_gate', 'GATE', 4),
    node('expand', 'EXPAND', 5, { observed_count: 1, fire_rate: 1 / 3, status_counts: { FIRED: 1, SKIPPED_BY_GATE: 2 } }),
    node('select', 'TRANSFORM', 6),
  ],
  edges: [
    edge('dense', 'rerank@dense'),
    edge('lexical', 'recency_filter'),
    edge('recency_filter', 'rerank@lexical'),
    edge('rerank@dense', 'fuse', 'fan_in'),
    edge('rerank@lexical', 'fuse', 'fan_in'),
    edge('fuse', 'expand_gate'),
    edge('expand_gate', 'expand'),
    edge('expand', 'select'),
    edge('expand_gate', 'select'),
  ],
}

const REPEATED_GRAPH: PipelineGraph = {
  ...GRAPH,
  nodes: [node('source', 'SOURCE', 0), node('rerank', 'RERANK', 1), node('rerank#2', 'RERANK', 2), node('fuse', 'FUSE', 3)],
  edges: [edge('source', 'rerank'), edge('rerank', 'rerank#2'), edge('rerank', 'fuse', 'fan_in'), edge('rerank#2', 'fuse', 'fan_in')],
}

function summary(op_id: string, served: number, skipped: number, received: number, removed: number, introduced: number, partial: number): StageSummary {
  return { op_id, operator_id: op_id.startsWith('rerank@') ? 'rerank' : op_id, queries_served: served, queries_skipped: skipped, candidates_received: received, removal_events: removed, introduced, partial_boundaries: partial }
}

// EXPECTED_STAGE_COUNTS from the golden fixture.
const AGGREGATE: StageSummary[] = [
  summary('dense', 3, 0, 0, 0, 8, 0),
  summary('lexical', 3, 0, 0, 0, 10, 0),
  summary('recency_filter', 3, 0, 10, 4, 0, 0),
  summary('rerank@dense', 3, 0, 8, 0, 0, 0),
  summary('rerank@lexical', 3, 0, 6, 0, 0, 1),
  summary('fuse', 3, 0, 14, 0, 0, 0),
  summary('expand_gate', 3, 0, 11, 0, 0, 0),
  summary('expand', 1, 2, 3, 0, 1, 0),
  summary('select', 3, 0, 12, 2, 0, 0),
]

function stage(op_id: string, op_type: string, status: string, extra: Partial<InvestigationStage> = {}): InvestigationStage {
  return {
    op_id,
    operator_id: op_id.startsWith('rerank@') ? 'rerank' : op_id,
    invocation_id: `inv-${op_id}`,
    op_type,
    status,
    branch: BRANCH[op_id] ?? null,
    parent_ids: GRAPH.edges.filter((e) => e.target === op_id).map((e) => e.source),
    input_capture: 'recorded',
    output_capture: 'recorded',
    received: 3,
    emitted: 3,
    removed: 0,
    introduced: 0,
    ...extra,
  }
}

const REFUND_STAGES: InvestigationStage[] = [
  stage('dense', 'SOURCE', 'FIRED', { input_capture: 'not_applicable', introduced: 3 }),
  stage('lexical', 'SOURCE', 'FIRED', { input_capture: 'not_applicable', introduced: 5 }),
  stage('recency_filter', 'FILTER', 'FIRED', { received: 5, emitted: 3, removed: 2 }),
  stage('rerank@dense', 'RERANK', 'FIRED'),
  stage('rerank@lexical', 'RERANK', 'FIRED', { output_capture: 'truncated' }),
  stage('fuse', 'FUSE', 'FIRED', { received: 6, emitted: 5 }),
  stage('expand_gate', 'GATE', 'FIRED', { received: 5, emitted: 5 }),
  stage('expand', 'EXPAND', 'SKIPPED_BY_GATE', { input_capture: 'unavailable', output_capture: 'unavailable', received: 0, emitted: 0 }),
  stage('select', 'TRANSFORM', 'FIRED', { received: 5, emitted: 4, removed: 1 }),
]

const DOCUMENTS: InvestigationDocumentRow[] = [
  { entity: 'kb:doc-faq', queries: 2, delivered: 1, excluded: 0, not_observed: 0, unknown: 0, judged_relevant_queries: ['q-refund'] },
  { entity: 'kb:doc-archive', queries: 1, delivered: 0, excluded: 1, not_observed: 1, unknown: 0, judged_relevant_queries: ['q-invoice'] },
]

// Stored per-query summaries (evidence/service.py::build_projection) for the golden run.
function querySummary(query_id: string, overrides: Partial<QuerySummaryRow>): QuerySummaryRow {
  return {
    query_id,
    query_text: null,
    pairs: 0,
    TP: 0,
    FP: 0,
    FN: 0,
    TN: 0,
    unknown: 0,
    relevant_excluded: 0,
    insufficient: 0,
    capture_partial: 0,
    relevant_delivered: 0,
    relevant_missed: 0,
    unjudged_included: 0,
    unknown_capture: 0,
    loss_boundaries: {},
    trace_ids: [`trace-${query_id}`],
    ...overrides,
  }
}

const SUMMARIES: QuerySummaryRow[] = [
  querySummary('q-invoice', { pairs: 4, TP: 2, FP: 1, FN: 1, relevant_delivered: 2, relevant_missed: 1, loss_boundaries: { not_observed: 1 } }),
  querySummary('q-outage', { pairs: 3, TP: 1, FP: 1, unknown: 1, capture_partial: 2, relevant_delivered: 1, unjudged_included: 1, unknown_capture: 2 }),
  querySummary('q-refund', {
    query_text: 'How do I get a refund?',
    pairs: 5,
    TP: 2,
    TN: 1,
    unknown: 2,
    relevant_delivered: 2,
    unjudged_included: 1,
    loss_boundaries: { select: 1, recency_filter: 1 },
  }),
]

const noop = () => undefined
const base = { total: null, sort: null, onSort: noop, onSelect: noop, onReset: noop }

describe('InvestigationTable', () => {
  test('queries shape lists the stored per-query summaries with exact counts', () => {
    const html = renderToStaticMarkup(<InvestigationTable shape="queries" rows={SUMMARIES} selection={{ ...DEFAULT_SELECTION, query: 'q-refund' }} {...base} total={202} />)
    expect(html).toContain('<caption')
    expect(html.match(/scope="col"/g)).toHaveLength(5)
    expect(html).toContain('202 queries')
    expect(html).not.toContain('rows,')
    expect(html).toContain('How do I get a refund?')
    expect(html).toContain('>q-refund</span>')
    expect(html).toContain('>✓</span> 2 delivered · <span aria-hidden="true">✕</span> 0 missed')
    expect(html).toContain('>✓</span> 2 delivered · <span aria-hidden="true">✕</span> 1 missed')
    expect(html).toContain('recency_filter ×1, select ×1')
    expect(html).toContain('not_observed ×1')
    expect(html.match(/aria-selected="true"/g)).toHaveLength(1)
  })

  test('queries shape rolls journey rows up per query when a pair-level filter is set', () => {
    const html = renderToStaticMarkup(
      <InvestigationTable shape="queries" rows={[policy, legal, news, faqOutage, archive]} selection={{ ...DEFAULT_SELECTION, query: 'q-refund', stage: 'select' }} {...base} total={12} />,
    )
    expect(html).toContain('<caption')
    expect(html.match(/scope="col"/g)).toHaveLength(5)
    expect(html).toContain('Principal loss boundaries')
    expect(html).toContain('aria-selected="true"')
    expect(html.match(/aria-selected="true"/g)).toHaveLength(1)
    expect(html).toContain('12 candidate rows across 3 queries (filtered)')
    expect(html).toContain('aria-live="polite"')
    expect(html).toContain('stage: select')
    expect(html).toContain('Reset selection')
    expect(html).toContain('aria-sort="none"')
  })

  test('query candidates shape shows glyph and text for every outcome and the source lanes', () => {
    const isSource = (opId: string) => opId === 'dense' || opId === 'lexical'
    const html = renderToStaticMarkup(
      <InvestigationTable shape="query-candidates" rows={[policy, legal, news]} selection={{ ...DEFAULT_SELECTION, query: 'q-refund', entity: 'kb:doc-legal', outcome: 'unjudged' }} isSource={isSource} {...base} sort={{ key: 'entity', dir: 'desc' }} />,
    )
    expect(html).toContain('Relevant, delivered')
    expect(html).toContain('>✓<')
    expect(html).toContain('Retained below cutoff')
    expect(html).toContain('>↓<')
    expect(html).toContain('Unjudged')
    expect(html).toContain('>?<')
    expect(html).toContain('dense, lexical')
    expect(html).toContain('outcome: Unjudged')
    expect(html).toContain('aria-sort="descending"')
    expect(html).toContain('recorded · ')
    expect(html).toContain('aria-selected="true"')
    expect(html).toContain('tabindex="0"')
  })

  test('documents shape lists per-entity counts with glyphs', () => {
    const html = renderToStaticMarkup(<InvestigationTable shape="documents" rows={DOCUMENTS} selection={{ ...DEFAULT_SELECTION, view: 'documents', entity: 'kb:doc-faq' }} {...base} total={8} />)
    expect(html).toContain('Judged-relevant queries')
    expect(html).toContain('Known downstream loss')
    expect(html).toContain('1 of 2')
    expect(html).toContain('8 rows, 2 shown')
    expect(html.match(/aria-selected="true"/g)).toHaveLength(1)
  })

  test('document queries shape renders the compact transition sequence and capture', () => {
    const html = renderToStaticMarkup(
      <InvestigationTable shape="document-queries" rows={[news, faqOutage]} selection={{ ...DEFAULT_SELECTION, view: 'documents', entity: 'kb:doc-news', query: 'q-refund' }} {...base} />,
    )
    expect(html).toContain('Recorded transition sequence')
    expect(html).toContain('lexical ▸ recency_filter ✕')
    expect(html).toContain('rerank@lexical ◌')
    expect(html).toContain('⚠ </span>partial')
    expect(html).toContain('Judged nonrelevant')
  })

  test('row keyboard handling is a pure index rule', () => {
    expect(nextIndexForKey('ArrowDown', 1, 5)).toBe(2)
    expect(nextIndexForKey('ArrowUp', 0, 5)).toBe(0)
    expect(nextIndexForKey('End', 0, 5)).toBe(4)
    expect(nextIndexForKey(' ', 0, 5)).toBeNull()
  })
})

describe('InvestigationDetail', () => {
  test('lists events in order with evidence labels, boundary capture, permalink and IDs-only fallback', () => {
    const html = renderToStaticMarkup(<InvestigationDetail row={policy} stages={REFUND_STAGES} />)
    const order = ['dense', 'lexical', 'recency_filter', 'rerank@dense', 'fuse', 'expand_gate', 'select'].map((op) => html.indexOf(`<span class="font-mono text-ink">${op}</span>`))
    expect(order.every((index, i) => index > 0 && (i === 0 || index > order[i - 1]))).toBe(true)
    expect(html).toContain('min_score <span class="text-ink-faint">(recorded)</span>')
    expect(html).toContain('no content captured; IDs only')
    expect(html).toContain('Boundary capture')
    expect(html).toContain('source not recorded')
    expect(html).toContain(`value="${policy.investigation_link.replace(/&/g, '&amp;')}"`)
    expect(html).toContain('Evidence details')
    expect(html).toContain('trace-digest')
    expect(html).not.toContain('boundary not fully captured')
  })

  test('an unknown event says the boundary was not fully captured', () => {
    const html = renderToStaticMarkup(<InvestigationDetail row={faqOutage} stages={REFUND_STAGES} />)
    expect(html).toContain('boundary not fully captured')
    expect(html).toContain('◌</span> unknown')
    expect(html).toContain('deduplicated <span class="text-ink-faint">(recorded)</span>')
    expect(html).toContain('out <span aria-hidden="true">⚠ </span>truncated')
  })

  test('shows captured content when the payload carries it', () => {
    const html = renderToStaticMarkup(<InvestigationDetail row={row({ metadata: { title: 'Refund policy' } })} stages={null} />)
    expect(html).toContain('Refund policy')
    expect(html).not.toContain('IDs only')
    expect(html).toContain('Not observed at any captured boundary')
  })
})

function flowStep(seen: number, input: number, output: number, in_top_k: number, removed = 0, removed_but_delivered = 0, dropped = 0): FlowStep {
  return { seen, input, output, in_top_k, removed, removed_but_delivered, lost: { dropped, ranked_low: 0, pushed_out: 0, unknown: 0 }, lost_total: dropped }
}

// GET /flow for the golden run (the seeded demo baseline).
const FLOW: InvestigationFlow = {
  k: 3,
  totals: { relevant: 6, delivered: 4, missed: 2, never_found: 1, insufficient: 0, questions: 3, questions_judged: 3, questions_with_miss: 2, questions_with_none: 1 },
  steps: {
    dense: flowStep(4, 0, 4, 4),
    lexical: flowStep(5, 0, 5, 5),
    recency_filter: flowStep(5, 5, 0, 0, 5, 4, 1),
    'rerank@dense': flowStep(4, 4, 4, 4),
    fuse: flowStep(4, 4, 4, 4),
    expand_gate: flowStep(4, 4, 4, 4),
    expand: flowStep(2, 2, 2, 2),
    select: flowStep(4, 4, 4, 4, 1, 1),
  },
  copresence: { 'dense→rerank@dense': 4, 'lexical→recency_filter': 5, 'rerank@dense→fuse': 4, 'fuse→expand_gate': 4, 'expand_gate→expand': 2, 'expand→select': 2, 'expand_gate→select': 4, 'dense→fuse': 4 },
  misses: [],
}

/** The markup outside every <details> disclosure: what a reader sees without opening one. */
function outsideDetails(html: string): string {
  return html.replace(/<details[\s\S]*?<\/details>/g, '')
}

function titles(html: string): string[][] {
  return [...html.matchAll(/<button type="button" aria-pressed="(?:true|false)" title="([^"]*)"/g)].map((m) => m[1].split('\n'))
}

/** The rendered text of the stage card whose title names `opId` on its second line. */
function card(html: string, opId: string): string {
  const cards = html.split('<foreignObject').slice(1)
  const found = cards.find((markup) => markup.match(/title="([^"]*)"/)?.[1].split('\n')[1] === opId)
  return (found ?? '>').slice((found ?? '>').indexOf('>') + 1).replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim()
}

describe('InvestigationGraph', () => {
  const graphProps = { flow: null, stages: null, traceStages: null, focus: null, k: 3, selectedStageId: null, collapsed: true, onToggleCollapsed: noop, onSelectStage: noop }

  test('run mode follows the correct documents through every step', () => {
    const html = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={GRAPH} flow={FLOW} stages={AGGREGATE} />)
    expect(card(html, 'dense')).toContain('Found 4 of 6')
    expect(card(html, 'dense')).toContain('4 in its top 3')
    expect(card(html, 'lexical')).toContain('Found 5 of 6')
    expect(card(html, 'recency_filter')).toContain('5 correct in')
    expect(card(html, 'recency_filter')).toContain('Lost 1')
    expect(card(html, 'recency_filter')).toContain('Removed 5 · 4 still delivered')
    expect(card(html, 'rerank@lexical')).toContain('None reached it')
    expect(card(html, 'expand')).toContain('Ran for 1 of 3 questions')
    // Seven columns at 1200 px leave no room for a result card: the final step carries the result.
    expect(card(html, 'select')).toContain('4 of 6 in top 3')
    expect(html).not.toContain('Final result')
    expect(html).toContain('role="group"')
    expect(html).toContain('aria-label="Pipeline golden-hybrid: 9 steps, 9 edges; showing correct documents over the whole run"')
    expect(html).toContain('Line thickness = correct documents passing · dashed = ran for only some questions')
    expect(html).toContain('1 never found by any search')
    // Edge thickness = correct documents passing; the count labels the long dense lane, empty edges are dashed.
    expect(html).toContain('stroke-width:12.666')
    expect(html).toContain('>4 correct</text>')
    expect(html.match(/stroke-dasharray:5 4/g)).toHaveLength(2)
    expect(html).not.toContain('repeated invocations')
    expect(html).not.toContain('Zoom')
  })

  test('without judgments the cards fall back to the stored candidate counts', () => {
    const html = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={GRAPH} stages={AGGREGATE} />)
    expect(card(html, 'expand')).toContain('Ran for 1 of 3 questions')
    expect(card(html, 'recency_filter')).toContain('10 candidates in')
    expect(card(html, 'lexical')).toContain('10 candidates found')
    expect(html).not.toContain('Line thickness')
    expect(html).not.toContain('stroke-dasharray')
  })

  test('question mode states each step in words and labels steps the question did not run', () => {
    const html = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={GRAPH} traceStages={REFUND_STAGES} selectedStageId="select" />)
    expect(card(html, 'rerank@lexical')).toContain('3 in · 3 out')
    expect(card(html, 'rerank@lexical')).toContain('Ran · Partly recorded')
    expect(card(html, 'expand')).toContain('Skipped by a gate')
    expect(card(html, 'select')).toContain('Selected')
    expect(html).toContain('showing one question; select selected')
    const partial = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={GRAPH} traceStages={REFUND_STAGES.filter((s) => s.op_id !== 'fuse')} />)
    expect(card(partial, 'fuse')).toContain('Not run for this question')
  })

  test('path mode shows the document’s rank at each step and draws its path', () => {
    const html = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={GRAPH} flow={FLOW} traceStages={REFUND_STAGES} focus={policy} />)
    expect(card(html, 'dense')).toContain('Rank 1')
    expect(card(html, 'dense')).toContain('Found it')
    expect(card(html, 'recency_filter')).toContain('Removed')
    expect(card(html, 'recency_filter')).toContain('min_score')
    expect(card(html, 'fuse')).toContain('Rank 2')
    expect(card(html, 'fuse')).toContain('was 1')
    expect(card(html, 'select')).toContain('Delivered at #2')
    expect(card(html, 'expand')).toContain('Skipped for this question')
    expect(card(html, 'rerank@lexical')).toContain("Didn't reach it")
    expect(html.match(/data-on-path="true"/g)).toHaveLength(5)
    expect(html).toContain('showing the path of doc-policy')
    expect(html).toContain('Rank of doc-policy at each step')
    // No correct-document counts in path mode.
    expect(html).not.toContain('never found by any search')

    const lost = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={GRAPH} traceStages={REFUND_STAGES} focus={legal} />)
    expect(card(lost, 'select')).toContain('Rank 4')
    expect(card(lost, 'select')).toContain('was 5 · fell below the top 3 · Not delivered')
    expect(card(lost, 'rerank@lexical')).toContain('was 2')
    expect(card(lost, 'dense')).toContain('Not in its top 3')
  })

  test('no internal enum, all-caps or sub-12px text outside a disclosure, in any mode', () => {
    for (const html of [
      renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={GRAPH} flow={FLOW} stages={AGGREGATE} />),
      renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={GRAPH} traceStages={REFUND_STAGES} />),
      renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={GRAPH} traceStages={REFUND_STAGES} focus={faqOutage} />),
    ]) {
      const visible = outsideDetails(html)
      for (const banned of ['FIRED', 'SKIPPED_BY_GATE', 'TIMEOUT', 'uppercase', 'text-[9px]', 'text-[10px]', 'text-[11px]', 'truncated', 'unavailable']) expect(visible).not.toContain(banned)
    }
  })

  test('step cards are keyboard-reachable buttons whose title names the step id on its second line', () => {
    const html = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={GRAPH} flow={FLOW} selectedStageId="fuse" />)
    expect(html).not.toContain('role="img"')
    expect(html.match(/<button type="button" aria-pressed="(true|false)"/g)).toHaveLength(GRAPH.nodes.length)
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1)
    expect(html).not.toContain('tabindex="-1"')
    expect(titles(html).map((lines) => lines[1]).sort()).toEqual(GRAPH.nodes.map((n) => n.node_id).sort())
    const onSelect = vi.fn()
    const fuse = { ...GRAPH.nodes.find((n) => n.node_id === 'fuse')!, x: 0, y: 0, w: 160, h: 108, col: 3, row: 1 }
    const words = { metric: '4 correct in', note: null, noteTone: null, badge: null, ghost: false }
    const element = StepCard({ node: fuse, words, selected: true, onPath: false, onSelect })
    const button = element.props.children
    expect(button.type).toBe('button')
    // Enter and Space activate a native button through the same onClick.
    button.props.onClick()
    expect(onSelect).toHaveBeenCalledWith('fuse')
    // Selection is stated in text, not only by the border colour.
    expect(renderToStaticMarkup(<svg>{element}</svg>)).toContain('>Selected<')
  })

  test('the diagram scrolls sideways only when its lanes do not fit', () => {
    const wide = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={GRAPH} flow={FLOW} width={1200} />)
    expect(wide).not.toContain('overflow-x-auto"><svg')
    expect(Number(wide.match(/<svg width="([\d.]+)"/)![1])).toBeLessThanOrEqual(1200)
    // The demo's two lanes fit a phone; three source lanes do not.
    const phone = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={GRAPH} flow={FLOW} width={330} />)
    expect(phone).not.toContain('overflow-x-auto"><svg')
    const threeLanes: PipelineGraph = {
      ...GRAPH,
      nodes: [node('a', 'SOURCE', 0), node('b', 'SOURCE', 0), node('c', 'SOURCE', 0), node('select', 'FUSE', 1)],
      edges: [edge('a', 'select', 'fan_in'), edge('b', 'select', 'fan_in'), edge('c', 'select', 'fan_in')],
    }
    expect(renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={threeLanes} width={330} />)).toContain('overflow-x-auto"><svg')
  })

  test('the only final step hands the result to its own card when the extra column fits', () => {
    const real: PipelineGraph = {
      ...GRAPH,
      pipeline_id: 'rag_search-retrieval',
      trace_count: 300,
      final_output_ids: ['rrf'],
      nodes: [
        node('bm25', 'SOURCE', 0, { label: 'Search (bm25)', status_counts: { FIRED: 300 } }),
        node('dense', 'SOURCE', 0, { label: 'Search (dense)', status_counts: { FIRED: 300 } }),
        node('rrf', 'FUSE', 1, { label: 'Fuse Hits', is_final_output: true, status_counts: { FIRED: 300 } }),
      ],
      edges: [edge('bm25', 'rrf', 'fan_in'), edge('dense', 'rrf', 'fan_in')],
    }
    const realFlow: InvestigationFlow = {
      k: 10,
      totals: { relevant: 339, delivered: 288, missed: 51, never_found: 8, insufficient: 0, questions: 300, questions_judged: 300, questions_with_miss: 48, questions_with_none: 40 },
      steps: { bm25: flowStep(311, 0, 311, 272), dense: flowStep(321, 0, 321, 283), rrf: { ...flowStep(331, 331, 328, 288, 3, 0, 3), lost: { dropped: 3, ranked_low: 26, pushed_out: 14, unknown: 0 }, lost_total: 43 } },
      copresence: { 'bm25→rrf': 311, 'dense→rrf': 321 },
      misses: [],
    }
    const html = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={real} flow={realFlow} k={10} />)
    expect(card(html, 'dense')).toContain('Search (dense) Found 321 of 339 283 in its top 10')
    expect(card(html, 'rrf')).toContain('Fuse Hits rrf 331 correct in Lost 43')
    expect(card(html, 'rrf')).not.toContain('in top 10')
    const result = html.split('<foreignObject').find((markup) => markup.includes('Final result'))!
    expect(result).toContain('aria-hidden="true"')
    expect(result).not.toContain('<button')
    for (const text of ['Top 10', '288 of 339', 'correct delivered · 85%']) expect(result).toContain(text)
    expect(html.match(/<button type="button" aria-pressed/g)).toHaveLength(3)
    expect(html).toContain('>288 correct</text>')
    expect(html).toContain('>321 correct</text>')

    const missed = row({ ...legal, trace_id: 't', query_id: '1', entity_id: '31715818', loss_boundary: 'rrf', events: [event('dense', 'introduced', null, 14), event('rrf', 'demoted', 14, 36)] })
    const path = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={real} flow={realFlow} k={10} focus={missed} />)
    expect(card(path, 'rrf')).toContain('Rank 36 was 14 · fell below the top 10')
    expect(card(path, 'rrf')).not.toContain('Not delivered')
    expect(path.split('<foreignObject').find((markup) => markup.includes('Final result'))).toContain('Not delivered')
    expect(path.match(/data-on-path="true"/g)).toHaveLength(1)
  })

  test('the steps table is the accessible equivalent, with correct documents per step', () => {
    const html = renderToStaticMarkup(<FlowTable graph={GRAPH} flow={FLOW} />)
    expect(html).toContain('<caption class="sr-only">Pipeline steps for golden-hybrid</caption>')
    expect(html.match(/scope="row"/g)).toHaveLength(GRAPH.nodes.length)
    expect(html.match(/scope="col"/g)).toHaveLength(6)
    for (const heading of ['Step', 'Kind', 'Ran for', 'Correct in', 'Correct out', 'Lost here']) expect(html).toContain(`>${heading}</th>`)
    expect(html).toContain('1 of 3 questions')
    const recency = html.split('<tr').find((tr) => tr.includes('>recency_filter<'))!
    expect(recency.replace(/<[^>]+>/g, '|')).toMatch(/Filter\|+3 of 3 questions\|+5\|+0\|+1/)
    expect(renderToStaticMarkup(<FlowTable graph={GRAPH} flow={null} />)).toContain('>—</td>')
    const graphHtml = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={GRAPH} flow={FLOW} />)
    expect(graphHtml).toContain('Show the steps as a table')
    expect(graphHtml).toContain('Pipeline steps for golden-hybrid')
  })

  test('collapses repeated invocations by default with an explicit expand control', () => {
    const collapsedHtml = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={REPEATED_GRAPH} />)
    expect(collapsedHtml).toContain('Expand repeated invocations (1)')
    expect(collapsedHtml).toContain('3 steps, 2 edges')
    const expandedHtml = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={REPEATED_GRAPH} collapsed={false} />)
    expect(expandedHtml).toContain('Collapse repeated invocations (1)')
    expect(expandedHtml).toContain('4 steps, 4 edges')
  })

  test('says so when no topology was recorded', () => {
    const html = renderToStaticMarkup(<InvestigationGraph {...graphProps} graph={null} stages={AGGREGATE} />)
    expect(html).toContain('No pipeline topology recorded for this run; the tables below still hold every indexed journey.')
  })
})

describe('OperatorInspector', () => {
  const nodeOf = (id: string) => ({ ...GRAPH.nodes.find((n) => n.node_id === id)!, label: id === 'recency_filter' ? 'Recency Filter' : id })
  const aggregateOf = (id: string) => AGGREGATE.find((s) => s.op_id === id)!

  test('says in one sentence what the step did with the correct documents', () => {
    const html = renderToStaticMarkup(
      <OperatorInspector opId="recency_filter" node={nodeOf('recency_filter')} flowStep={FLOW.steps.recency_filter} flow={FLOW} stage={null} aggregate={aggregateOf('recency_filter')} />,
    )
    expect(html).toContain('id="operator-inspector-title"')
    expect(html).toContain('aria-labelledby="operator-inspector-title"')
    expect(html).toContain('Recency Filter <span class="font-normal text-ink-muted">· Filter</span>')
    expect(html).toContain('>recency_filter</span>')
    expect(html).toContain('Ran for 3 of 3 questions. Received 5 correct documents and lost 1 for good: 1 dropped. It removed 5; 4 still reached the top 3.')
    expect(html).toContain('Technical details')
    expect(html).toContain('Removal events')
    expect(html.toLowerCase()).not.toContain('attribution')
    const source = renderToStaticMarkup(<OperatorInspector opId="dense" node={nodeOf('dense')} flowStep={FLOW.steps.dense} flow={FLOW} stage={null} aggregate={aggregateOf('dense')} />)
    expect(source).toContain('Found 4 correct documents, 4 in its own top 3 and lost none.')
  })

  test('an open question adds what the step did for it; raw states stay in Technical details', () => {
    const html = renderToStaticMarkup(
      <OperatorInspector opId="expand" node={nodeOf('expand')} flowStep={FLOW.steps.expand} flow={FLOW} stage={REFUND_STAGES.find((s) => s.op_id === 'expand')!} aggregate={aggregateOf('expand')} />,
    )
    expect(html).toContain('Ran for 1 of 3 questions. Received 2 correct documents and lost none.')
    expect(html).toContain('For this question: Skipped by a gate. 0 candidates in, 0 out. Input not recorded. Output not recorded.')
    expect(html).toContain('SKIPPED_BY_GATE')
    expect(outsideDetails(html)).not.toContain('SKIPPED_BY_GATE')
    expect(outsideDetails(html)).not.toContain('unavailable')
  })

  test('falls back to the stored counts, and explains the missing counts before the index is built', () => {
    const stored = renderToStaticMarkup(<OperatorInspector opId="expand" node={nodeOf('expand')} flowStep={null} flow={null} stage={null} aggregate={aggregateOf('expand')} />)
    expect(stored).toContain('Ran for 1 of 3 questions; 3 candidates in.')
    const html = renderToStaticMarkup(<OperatorInspector opId="select" node={null} flowStep={null} flow={null} stage={null} aggregate={null} />)
    expect(html).toContain('No stored counts for this step yet; index the run to count them.')
    expect(html).toContain('select')
  })
})

describe('modeFor', () => {
  test('derives the table shape from the URL selection only', () => {
    expect(modeFor(DEFAULT_SELECTION)).toBe('queries')
    expect(modeFor({ ...DEFAULT_SELECTION, query: 'q' })).toBe('query-candidates')
    expect(modeFor({ ...DEFAULT_SELECTION, view: 'documents' })).toBe('documents')
    expect(modeFor({ ...DEFAULT_SELECTION, view: 'documents', entity: 'kb:doc' })).toBe('document-queries')
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('Investigate stale-response guards', () => {
  test('two fast load-more clicks for one cursor send one request', async () => {
    const inFlight = { current: null as string | null }
    const pending = deferred<string[]>()
    const request = vi.fn(() => pending.promise)
    const first = singleFlight(inFlight, '1:cursor-2', request)
    const second = singleFlight(inFlight, '1:cursor-2', request)
    expect(first).not.toBeNull()
    expect(second).toBeNull()
    expect(request).toHaveBeenCalledTimes(1)
    // The same cursor under a newer scope (sequence) is a different request and goes through.
    const newScope = singleFlight(inFlight, '2:cursor-2', () => Promise.resolve(['other-scope']))
    expect(newScope).not.toBeNull()
    await newScope
    pending.resolve(['row-51'])
    expect(await first).toEqual(['row-51'])
    // The slot is released once the request settles; the next cursor goes through.
    expect(singleFlight(inFlight, 'cursor-3', () => Promise.resolve([]))).not.toBeNull()
  })

  test('a failed load-more releases the cursor so it can be retried', async () => {
    const inFlight = { current: null as string | null }
    const pending = deferred<string[]>()
    const first = singleFlight(inFlight, 'cursor-2', () => pending.promise)
    pending.reject(new Error('boom'))
    await expect(first).rejects.toThrow('boom')
    expect(inFlight.current).toBeNull()
  })

  test('an index build that resolves after a run switch never lands on the new scope', async () => {
    let scope = 'run-a'
    const started = scope
    const setBuild = vi.fn()
    const reload = vi.fn()
    const build = deferred<{ status: string; error?: string | null }>()
    const settled = settleBuild(build.promise, () => scope === started, 'run-a', setBuild, reload)
    scope = 'run-b'
    build.resolve({ status: 'complete' })
    await settled
    expect(setBuild).not.toHaveBeenCalled()
    expect(reload).not.toHaveBeenCalled()
  })

  test('builds resolving out of order: only the one for the current scope applies', async () => {
    let scope = 'run-a'
    const setBuild = vi.fn()
    const reload = vi.fn()
    const buildA = deferred<{ status: string; error?: string | null }>()
    const settledA = settleBuild(buildA.promise, () => scope === 'run-a', 'run-a', setBuild, reload)
    scope = 'run-b'
    const buildB = deferred<{ status: string; error?: string | null }>()
    const settledB = settleBuild(buildB.promise, () => scope === 'run-b', 'run-b', setBuild, reload)
    buildB.resolve({ status: 'failed', error: 'B failed' })
    await settledB
    buildA.reject(new Error('buildInvestigationProjection: 409 Conflict — {"detail":{"code":"read_only"}}'))
    await settledA
    expect(setBuild).toHaveBeenCalledTimes(1)
    expect(setBuild).toHaveBeenCalledWith({ kind: 'failed', message: 'B failed' })
    expect(reload).not.toHaveBeenCalled()
  })

  test('a build for the still-selected scope applies its outcome', async () => {
    const setBuild = vi.fn()
    const reload = vi.fn()
    await settleBuild(Promise.resolve({ status: 'complete' }), () => true, 'run-a', setBuild, reload)
    expect(setBuild).toHaveBeenCalledWith({ kind: 'idle' })
    expect(reload).toHaveBeenCalledTimes(1)
    const refused = vi.fn()
    await settleBuild(Promise.reject(new Error('buildInvestigationProjection: 409 Conflict — {}')), () => true, 'run-a', refused, reload)
    expect(refused.mock.calls[0][0]).toMatchObject({ kind: 'refused' })
  })
})
