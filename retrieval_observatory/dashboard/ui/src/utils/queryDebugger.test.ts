import { describe, expect, it } from 'vitest'
import type { JourneyEvent, JourneyRow, PipelineGraph, PipelineGraphNode } from '../api'
import {
  cameFrom,
  contentPreview,
  displayEntity,
  evidenceLabel,
  focusRowFor,
  isPushedOut,
  judgedText,
  nextIndexForKey,
  OUTCOME_LABELS,
  outcomeLabel,
  outcomeText,
  outcomeTone,
  pathHighlight,
  principalLossBoundaries,
  queryRollups,
  sortForView,
  stageFilter,
  transitionText,
} from './queryDebugger'

// Rows mirror tests/fixtures/investigation_cases.py (golden-hybrid: dense + lexical lanes,
// recency_filter on the lexical lane, one reranker invoked per lane, RRF fuse, gated expand, select).

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
    evaluation_digest: 'eval',
    judgment_digest: 'judg',
    trace_digest: 'trace',
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
  priority: 3,
  events: [
    event('lexical', 'introduced', null, 4),
    event('recency_filter', 'promoted', 4, 2),
    event('rerank@lexical', 'demoted', 2, 3),
    event('fuse', 'demoted', 3, 5),
    event('expand_gate', 'retained', 5, 5),
    event('select', 'promoted', 5, 4),
  ],
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
  priority: 20,
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
  priority: 30,
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
  priority: 0,
})

const missed = row({
  trace_id: 'trace-q-invoice',
  query_id: 'q-invoice',
  entity_id: 'doc-missed',
  final_membership: 'excluded',
  in_final_output: false,
  final_rank: null,
  outcome: 'relevant_excluded',
  confusion: 'FN',
  loss_boundary: 'select',
  priority: 1,
  events: [event('dense', 'introduced', null, 3), event('rerank@dense', 'retained', 3, 3), event('fuse', 'retained', 3, 3), event('expand_gate', 'retained', 3, 3), event('select', 'removed', 3, null, { reason: 'budget', reason_evidence: 'inferred' })],
})

const unknownRow = row({
  trace_id: 'trace-q-outage',
  query_id: 'q-outage',
  entity_id: 'doc-guide',
  final_membership: 'unknown',
  in_final_output: null,
  final_rank: null,
  outcome: 'insufficient_evidence',
  confusion: 'unknown',
  capture_state: 'partial',
  loss_boundary: 'unknown',
  priority: 2,
  events: [event('lexical', 'introduced', null, 1), event('rerank@lexical', 'unknown', 1, null, { reason_evidence: 'unavailable', boundary_complete: false })],
})

const emptyMetrics = { 'ndcg@10': null, recall: null, latency_p50: null }
const emptyLatency = { count: 0, mean_ms: null, p50_ms: null, p95_ms: null }

function graphNode(node_id: string, op_type: string, depth: number, extra: Partial<PipelineGraphNode> = {}): PipelineGraphNode {
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

const GOLDEN_GRAPH: PipelineGraph = {
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
    graphNode('dense', 'SOURCE', 0),
    graphNode('lexical', 'SOURCE', 0),
    graphNode('recency_filter', 'FILTER', 1),
    graphNode('rerank@dense', 'RERANK', 1),
    graphNode('rerank@lexical', 'RERANK', 2),
    graphNode('fuse', 'FUSE', 3),
    graphNode('expand_gate', 'GATE', 4),
    graphNode('expand', 'EXPAND', 5, { observed_count: 1, fire_rate: 1 / 3, status_counts: { FIRED: 1, SKIPPED_BY_GATE: 2 } }),
    graphNode('select', 'TRANSFORM', 6),
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

describe('pathHighlight', () => {
  it('lists the golden doc-policy path in event order with its kinds and no incomplete boundary', () => {
    const path = pathHighlight(policy)
    expect(path.nodeIds).toEqual(['dense', 'lexical', 'recency_filter', 'rerank@dense', 'fuse', 'expand_gate', 'select'])
    expect(path.kinds).toEqual({ dense: 'introduced', lexical: 'introduced', recency_filter: 'removed', 'rerank@dense': 'retained', fuse: 'demoted', expand_gate: 'retained', select: 'retained' })
    expect(path.incomplete).toEqual([])
    expect(path.edges).toEqual([
      ['dense', 'lexical'],
      ['lexical', 'recency_filter'],
      ['recency_filter', 'rerank@dense'],
      ['rerank@dense', 'fuse'],
      ['fuse', 'expand_gate'],
      ['expand_gate', 'select'],
    ])
  })

  it('validates edges against the graph so only parent-linked lanes are drawn', () => {
    const path = pathHighlight(policy, GOLDEN_GRAPH)
    // One entry per path node in path order, so the lexical lane's edge lands before the dense lane's.
    expect(path.edges).toEqual([
      ['lexical', 'recency_filter'],
      ['dense', 'rerank@dense'],
      ['rerank@dense', 'fuse'],
      ['fuse', 'expand_gate'],
      ['expand_gate', 'select'],
    ])
  })

  it('names the operator whose boundary was not captured', () => {
    const path = pathHighlight(faqOutage, GOLDEN_GRAPH)
    expect(path.incomplete).toEqual(['rerank@lexical'])
    expect(path.kinds['rerank@lexical']).toBe('unknown')
    expect(path.nodeIds).toContain('rerank@lexical')
  })

  it('has no edges for an entity never observed', () => {
    expect(pathHighlight(archive, GOLDEN_GRAPH)).toEqual({ nodeIds: [], edges: [], kinds: {}, incomplete: [] })
  })
})

describe('outcome vocabulary', () => {
  const outcomes = Object.keys(OUTCOME_LABELS) as Array<keyof typeof OUTCOME_LABELS>
  it('covers all seven outcomes with plain words and a tone', () => {
    expect(outcomes).toHaveLength(7)
    expect(Object.fromEntries(outcomes.map((outcome) => [outcome, [outcomeLabel(outcome), outcomeTone(outcome)]]))).toEqual({
      relevant_delivered: ['Correct, delivered', 'positive'],
      relevant_excluded: ['Correct, dropped', 'negative'],
      retained_below_cutoff: ['Correct, ranked too low', 'negative'],
      not_observed: ['Correct, never found', 'negative'],
      judged_nonrelevant: ['Not correct', 'neutral'],
      unjudged: ['Not judged', 'neutral'],
      insufficient_evidence: ['Not enough evidence', 'warning'],
    })
  })

  it('falls back to the raw value and a neutral tone for an unknown outcome', () => {
    expect(outcomeLabel('later_outcome')).toBe('later_outcome')
    expect(outcomeTone('later_outcome')).toBe('neutral')
  })

  it('says "pushed out of the top k" when another step had the document in the top k (the server rule)', () => {
    // legal: retained below the cutoff at select; recency_filter had it at #2, inside the top 3.
    expect(isPushedOut(legal, 3)).toBe(true)
    expect(outcomeText(legal, 3)).toBe('Correct, pushed out of the top 3')
    // Inside the top 3 only at the loss boundary itself, or never: ranked too low.
    expect(isPushedOut(legal, 1)).toBe(false)
    expect(outcomeText(legal, 1)).toBe('Correct, ranked too low')
    expect(isPushedOut(legal, null)).toBe(false)
    expect(outcomeText(missed, 3)).toBe('Correct, dropped')
  })

  it('states the judgment, the source lanes and the id in plain words', () => {
    expect(judgedText(policy)).toBe('Correct · grade 2')
    expect(judgedText(legal)).toBe('Correct')
    expect(judgedText(faqOutage)).toBe('Not correct')
    expect(judgedText(news)).toBe('Not judged')
    const isSource = (opId: string) => GOLDEN_GRAPH.nodes.find((n) => n.node_id === opId)?.op_type === 'SOURCE'
    expect(cameFrom(policy, isSource)).toBe('dense #1 · lexical #1')
    expect(cameFrom(faqOutage, isSource)).toBe('dense #1 · lexical #2')
    expect(cameFrom(row({ events: [event('dense', 'introduced', null, 16), event('lexical', 'introduced', null, 4), event('expand', 'introduced', null, 1)] }), isSource)).toBe('lexical #4 · dense #16')
    expect(cameFrom(archive, isSource)).toBe('—')
    expect(displayEntity(policy, true)).toBe('doc-policy')
    expect(displayEntity(policy, false)).toBe('kb:doc-policy')
  })

  it('maps reason evidence to the three user-facing labels', () => {
    expect(evidenceLabel('recorded')).toBe('recorded')
    expect(evidenceLabel('inferred')).toBe('inferred')
    expect(evidenceLabel('legacy_inferred')).toBe('inferred')
    expect(evidenceLabel('unavailable')).toBe('unavailable')
    expect(evidenceLabel(null)).toBe('unavailable')
  })
})

describe('stageFilter', () => {
  it('keeps rows lost at the stage and rows with a branch-local removal or unknown there', () => {
    const rows = [policy, legal, news, faqOutage, archive]
    expect(stageFilter(rows, 'recency_filter').map((r) => r.entity_id)).toEqual(['doc-policy', 'doc-news'])
    expect(stageFilter(rows, 'rerank@lexical').map((r) => r.entity_id)).toEqual(['doc-faq'])
    expect(stageFilter(rows, 'select').map((r) => r.entity_id)).toEqual(['doc-legal'])
    expect(stageFilter(rows, null)).toBe(rows)
  })
})

describe('focusRowFor', () => {
  it('follows the URL entity, else the first correct document missed, else the first correct one', () => {
    const rows = [faqOutage, policy, news, missed, legal]
    expect(focusRowFor(rows, 'kb:doc-news', null)).toBe(news)
    expect(focusRowFor(rows, 'kb:doc-news', 'other-trace')).toBe(missed)
    expect(focusRowFor(rows, null, null)).toBe(missed)
    expect(focusRowFor([faqOutage, policy, news], null, null)).toBe(policy)
    expect(focusRowFor([faqOutage, news], null, null)).toBeNull()
  })
})

describe('sortForView', () => {
  it('puts complete relevant misses first, then evidence-limited rows, delivered relevant rows, and the rest', () => {
    const sorted = sortForView([news, faqOutage, unknownRow, policy, missed, archive], 'queries')
    expect(sorted.map((r) => `${r.query_id}/${r.entity_id}`)).toEqual([
      'q-invoice/doc-archive',
      'q-invoice/doc-missed',
      'q-outage/doc-guide',
      'q-refund/doc-policy',
      'q-outage/doc-faq',
      'q-refund/doc-news',
    ])
  })

  it('puts a relevant document retained below the cutoff above unjudged rows', () => {
    const below = row({ query_id: 'q-a', entity_id: 'doc-z', outcome: 'retained_below_cutoff', final_membership: 'excluded', in_final_output: false })
    const unjudged = ['doc-a', 'doc-b'].map((entity_id) => row({ query_id: 'q-a', entity_id, judgment: 'unjudged', outcome: 'unjudged' }))
    expect(sortForView([...unjudged, below], 'queries').map((r) => r.entity_id)).toEqual(['doc-z', 'doc-a', 'doc-b'])
  })

  it('orders the documents view by query then entity', () => {
    const sorted = sortForView([news, faqOutage, policy, archive], 'documents')
    expect(sorted.map((r) => `${r.query_id}/${r.entity_id}`)).toEqual(['q-invoice/doc-archive', 'q-outage/doc-faq', 'q-refund/doc-news', 'q-refund/doc-policy'])
  })
})

describe('row helpers', () => {
  it('rolls up per-query counts from rows and names the principal loss boundary', () => {
    const [refund] = queryRollups([policy, legal, news])
    expect(refund).toEqual({
      query_id: 'q-refund',
      trace_ids: ['trace-q-refund'],
      rows: 3,
      relevant_delivered: 1,
      relevant_missed: 1,
      unjudged_included: 0,
      unknown_capture: 0,
      boundaries: ['select'],
    })
  })

  it('names at most three stored loss boundaries with their counts, most frequent first', () => {
    expect(principalLossBoundaries({ select: 1, recency_filter: 3, not_observed: 2, unknown: 1 })).toEqual(['recency_filter ×3', 'not_observed ×2', 'select ×1'])
    expect(principalLossBoundaries({})).toEqual([])
  })

  it('renders the compact transition sequence with removal and unknown marks only', () => {
    expect(transitionText(news)).toBe('lexical ▸ recency_filter ✕')
    expect(transitionText(policy)).toBe('dense ▸ lexical ▸ recency_filter ✕ ▸ rerank@dense ▸ fuse ▸ expand_gate ▸ select')
    expect(transitionText(faqOutage)).toContain('rerank@lexical ◌')
  })

  it('previews captured content only when the payload carries it', () => {
    expect(contentPreview(policy)).toBeNull()
    expect(contentPreview(row({ metadata: { title: 'Refund policy' } }))).toBe('Refund policy')
    expect(contentPreview(row({ events: [event('dense', 'introduced', null, 1, { metadata: { text: 'Refunds within 30 days.' } })] }))).toBe('Refunds within 30 days.')
  })

  it('moves row focus with the arrow, Home and End keys only', () => {
    expect(nextIndexForKey('ArrowDown', 0, 3)).toBe(1)
    expect(nextIndexForKey('ArrowDown', 2, 3)).toBe(2)
    expect(nextIndexForKey('ArrowUp', 0, 3)).toBe(0)
    expect(nextIndexForKey('ArrowUp', 2, 3)).toBe(1)
    expect(nextIndexForKey('Home', 2, 3)).toBe(0)
    expect(nextIndexForKey('End', 0, 3)).toBe(2)
    expect(nextIndexForKey('Enter', 1, 3)).toBeNull()
    expect(nextIndexForKey('ArrowDown', 0, 0)).toBeNull()
  })
})
