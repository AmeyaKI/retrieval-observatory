import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'
// api.ts reads window.location.origin at import time; the node test environment has no window.
vi.hoisted(() => {
  ;(globalThis as { window?: unknown }).window = { location: { origin: 'http://localhost' } }
})
import type { FlowMiss, FlowStep, InvestigationDocumentRow, InvestigationFlow, InvestigationStage, JourneyEvent, JourneyRow, PipelineGraph, PipelineGraphNode, QuerySummaryRow, StageSummary } from '../api'
import { DEFAULT_SELECTION } from '../context/dashboardQuery'
import { missedDocuments, missedQuestions, runHeadline } from '../utils/flowWords'
import { nextIndexForKey } from '../utils/queryDebugger'
import JourneyCard from './InvestigationDetail'
import InvestigationGraph, { FlowTable, StepCard } from './InvestigationGraph'
import InvestigationTable from './InvestigationTable'
import { modeFor, settleBuild, singleFlight } from './InvestigateWorkspace'
import OperatorInspector from './OperatorInspector'
import { CorrectDocuments, DeliveredList, QuestionHeader } from './QuestionView'
import { DocumentHeader, MissedQuestions, RunHeadline } from './RunView'

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
const base = { total: null, sort: null, onSort: noop, onSelect: noop }

describe('InvestigationTable', () => {
  const headers = (html: string) => [...html.matchAll(/<th scope="col"[^>]*>.*?<button[^>]*>([^<]+)/g)].map((m) => m[1])
  const bodyRows = (html: string) => [...html.matchAll(/<tr tabindex="0"[^>]*>([\s\S]*?)<\/tr>/g)].map((m) => words(m[1]))
  const outageMisses = new Map<string, FlowMiss[]>([['q-invoice', [flowMiss('q-invoice', 'doc-archive', 'not_observed', 'not_observed', { question_relevant: 3, question_delivered: 2 })]]])

  test('queries shape lists every question with its correct documents in the top k and what happened', () => {
    const html = renderToStaticMarkup(
      <InvestigationTable shape="queries" rows={SUMMARIES} selection={{ ...DEFAULT_SELECTION, query: 'q-refund' }} {...base} total={202} k={3} misses={outageMisses} />,
    )
    expect(html).toContain('<caption')
    expect(headers(html)).toEqual(['Question', 'Correct in top 3', 'What happened'])
    expect(html).toContain('>202 questions</p>')
    expect(bodyRows(html)).toEqual([
      'q-invoice 2 of 3 correct in top 3 Never found by any search',
      'q-outage 1 of 1 correct in top 3 All delivered',
      'How do I get a refund? q-refund 2 of 2 correct in top 3 All delivered',
    ])
    expect(html).toContain('text-status-warning">2 of 3')
    expect(html).toContain('text-status-positive">2 of 2')
    // Without the flow's misses a question reads how many it missed.
    expect(words(renderToStaticMarkup(<InvestigationTable shape="queries" rows={SUMMARIES} selection={DEFAULT_SELECTION} {...base} k={3} />))).toContain('2 of 3 correct in top 3 1 missed')
    // A question in the flow's misses counts from the flow, like the missed list.
    const flowCounts = new Map([['q-invoice', [flowMiss('q-invoice', 'doc-archive', 'not_observed', 'not_observed', { question_relevant: 4, question_delivered: 1 })]]])
    expect(words(renderToStaticMarkup(<InvestigationTable shape="queries" rows={SUMMARIES} selection={DEFAULT_SELECTION} {...base} k={3} misses={flowCounts} />))).toContain('q-invoice 1 of 4 correct in top 3')
    expect(html.match(/aria-selected="true"/g)).toHaveLength(1)
    for (const gone of ['Principal loss boundaries', 'Unjudged included', 'Unknown capture', 'recency_filter ×1', 'Reset selection', 'min-w-[48rem]', '✓', '✕']) expect(html).not.toContain(gone)
    expect(html).toContain('max-sm:flex')
  })

  test('queries shape rolls journey rows up per question when a pair-level filter is set', () => {
    const html = renderToStaticMarkup(
      <InvestigationTable
        shape="queries"
        rows={[policy, legal, news, faqOutage, archive]}
        selection={{ ...DEFAULT_SELECTION, query: 'q-refund', stage: 'select' }}
        {...base}
        total={12}
        k={3}
        stepLabel={(opId) => (opId === 'select' ? 'Select' : opId)}
      />,
    )
    expect(headers(html)).toEqual(['Question', 'Correct in top 3', 'What happened'])
    expect(html.match(/aria-selected="true"/g)).toHaveLength(1)
    expect(html).toContain('12 candidate rows across 3 questions (filtered)')
    expect(html).toContain('aria-live="polite"')
    expect(html).toContain('Lost at Select')
    expect(html).toContain('Clear filters')
    expect(html).toContain('aria-sort="none"')
    expect(bodyRows(html)).toContain('q-refund 1 of 2 correct in top 3 1 missed')
  })

  test('missed shape: one row per question, a line per missed correct document', () => {
    const flow: InvestigationFlow = {
      ...FLOW,
      misses: [
        flowMiss('q-outage', 'doc-guide', 'relevant_excluded', 'recency_filter', { query_text: 'why is the site down', best_op: 'lexical', best_rank: 1 }),
        flowMiss('q-invoice', 'doc-archive', 'not_observed', 'not_observed', { query_text: 'invoice for order 42', question_relevant: 3, question_delivered: 2 }),
      ],
    }
    const onSelect = vi.fn()
    const element = InvestigationTable({
      shape: 'missed',
      rows: missedQuestions(flow),
      selection: DEFAULT_SELECTION,
      ...base,
      total: 2,
      k: 3,
      stepLabel: (opId) => LABELS[opId] ?? opId,
      onSelect,
    })
    const html = renderToStaticMarkup(element)
    expect(html).toContain('<caption class="sr-only">Questions that missed a correct document')
    expect(headers(html)).toEqual(['Question', 'Correct in top 3', 'What happened'])
    expect(bodyRows(html)).toEqual(['why is the site down q-outage 0 of 1 correct in top 3 Dropped by Recency Filter Lexical had it at #1', 'invoice for order 42 q-invoice 2 of 3 correct in top 3 Never found by any search'])
    expect(html).toContain('text-status-negative">0 of 1')
    expect(html).toContain('text-status-warning">2 of 3')
    expect(html).toContain('2 questions · 2 shown')
    expect(html.match(/tabindex="0"/g)).toHaveLength(2)
    expect(html).not.toContain('Clear filters')
    // Activating a row opens the question on its one trace.
    const findRows = (node: unknown): Array<{ props: { onClick: () => void } }> => {
      if (!node || typeof node !== 'object') return []
      const el = node as { type?: unknown; props?: { children?: unknown; onClick?: () => void } }
      const own = el.type === 'tr' && el.props?.onClick ? [el as { props: { onClick: () => void } }] : []
      const children = el.props?.children
      return [...own, ...(Array.isArray(children) ? children.flatMap(findRows) : findRows(children))]
    }
    findRows(element)[0].props.onClick()
    expect(onSelect).toHaveBeenCalledWith({ query: 'q-outage', trace: 't:q-outage', entity: null })
  })

  test('query candidates shape says in words what happened to each candidate and where it came from', () => {
    const isSource = (opId: string) => opId === 'dense' || opId === 'lexical'
    const html = renderToStaticMarkup(
      <InvestigationTable
        shape="query-candidates"
        rows={[policy, legal, news]}
        selection={{ ...DEFAULT_SELECTION, query: 'q-refund', entity: 'kb:doc-legal', outcome: 'unjudged', stage: 'recency_filter' }}
        isSource={isSource}
        k={3}
        singleNamespace
        stepLabel={(opId) => (opId === 'recency_filter' ? 'Recency Filter' : opId)}
        {...base}
        total={12}
        sort={{ key: 'entity', dir: 'desc' }}
      />,
    )
    expect(html).toContain('<caption')
    expect([...html.matchAll(/<th scope="col"[^>]*>.*?<button[^>]*>([^<]+)/g)].map((m) => m[1])).toEqual(['Rank', 'Document', 'Judged', 'Came from', 'What happened'])
    expect(html).toContain('<span class="text-status-positive">Correct, delivered</span>')
    expect(html).toContain('<span class="text-status-negative">Correct, pushed out of the top 3</span>')
    expect(html).toContain('<span class="text-ink-muted">Not judged</span>')
    expect(html).toContain('Correct · grade 2')
    expect(html).toContain('dense #1 · lexical #1')
    expect(html).toContain('>doc-legal</span>')
    expect(html).not.toContain('kb:doc')
    expect(html).toContain('12 candidates · 3 shown')
    expect(html).toContain('aria-live="polite"')
    // Filters as words, removable one by one or together.
    expect(html).toContain('Lost at Recency Filter')
    expect(html).toContain('aria-label="Remove filter Not judged"')
    expect(html).toContain('Clear filters')
    // Only the active column shows a sort arrow; selection is the accent bar plus aria-selected.
    expect(html).toContain('aria-sort="descending"')
    expect(html.match(/[▲▼↕]/g)).toEqual(['▼'])
    expect(html.match(/aria-selected="true"/g)).toHaveLength(1)
    expect(html).toContain('shadow-[inset_3px_0_0_0_rgb(var(--accent))]')
    expect(html.match(/tabindex="0"/g)).toHaveLength(3)
    // Stacked rows on a phone instead of a floor width; no all-caps tag, no glyphs, nothing under 12 px.
    expect(html).toContain('max-sm:flex')
    for (const banned of ['min-w-[48rem]', 'uppercase', 'text-[10px]', '>selected<', '✓', '↓', '>?<']) expect(html).not.toContain(banned)
    const plain = renderToStaticMarkup(<InvestigationTable shape="query-candidates" rows={[news]} selection={{ ...DEFAULT_SELECTION, query: 'q-refund' }} {...base} />)
    expect(plain).not.toContain('Clear filters')
    expect(plain).toContain('>—</td>')
  })

  test('documents shape: correct for, delivered, missed (of its correct questions) and appears in; missed ones lead', () => {
    const html = renderToStaticMarkup(<InvestigationTable shape="documents" rows={DOCUMENTS} selection={{ ...DEFAULT_SELECTION, view: 'documents', entity: 'kb:doc-faq' }} {...base} total={8} singleNamespace />)
    expect(headers(html)).toEqual(['Document', 'Correct for', 'Delivered', 'Missed', 'Appears in'])
    // doc-archive was never found for its one correct question: missed once, not excluded + not observed.
    expect(bodyRows(html)).toEqual(['doc-archive Correct for 1 question Delivered 0 Missed 1 Appears in 1 question', 'doc-faq Correct for 1 question Delivered 1 Missed 0 Appears in 2 questions'])
    expect(html).toContain('8 documents · 2 shown')
    expect(html.match(/aria-selected="true"/g)).toHaveLength(1)
    const none = renderToStaticMarkup(<InvestigationTable shape="documents" rows={[{ ...DOCUMENTS[0], judged_relevant_queries: [] }]} selection={DEFAULT_SELECTION} {...base} />)
    expect(bodyRows(none)).toEqual(['kb:doc-faq Correct for — Delivered 1 Missed 0 Appears in 2 questions'])
    for (const gone of ['Judged-relevant queries', 'Known downstream loss', 'Unobserved', '✓', '✕', '○', '◌']) expect(html).not.toContain(gone)
  })

  test('document queries shape: the question, judged, what happened and a compact trail of ranks', () => {
    const html = renderToStaticMarkup(
      <InvestigationTable
        shape="document-queries"
        rows={[news, { ...faqOutage, query_text: 'why is the site down' }]}
        selection={{ ...DEFAULT_SELECTION, view: 'documents', entity: 'kb:doc-news', query: 'q-refund' }}
        {...base}
        k={3}
        isSource={(opId) => opId === 'dense' || opId === 'lexical'}
        stepLabel={(opId) => (LABELS[opId] ?? opId).replace(/ \(.*\)$/, '')}
      />,
    )
    expect(headers(html)).toEqual(['Question', 'Judged', 'What happened', 'Ranks'])
    expect(bodyRows(html)).toEqual([
      'why is the site down q-outage Not correct Not correct Dense #1 · Lexical #2 → Recency Filter #2 → Rerank #1 → … → Select #1',
      'q-refund Not judged Not judged Lexical #2 → Recency Filter removed',
    ])
    expect(html).toContain('<span class="text-ink-muted">Not judged</span>')
    expect(html).toContain('2 questions · 2 shown')
    for (const gone of ['Recorded transition sequence', '▸', '✕', '◌', '⚠', 'Judged nonrelevant', 'Capture']) expect(html).not.toContain(gone)
  })

  test('row keyboard handling is a pure index rule', () => {
    expect(nextIndexForKey('ArrowDown', 1, 5)).toBe(2)
    expect(nextIndexForKey('ArrowUp', 0, 5)).toBe(0)
    expect(nextIndexForKey('End', 0, 5)).toBe(4)
    expect(nextIndexForKey(' ', 0, 5)).toBeNull()
  })
})

// The golden graph with the labels the demo records.
const LABELS: Record<string, string> = {
  dense: 'Dense',
  lexical: 'Lexical',
  recency_filter: 'Recency Filter',
  'rerank@dense': 'Rerank (rerank@dense)',
  'rerank@lexical': 'Rerank (rerank@lexical)',
  fuse: 'Fuse',
  expand_gate: 'Expand Gate',
  expand: 'Expand',
  select: 'Select',
}
const LABELLED: PipelineGraph = { ...GRAPH, nodes: GRAPH.nodes.map((n) => ({ ...n, label: LABELS[n.node_id] })) }

/** Visible words of server-rendered markup. */
function words(html: string): string {
  return html.replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/\s+/g, ' ').trim()
}

describe('JourneyCard', () => {
  const props = { graph: LABELLED, stages: REFUND_STAGES, k: 3, singleNamespace: true }

  test('the expanded card is the named region with the numbered steps in words', () => {
    const html = renderToStaticMarkup(<JourneyCard row={legal} {...props} expanded isHeading />)
    expect(html).toContain('<section aria-labelledby="journey-detail-title"')
    expect(html).toContain('<h3 id="journey-detail-title" class="break-all font-mono text-sm font-semibold text-ink">doc-legal<span class="sr-only"> in question q-refund</span></h3>')
    expect(html).toContain('Correct, pushed out of the top 3')
    const steps = [...html.matchAll(/<li class="flex gap-3">([\s\S]*?)<\/li>/g)].map((m) => words(m[1]))
    expect(steps).toEqual([
      '1 Lexical found it at rank 4 Outside its own top 3',
      '2 Dense did not return it Not in its top 3',
      '3 Recency Filter moved it 4 → 2',
      '4 Rerank moved it 2 → 3',
      '5 Fuse moved it 3 → 5',
      '6 Expand Gate kept it at rank 5',
      '7 Expand was skipped for this question',
      '8 Select moved it 5 → 4 Below the top 3 cutoff',
      '9 Not delivered Final rank #4',
    ])
    // Raw kinds, states and ids stay inside the disclosure.
    expect(html).toContain('<summary class="cursor-pointer text-ink-muted">Technical details</summary>')
    const visible = outsideDetails(html)
    for (const raw of ['demoted', 'promoted', 'retained_below_cutoff', 'excluded', 'recorded', 'kb:doc-legal', 'uppercase', 'text-[11px]']) expect(visible).not.toContain(raw)
    expect(html).toContain('loss boundary select')
  })

  test('technical details keep the recorded transitions, boundary capture, ids and the permalink', () => {
    const html = renderToStaticMarkup(<JourneyCard row={policy} {...props} expanded isHeading />)
    const order = ['dense', 'lexical', 'recency_filter', 'rerank@dense', 'fuse', 'expand_gate', 'select'].map((op) => html.indexOf(`<span class="font-mono text-ink">${op}</span>`))
    expect(order.every((index, i) => index > 0 && (i === 0 || index > order[i - 1]))).toBe(true)
    expect(html).toContain('min_score <span class="text-ink-faint">(recorded)</span>')
    expect(html).toContain('Boundary capture')
    expect(html).toContain('source not recorded')
    expect(html).toContain(`value="${policy.investigation_link.replace(/&/g, '&amp;')}"`)
    expect(html).toContain('>Copy</button>')
    expect(html).toContain('trace-digest')
    expect(html).toContain('No content captured; ids only.')
    expect(html).not.toContain('boundary not fully captured')
    expect(words(outsideDetails(html))).toContain('3 Recency Filter removed it Reason: min_score')
    expect(words(outsideDetails(html))).toContain('8 Select kept it at rank 2 9 Delivered at #2')
  })

  test('an unknown event is not fully recorded; captured content shows when the payload carries it', () => {
    const html = renderToStaticMarkup(<JourneyCard row={faqOutage} {...props} expanded isHeading />)
    expect(words(outsideDetails(html))).toContain('5 Rerank : not fully recorded No reason can be given')
    expect(html).toContain('Not correct')
    expect(html).toContain('boundary not fully captured')
    expect(html).toContain('in recorded · out truncated')
    expect(html).toContain('deduplicated <span class="text-ink-faint">(recorded)</span>')
    const content = renderToStaticMarkup(<JourneyCard row={row({ metadata: { title: 'Refund policy' } })} {...props} expanded isHeading={false} />)
    expect(content).toContain('Refund policy')
    expect(content).toContain('Not observed at any captured boundary')
    expect(content).not.toContain('journey-detail-title')
    expect(content).not.toContain('<section')
  })

  test('a collapsed card is one button that selects the document', () => {
    const onSelect = vi.fn()
    const element = JourneyCard({ row: policy, ...props, expanded: false, isHeading: false, onSelect })
    element!.props.onClick()
    expect(onSelect).toHaveBeenCalledTimes(1)
    const html = renderToStaticMarkup(element!)
    expect(html.startsWith('<button type="button"')).toBe(true)
    expect(words(html)).toBe('doc-policy Correct, delivered Best rank #1')
    for (const nested of ['<details', '<h3', 'journey-detail-title', '<input']) expect(html).not.toContain(nested)
  })
})

describe('One question', () => {
  const parts = { graph: LABELLED, stages: REFUND_STAGES, k: 3, singleNamespace: true }

  test('the header names the question, counts its correct documents and explains the focused one', () => {
    const html = renderToStaticMarkup(<QuestionHeader queryId="q-refund" queryText="How do I get a refund?" relevant={[legal, policy]} focus={legal} {...parts} onBack={noop} />)
    expect(words(html)).toContain('← All questions · Question q-refund')
    expect(html).toContain('<h2 class="mt-1 text-[22px] font-semibold leading-tight text-ink">“How do I get a refund?”</h2>')
    expect(html).toContain('bg-status-negative/10 text-status-negative">1 of 2 correct in the top 3</span>')
    expect(words(html)).toContain("doc-legal : Lexical found it at rank 4; it was not in Dense's top 3; Select placed it 4th, below the top 3.")
    const all = renderToStaticMarkup(<QuestionHeader queryId="q-refund" queryText={null} relevant={[policy]} focus={policy} {...parts} onBack={noop} />)
    expect(all).toContain('<span class="font-mono">q-refund</span></h2>')
    expect(all).toContain('text-status-positive">1 of 1 correct in the top 3</span>')
    expect(words(all)).toContain('Dense found it at rank 1; Lexical found it at rank 1; Select delivered it at #2.')
    const none = renderToStaticMarkup(<QuestionHeader queryId="q-x" queryText="x" relevant={[]} focus={null} {...parts} onBack={noop} />)
    expect(none).toContain('This question has no correct documents recorded.')
  })

  test('only the focused correct document is expanded and carries the journey heading', () => {
    const html = renderToStaticMarkup(<CorrectDocuments relevant={[legal, policy]} focus={legal} {...parts} onSelect={noop} />)
    expect(html).toContain('Correct documents (2)')
    expect(html.match(/id="journey-detail-title"/g)).toHaveLength(1)
    expect(html).toContain('doc-legal<span class="sr-only"> in question q-refund</span>')
    expect(html.match(/<ol class="mt-3/g)).toHaveLength(1)
    expect(words(html)).toContain('doc-policy Correct, delivered Best rank #1')
    expect(html).not.toContain('Selected document')
  })

  test('a selected document that is not correct leads as "Selected document"; the correct ones stay collapsed', () => {
    const html = renderToStaticMarkup(<CorrectDocuments relevant={[legal, policy]} focus={news} {...parts} onSelect={noop} />)
    expect(html.indexOf('Selected document')).toBeLessThan(html.indexOf('Correct documents (2)'))
    expect(html.match(/id="journey-detail-title"/g)).toHaveLength(1)
    expect(html).toContain('doc-news<span class="sr-only"> in question q-refund</span>')
    expect(html.match(/<ol class="mt-3/g)).toHaveLength(1)
    expect(html.match(/<button type="button" class="flex w-full/g)).toHaveLength(2)
  })

  test('the delivered list ranks what the question delivered, without focusable rows', () => {
    const faqRefund = row({ entity_id: 'doc-faq', judgment: 'nonrelevant', grade: 0, final_rank: 1, outcome: 'judged_nonrelevant', events: [event('dense', 'introduced', null, 2), event('lexical', 'introduced', null, 1)] })
    const isSource = (opId: string) => opId === 'dense' || opId === 'lexical'
    const html = renderToStaticMarkup(<DeliveredList rows={[policy, faqRefund]} k={3} allDelivered={false} singleNamespace isSource={isSource} />)
    expect(html).toContain('>Delivered instead</h2>')
    expect(html).toContain('top 3')
    expect([...html.matchAll(/<th scope="col"[^>]*>([^<]+)/g)].map((m) => m[1])).toEqual(['Rank', 'Document', 'Judged', 'Came from'])
    const rows = [...html.matchAll(/<tr class="border-t[^>]*>([\s\S]*?)<\/tr>/g)].map((m) => words(m[1]))
    expect(rows).toEqual(['1 doc-faq Not correct lexical #1 · dense #2', '2 doc-policy Correct · grade 2 dense #1 · lexical #1'])
    expect(html).not.toContain('tabindex')
    expect(renderToStaticMarkup(<DeliveredList rows={[policy]} k={3} allDelivered singleNamespace />)).toContain('>Delivered</h2>')
    expect(renderToStaticMarkup(<DeliveredList rows="failed" k={3} allDelivered={false} singleNamespace />)).toContain('Could not load the delivered list')
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

function flowMiss(query_id: string, entity_id: string, outcome: FlowMiss['outcome'], loss_boundary: string | null, extra: Partial<FlowMiss> = {}): FlowMiss {
  return {
    query_id,
    query_text: null,
    namespace: 'kb',
    entity_id,
    trace_id: `t:${query_id}`,
    outcome,
    loss_boundary,
    final_rank: null,
    capture_state: 'complete',
    best_rank: null,
    best_op: null,
    pushed_out: false,
    events: [],
    question_relevant: 1,
    question_delivered: 0,
    ...extra,
  }
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
    expect(card(lost, 'select')).toContain('Rank 4 was 5 · below top 3')
    expect(card(lost, 'select')).not.toContain('Not delivered')
    expect(titles(lost).find((lines) => lines[1] === 'select')).toContain('was 5 · fell below the top 3 · Not delivered')
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
    expect(card(path, 'rrf')).toContain('Rank 36 was 14 · below top 10')
    expect(titles(path).find((lines) => lines[1] === 'rrf')).toContain('was 14 · fell below the top 10')
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
    expect(html).toContain('No pipeline steps were recorded for this run, so there is no diagram; the lists below still show everything indexed.')
  })
})

describe('Run view', () => {
  const DEMO_FLOW: InvestigationFlow = {
    ...FLOW,
    misses: [
      flowMiss('q-outage', 'doc-guide', 'relevant_excluded', 'recency_filter', { query_text: 'why is the site down', best_op: 'lexical', best_rank: 1 }),
      flowMiss('q-invoice', 'doc-archive', 'not_observed', 'not_observed', { query_text: 'invoice for order 42', question_relevant: 3, question_delivered: 2 }),
    ],
  }
  const missedProps = {
    questions: missedQuestions(DEMO_FLOW),
    k: 3,
    selection: DEFAULT_SELECTION,
    stage: null,
    stepLabel: (opId: string) => LABELS[opId] ?? opId,
    sort: null,
    onSort: noop,
    onSelect: noop,
  }

  test('the headline names the step that loses the most, its lost count in red; the lede numbers stand out', () => {
    const html = renderToStaticMarkup(<RunHeadline words={runHeadline(DEMO_FLOW, LABELLED)} />)
    expect(html).toContain('<h2 class="text-[22px] font-semibold leading-tight text-ink">Recency Filter loses the most correct documents: <span class="text-status-negative">1 of the 2</span> that missed the top 3.</h2>')
    expect(words(html)).toContain('4 of 6 correct documents ( 67% ) reached the top 3 across 3 questions. The one lost at Recency Filter was in the top 3 at an earlier step. 1 was never found by any search.')
    expect(html).toContain('<span class="font-semibold text-ink">67%</span>')
    expect(html).toContain('text-[15px]')
    // A digit inside a step name is not a number of the sentence.
    const named = renderToStaticMarkup(<RunHeadline words={{ headline: 'x', lede: ['Of the 3 lost at Search (bm25), 1 was in the top 10 at an earlier step.'], lost: null }} />)
    expect(named).toContain('Search (bm25)')
    expect(named.match(/font-semibold text-ink">/g)).toHaveLength(3)
    const none = renderToStaticMarkup(<RunHeadline words={runHeadline({ ...FLOW, totals: { ...FLOW.totals, relevant: 0 } }, LABELLED)} />)
    expect(none).toContain('This run has no correct answers recorded, so losses can&#x27;t be counted.')
    expect(none).not.toContain('<p')
  })

  test('the missed list: reason chips filter it, each question reads its correct count and what happened', () => {
    const html = renderToStaticMarkup(<MissedQuestions {...missedProps} />)
    expect(html).toContain('<h2 id="missed-title"')
    expect(html).toContain('Questions that missed a correct document (2)')
    expect([...html.matchAll(/<button type="button" aria-pressed="(true|false)"[^>]*>([^<]+)<\/button>/g)].map((m) => `${m[2]} ${m[1]}`)).toEqual([
      'Ranked too low or pushed out · 0 (0 pushed out) false',
      'Dropped · 1 false',
      'Never found · 1 false',
    ])
    // Each question's counts come with its misses from the flow.
    expect(words(html)).toContain('why is the site down q-outage 0 of 1 correct in top 3 Dropped by Recency Filter Lexical had it at #1')
    expect(words(html)).toContain('invoice for order 42 q-invoice 2 of 3 correct in top 3 Never found by any search')
    expect(html).not.toContain('role="status"')
    expect(html).not.toContain('Clear filters')
    const dropped = renderToStaticMarkup(<MissedQuestions {...missedProps} selection={{ ...DEFAULT_SELECTION, outcome: 'relevant_excluded' }} />)
    expect(dropped).toContain('aria-pressed="true"')
    expect(dropped).toContain('1 question · 1 shown')
    expect(dropped).not.toContain('q-invoice')
    expect(dropped).toContain('Clear filters')
  })

  test('a reason no chip offers still leaves a way out: Clear filters next to the section heading', () => {
    const html = renderToStaticMarkup(<MissedQuestions {...missedProps} selection={{ ...DEFAULT_SELECTION, outcome: 'judged_nonrelevant' }} />)
    expect(html).not.toContain('aria-pressed="true"')
    expect(html).toContain('0 questions · 0 shown')
    expect(words(html)).toContain('Questions that missed a correct document (2) Clear filters')
    const atStep = renderToStaticMarkup(<MissedQuestions {...missedProps} stage={{ id: 'select', name: 'Select' }} selection={{ ...DEFAULT_SELECTION, stage: 'select' }} />)
    expect(words(atStep)).toContain('Questions that missed a correct document (2) Clear filters')
  })

  test('a selected step filters the list under a banner that clears it', () => {
    const html = renderToStaticMarkup(<MissedQuestions {...missedProps} stage={{ id: 'recency_filter', name: 'Recency Filter' }} />)
    expect(html).toContain('role="status"')
    expect(words(html)).toContain('Showing questions where Recency Filter lost a correct document (1) Clear')
    expect(html).toContain('1 question · 1 shown')
    expect(html).not.toContain('q-invoice')
    const none = renderToStaticMarkup(<MissedQuestions {...missedProps} stage={{ id: 'select', name: 'Select' }} />)
    expect(words(none)).toContain('Select lost no correct documents. Clear')
    expect(none).not.toContain('<table')
  })

  test('the documents list leads with the correct documents that were missed', () => {
    const documents = missedDocuments(DEMO_FLOW)
    const html = renderToStaticMarkup(<MissedQuestions {...missedProps} kind="documents" questions={documents} singleNamespace />)
    expect(html).toContain('Correct documents that were missed (2)')
    expect(html).toContain('Correct documents that missed the top k and what happened to them')
    expect(words(html)).toContain('doc-archive 1 question Never found by any search Question q-invoice')
    expect(words(html)).toContain('doc-guide 1 question Dropped by Recency Filter Question q-outage · Lexical had it at #1')
    expect(html).toContain('2 documents · 2 shown')
    // Phone second lines are 13 px, not the 12 px floor.
    expect(html).toContain('max-sm:text-[13px]')
    expect(html).not.toContain('max-sm:text-xs')
    const atStep = renderToStaticMarkup(<MissedQuestions {...missedProps} kind="documents" questions={documents} singleNamespace stage={{ id: 'recency_filter', name: 'Recency Filter' }} />)
    expect(words(atStep)).toContain('Showing correct documents that Recency Filter lost (1) Clear')
    expect(atStep).not.toContain('doc-archive')
  })

  test('the missed list shows 50 questions at a time', () => {
    const many: InvestigationFlow = { ...FLOW, misses: Array.from({ length: 120 }, (_, i) => flowMiss(`q${i}`, 'doc', 'not_observed', 'not_observed')) }
    const html = renderToStaticMarkup(<MissedQuestions {...missedProps} questions={missedQuestions(many)} />)
    expect(html.match(/<tr tabindex="0"/g)).toHaveLength(50)
    expect(words(html)).toContain('50 of 120 questions Show more')
    expect(html).toContain('120 questions · 50 shown')
  })

  test('one document: its id and a sentence on the questions it is correct for', () => {
    const guide = row({ entity_id: 'doc-guide', query_id: 'q-outage', outcome: 'relevant_excluded', final_rank: null, loss_boundary: 'recency_filter' })
    const html = renderToStaticMarkup(<DocumentHeader entity="kb:doc-guide" rows={[guide, { ...policy, entity_id: 'doc-guide', query_id: 'q-invoice' }, { ...news, entity_id: 'doc-guide' }]} questions={3} singleNamespace onBack={noop} />)
    expect(words(html)).toContain('← All documents · Document doc-guide')
    expect(html).toContain('<h2 class="mt-1 text-[22px] font-semibold leading-tight text-ink">Correct for 2 questions: delivered in 1, missed in 1.</h2>')
    expect(renderToStaticMarkup(<DocumentHeader entity="kb:doc-news" rows={[news]} questions={2} singleNamespace={false} onBack={noop} />)).toContain('Not judged correct for any question; it appears in 2 questions.')
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
