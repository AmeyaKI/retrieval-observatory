import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'
// api.ts reads window.location.origin at import time; the node test environment has no window.
vi.hoisted(() => {
  ;(globalThis as { window?: unknown }).window = { location: { origin: 'http://localhost' } }
})
import type { InvestigationDocumentRow, InvestigationStage, JourneyEvent, JourneyRow, PipelineGraph, PipelineGraphNode, QuerySummaryRow, StageSummary } from '../api'
import { DEFAULT_SELECTION } from '../context/dashboardQuery'
import { nextIndexForKey, pathHighlight } from '../utils/queryDebugger'
import InvestigationDetail from './InvestigationDetail'
import InvestigationGraph, { CARD_GEOMETRY, MAX_OVERLAY_LINES, nodeOverlay, STAGE_CARD_H, StageCard } from './InvestigationGraph'
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

describe('InvestigationGraph', () => {
  const graphProps = { selectedStageId: null, highlight: null, collapsed: true, onToggleCollapsed: noop, onSelectStage: noop }

  test('aggregate overlay states served queries with the denominator', () => {
    expect(nodeOverlay('expand', AGGREGATE, 'aggregate', true).lines[0]).toBe('served 1 of 3 queries')
    expect(nodeOverlay('recency_filter', AGGREGATE, 'aggregate', true).lines).toEqual(['served 3 of 3 queries', 'received 10 candidates', 'removed 4 · introduced 0', 'unknown boundaries 0'])
    expect(nodeOverlay('rerank@lexical', AGGREGATE, 'aggregate', true).glyph).toBe('⚠')
    expect(nodeOverlay('ghost', AGGREGATE, 'aggregate', true).lines).toEqual(['no invocations recorded'])
    const html = renderToStaticMarkup(<InvestigationGraph graph={GRAPH} stages={AGGREGATE} mode="aggregate" {...graphProps} />)
    expect(html).toContain('served 1 of 3 queries')
    expect(html).toContain('role="group"')
    expect(html).toContain('aria-label="Pipeline golden-hybrid: 9 operators, 9 edges; showing counts over the whole run"')
    expect(html).toContain('aria-label="Legend"')
    expect(html).toContain('SKIPPED_BY_GATE')
    expect(html).toContain('aria-label="Zoom in"')
    expect(html).toContain('aria-label="Zoom out"')
    expect(html).toContain('aria-label="Reset zoom"')
    expect(html).toContain('Operator table (accessible equivalent)')
    expect(html).not.toContain('repeated invocations')
  })

  test('query overlay shows the trace status as text with a glyph and labels unobserved nodes', () => {
    const skipped = nodeOverlay('expand', REFUND_STAGES, 'query', true)
    expect(skipped.lines[0]).toBe('SKIPPED_BY_GATE')
    expect(skipped.glyph).toBe('⊘')
    expect(nodeOverlay('rerank@lexical', REFUND_STAGES, 'query', true)).toMatchObject({ lines: ['FIRED', 'in recorded · out truncated', 'received 3 · emitted 3 candidates'], glyph: '⚠' })
    expect(nodeOverlay('ghost', REFUND_STAGES, 'query', true).lines).toEqual(['not observed for this query'])
    const html = renderToStaticMarkup(<InvestigationGraph graph={GRAPH} stages={REFUND_STAGES} mode="query" {...graphProps} selectedStageId="select" />)
    expect(html).toContain('SKIPPED_BY_GATE')
    expect(html).toContain('>⊘<')
    expect(html).toContain('aria-pressed="true"')
    expect(html).toContain('showing one query’s execution; select selected')
  })

  test('a highlighted path annotates its nodes with the event kind and thickens its edges', () => {
    const highlight = pathHighlight(policy, GRAPH)
    const html = renderToStaticMarkup(<InvestigationGraph graph={GRAPH} stages={REFUND_STAGES} mode="query" {...graphProps} highlight={highlight} />)
    expect(html).toContain('✕</span> removed')
    expect(html).toContain('+</span> introduced')
    expect(html).toContain('↓</span> demoted')
    expect(html.match(/data-on-path="true"/g)).toHaveLength(5)
    expect(html).toContain('path through dense, lexical, recency_filter, rerank@dense, fuse, expand_gate, select')
  })

  test('collapses repeated invocations by default with an explicit expand control', () => {
    const collapsedHtml = renderToStaticMarkup(<InvestigationGraph graph={REPEATED_GRAPH} stages={null} mode="aggregate" {...graphProps} />)
    expect(collapsedHtml).toContain('Expand repeated invocations (1)')
    expect(collapsedHtml).toContain('3 operators, 2 edges')
    const expandedHtml = renderToStaticMarkup(<InvestigationGraph graph={REPEATED_GRAPH} stages={null} mode="aggregate" {...graphProps} collapsed={false} />)
    expect(expandedHtml).toContain('Collapse repeated invocations (1)')
    expect(expandedHtml).toContain('4 operators, 4 edges')
  })

  test('every card reserves the maximum overlay lines plus the path-event line, with or without a selected journey', () => {
    const g = CARD_GEOMETRY
    const content = g.header + g.label + MAX_OVERLAY_LINES * g.line + g.path + (MAX_OVERLAY_LINES + 2) * g.gap
    expect(STAGE_CARD_H).toBeGreaterThanOrEqual(g.border + g.paddingY + content)
    // No overlay renders more lines than the card reserves, in either mode or when unobserved.
    for (const id of GRAPH.nodes.map((n) => n.node_id).concat('ghost')) {
      expect(nodeOverlay(id, AGGREGATE, 'aggregate', true).lines.length).toBeLessThanOrEqual(MAX_OVERLAY_LINES)
      expect(nodeOverlay(id, REFUND_STAGES, 'query', true).lines.length).toBeLessThanOrEqual(MAX_OVERLAY_LINES)
      expect(nodeOverlay(id, null, 'query', true).lines.length).toBeLessThanOrEqual(MAX_OVERLAY_LINES)
    }
    const heights = (html: string) => [...html.matchAll(/<foreignObject[^>]*height="([\d.]+)"/g)].map((m) => Number(m[1]))
    const plain = renderToStaticMarkup(<InvestigationGraph graph={GRAPH} stages={AGGREGATE} mode="aggregate" {...graphProps} />)
    const highlighted = renderToStaticMarkup(<InvestigationGraph graph={GRAPH} stages={AGGREGATE} mode="aggregate" {...graphProps} highlight={pathHighlight(policy, GRAPH)} />)
    expect(heights(plain)).toHaveLength(GRAPH.nodes.length)
    expect(new Set(heights(plain))).toEqual(new Set([STAGE_CARD_H]))
    // Layout is stable: selecting a journey does not move or resize any card.
    expect(heights(highlighted)).toEqual(heights(plain))
    expect(highlighted.match(/<foreignObject[^>]*>/g)).toEqual(plain.match(/<foreignObject[^>]*>/g))
    // The classes that pin the geometry above (py-2 = 16px, h-4/leading-4 = 16px, label 18px, lines 12px).
    for (const pinned of ['py-2', 'flex h-4', 'leading-[18px]', 'leading-[12px]', 'font-medium leading-4']) expect(highlighted).toContain(pinned)
  })

  test('operator cards are keyboard-reachable buttons that select the stage like a click', () => {
    const html = renderToStaticMarkup(<InvestigationGraph graph={GRAPH} stages={AGGREGATE} mode="aggregate" {...graphProps} selectedStageId="fuse" />)
    // The container is a named group, not an image, so its buttons stay in the accessibility tree.
    expect(html).not.toContain('role="img"')
    expect(html.match(/<button type="button" aria-pressed="(true|false)"/g)).toHaveLength(GRAPH.nodes.length)
    expect(html).not.toContain('tabindex="-1"')
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1)
    const onSelect = vi.fn()
    const fuse = { ...GRAPH.nodes.find((n) => n.node_id === 'fuse')!, x: 0, y: 0, w: 200, h: STAGE_CARD_H }
    const card = StageCard({ node: fuse, overlay: nodeOverlay('fuse', AGGREGATE, 'aggregate', true), kind: null, selected: true, dimmed: false, onSelect })
    const button = card.props.children
    expect(button.type).toBe('button')
    // Enter and Space activate a native button through the same onClick.
    button.props.onClick()
    expect(onSelect).toHaveBeenCalledWith('fuse')
    // Selection is stated in text, not only by the border colour.
    expect(renderToStaticMarkup(card)).toContain('>selected<')
  })

  test('says so when no topology was recorded', () => {
    const html = renderToStaticMarkup(<InvestigationGraph graph={null} stages={AGGREGATE} mode="aggregate" {...graphProps} />)
    expect(html).toContain('No pipeline topology recorded')
  })
})

describe('OperatorInspector', () => {
  test('reports every count with its denominator and the capture labels, without attribution', () => {
    const html = renderToStaticMarkup(<OperatorInspector opId="expand" stage={REFUND_STAGES.find((s) => s.op_id === 'expand')!} aggregate={AGGREGATE.find((s) => s.op_id === 'expand')!} />)
    expect(html).toContain('1<span class="text-ink-muted"> of 3</span> <span class="font-sans text-ink-muted">queries</span>')
    expect(html).toContain('Skipped by gate')
    expect(html).toContain('2<span class="text-ink-muted"> of 3</span>')
    expect(html).toContain('candidates over 1 served queries')
    expect(html).toContain('SKIPPED_BY_GATE')
    expect(html).toContain('unavailable')
    expect(html).toContain('Input capture')
    expect(html).toContain('Output capture')
    expect(html.toLowerCase()).not.toContain('attribution')
  })

  test('explains the missing aggregate before the index is built', () => {
    const html = renderToStaticMarkup(<OperatorInspector opId="select" stage={null} aggregate={null} />)
    expect(html).toContain('No stored aggregate for this operator')
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
