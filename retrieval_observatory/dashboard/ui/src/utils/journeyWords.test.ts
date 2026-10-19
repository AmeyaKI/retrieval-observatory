import { describe, expect, test } from 'vitest'
import type { InvestigationStage, JourneyEvent, JourneyRow, PipelineGraph, PipelineGraphNode } from '../api'
import { documentSentence, journeySteps, ordinal, ranksTrail, verdictSentence } from './journeyWords'

const emptyMetrics = { 'ndcg@10': null, recall: null, latency_p50: null }
const emptyLatency = { count: 0, mean_ms: null, p50_ms: null, p95_ms: null }

function node(node_id: string, op_type: string, label: string): PipelineGraphNode {
  return {
    node_id,
    label,
    op_type,
    depth: 0,
    branch_id: null,
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
    is_final_output: false,
    final_output_count: 0,
    configured: null,
    availability: {},
  }
}

function graphOf(pipeline_id: string, nodes: PipelineGraphNode[]): PipelineGraph {
  return {
    pipeline_id,
    contract_version: 2,
    projection_mode: 'run_union',
    trace_count: 3,
    complete_trace_count: 3,
    status_counts: {},
    final_output_ids: [],
    timing_semantics: {},
    warnings: [],
    nodes,
    edges: [],
  }
}

function event(op_id: string, kind: JourneyEvent['kind'], input_rank: number | null, output_rank: number | null, extra: Partial<JourneyEvent> = {}): JourneyEvent {
  return {
    op_id,
    operator_id: op_id,
    invocation_id: `inv-${op_id}`,
    branch: null,
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
    run_id: 'run',
    pipeline_id: 'p',
    trace_id: 't',
    query_id: 'q',
    namespace: 'kb',
    entity_id: 'doc',
    unit: 'document',
    entity_revision: null,
    judgment: 'relevant',
    grade: 1,
    judgment_source: 'qrels',
    final_membership: 'excluded',
    in_final_output: false,
    final_rank: null,
    outcome: 'relevant_excluded',
    confusion: 'FN',
    capture_state: 'complete',
    observed: true,
    loss_boundary: null,
    priority: 0,
    events: [],
    occurrence_entity_ids: [],
    evaluation_digest: 'e',
    judgment_digest: 'j',
    trace_digest: 't',
    investigation_link: '#/investigate',
    ...overrides,
  }
}

function stage(op_id: string, op_type: string, status: string, emitted: number): InvestigationStage {
  return {
    op_id,
    operator_id: op_id,
    invocation_id: `inv-${op_id}`,
    op_type,
    status,
    branch: null,
    parent_ids: [],
    input_capture: 'recorded',
    output_capture: 'recorded',
    received: 0,
    emitted,
    removed: 0,
    introduced: 0,
  }
}

// The real run bf9b1a02, question 1: its correct document 31715818.
const REAL_GRAPH = graphOf('rag_search-retrieval', [node('bm25', 'SOURCE', 'Search (bm25)'), node('dense', 'SOURCE', 'Search (dense)'), node('rrf', 'FUSE', 'Fuse Hits')])
const REAL_STAGES = [stage('dense', 'SOURCE', 'FIRED', 100), stage('bm25', 'SOURCE', 'FIRED', 100), stage('rrf', 'FUSE', 'FIRED', 100)]
const REAL_MISS = row({
  query_id: '1',
  namespace: 'default',
  entity_id: '31715818',
  final_rank: 36,
  outcome: 'retained_below_cutoff',
  loss_boundary: 'rrf',
  events: [event('dense', 'introduced', null, 14), event('rrf', 'demoted', 14, 36)],
})

// The seeded demo run c25c2be3 (golden-hybrid), question q-outage.
const DEMO_GRAPH = graphOf('golden-hybrid', [
  node('dense', 'SOURCE', 'Dense'),
  node('lexical', 'SOURCE', 'Lexical'),
  node('recency_filter', 'FILTER', 'Recency Filter'),
  node('rerank@dense', 'RERANK', 'Rerank (rerank@dense)'),
  node('rerank@lexical', 'RERANK', 'Rerank (rerank@lexical)'),
  node('fuse', 'FUSE', 'Fuse'),
  node('expand_gate', 'GATE', 'Expand Gate'),
  node('expand', 'EXPAND', 'Expand'),
  node('select', 'TRANSFORM', 'Select'),
])
const DEMO_STAGES = [
  stage('dense', 'SOURCE', 'FIRED', 2),
  stage('lexical', 'SOURCE', 'FIRED', 3),
  stage('recency_filter', 'FILTER', 'FIRED', 0),
  stage('rerank@dense', 'RERANK', 'FIRED', 2),
  stage('rerank@lexical', 'RERANK', 'FIRED', 0),
  stage('fuse', 'FUSE', 'FIRED', 2),
  stage('expand_gate', 'GATE', 'FIRED', 2),
  stage('expand', 'EXPAND', 'SKIPPED_BY_GATE', 0),
  stage('select', 'TRANSFORM', 'FIRED', 2),
]
const GUIDE = row({
  query_id: 'q-outage',
  entity_id: 'doc-guide',
  loss_boundary: 'recency_filter',
  events: [event('lexical', 'introduced', null, 1), event('recency_filter', 'removed', 1, null, { reason: 'min_score' })],
})
// Removed from the lexical lane but delivered through the dense lane.
const FAQ = row({
  query_id: 'q-outage',
  entity_id: 'doc-faq',
  final_membership: 'included',
  in_final_output: true,
  final_rank: 1,
  outcome: 'relevant_delivered',
  confusion: 'TP',
  events: [
    event('dense', 'introduced', null, 1),
    event('lexical', 'introduced', null, 2),
    event('recency_filter', 'removed', 2, null, { reason: 'min_score' }),
    event('rerank@dense', 'retained', 1, 1),
    event('fuse', 'retained', 1, 1),
    event('expand_gate', 'retained', 1, 1),
    event('select', 'retained', 1, 1),
  ],
})

// Demo q-invoice: doc-guide's two chunks. Select keeps chunk-1 at #2 and removes chunk-2 as a duplicate (the seeded events).
const chunk2 = { occurrence_entity_id: 'doc-guide/chunk-2', candidate_id: 'kb:doc-guide/chunk-2' }
const chunk1 = { occurrence_entity_id: 'doc-guide/chunk-1', candidate_id: 'kb:doc-guide/chunk-1' }
const INVOICE_GUIDE = row({
  query_id: 'q-invoice',
  entity_id: 'doc-guide',
  final_membership: 'included',
  in_final_output: true,
  final_rank: 2,
  outcome: 'relevant_delivered',
  confusion: 'TP',
  events: [
    event('dense', 'introduced', null, 1, chunk1),
    event('lexical', 'introduced', null, 1, chunk2),
    event('recency_filter', 'removed', 1, null, { ...chunk2, reason: 'min_score' }),
    event('rerank@dense', 'demoted', 1, 2, chunk1),
    event('fuse', 'retained', 2, 2, chunk1),
    event('expand_gate', 'retained', 2, 2, chunk1),
    event('expand', 'retained', 2, 2, chunk1),
    event('expand', 'recovered', null, 4, { ...chunk2, reason: 'expanded' }),
    event('select', 'retained', 2, 2, chunk1),
    event('select', 'removed', 4, null, { ...chunk2, reason: 'duplicate_document' }),
  ],
})

const texts = (steps: ReturnType<typeof journeySteps>) => steps.map((step) => step.text)

describe('journeySteps', () => {
  test('real question 1: found by dense, absent from bm25, fused below the cutoff', () => {
    const steps = journeySteps(REAL_MISS, REAL_GRAPH, REAL_STAGES, 10)
    expect(steps).toEqual([
      { opId: 'dense', name: 'Search (dense)', tone: 'accent', text: 'Search (dense) found it at rank 14', sub: 'Outside its own top 10' },
      { opId: 'bm25', name: 'Search (bm25)', tone: 'faint', text: 'Search (bm25) did not return it', sub: 'Not in its top 100' },
      { opId: 'rrf', name: 'Fuse Hits', tone: 'negative', text: 'Fuse Hits moved it 14 → 36', sub: 'Below the top 10 cutoff' },
      { opId: null, name: '', tone: 'neutral', text: 'Not delivered', sub: 'Final rank #36' },
    ])
  })

  test('demo q-outage: the filter removes the correct document; the gated step is named as skipped', () => {
    const steps = journeySteps(GUIDE, DEMO_GRAPH, DEMO_STAGES, 3)
    expect(texts(steps)).toEqual([
      'Lexical found it at rank 1',
      'Dense did not return it',
      'Recency Filter removed it',
      'Expand was skipped for this question',
      'Not delivered',
    ])
    expect(steps[0].sub).toBe('In its own top 3')
    expect(steps[1].sub).toBe('Not in its top 2')
    expect(steps[2]).toMatchObject({ tone: 'negative', sub: 'Reason: min_score' })
    expect(steps[3].tone).toBe('faint')
  })

  test('a lane removal that another lane recovered is neutral, and the delivered document closes positive', () => {
    const steps = journeySteps(FAQ, DEMO_GRAPH, DEMO_STAGES, 3)
    expect(texts(steps)).toEqual([
      'Dense found it at rank 1',
      'Lexical found it at rank 2',
      'Recency Filter removed it',
      'Rerank kept it at rank 1',
      'Fuse kept it at rank 1',
      'Expand Gate kept it at rank 1',
      'Expand was skipped for this question',
      'Select kept it at rank 1',
      'Delivered at #1',
    ])
    expect(steps[2].tone).toBe('neutral')
    expect(steps[8].tone).toBe('positive')
  })

  test('an unknown event says it was not fully recorded; spans not loaded say "Not returned"', () => {
    const partial = row({
      outcome: 'insufficient_evidence',
      loss_boundary: 'rerank@lexical',
      events: [event('lexical', 'introduced', null, 2), event('rerank@lexical', 'unknown', 2, null, { reason_evidence: 'unavailable', boundary_complete: false })],
    })
    const steps = journeySteps(partial, DEMO_GRAPH, null, 3)
    expect(steps[1]).toMatchObject({ opId: 'dense', text: 'Dense did not return it', sub: 'Not returned' })
    expect(steps[2]).toMatchObject({ tone: 'warning', text: 'Rerank: not fully recorded', sub: 'No reason can be given' })
    expect(verdictSentence(partial, DEMO_GRAPH, null, 3)).toBe('Lexical found it at rank 2; Dense did not return it; Rerank did not record what happened to it.')
  })

  test('a step that removed a duplicate chunk but output another keeps the document at its output rank', () => {
    const steps = journeySteps(INVOICE_GUIDE, DEMO_GRAPH, DEMO_STAGES, 3)
    expect(steps.find((step) => step.opId === 'select')).toEqual({ opId: 'select', name: 'Select', tone: 'neutral', text: 'Select kept it at rank 2', sub: 'Removed a duplicate occurrence' })
    expect(steps[steps.length - 1]).toMatchObject({ tone: 'positive', text: 'Delivered at #2' })
    expect(verdictSentence(INVOICE_GUIDE, DEMO_GRAPH, DEMO_STAGES, 3)).toBe('Dense found it at rank 1; Lexical found it at rank 1; Select delivered it at #2.')
    // As the loss boundary (a top 1), the step placed it below the cutoff; it did not remove it.
    const lost = { ...INVOICE_GUIDE, final_membership: 'excluded' as const, outcome: 'retained_below_cutoff' as const, loss_boundary: 'select' }
    expect(journeySteps(lost, DEMO_GRAPH, DEMO_STAGES, 1).find((step) => step.opId === 'select')).toMatchObject({ tone: 'negative', sub: 'Below the top 1 cutoff · Removed a duplicate occurrence' })
    expect(verdictSentence(lost, DEMO_GRAPH, DEMO_STAGES, 1)).toBe('Dense found it at rank 1; Lexical found it at rank 1; Select placed it 2nd, below the top 1.')
    // A reason that is not recorded as a duplicate only says another occurrence was kept.
    const other = { ...INVOICE_GUIDE, events: INVOICE_GUIDE.events.map((e) => (e.reason === 'duplicate_document' ? { ...e, reason: null } : e)) }
    expect(journeySteps(other, DEMO_GRAPH, DEMO_STAGES, 3).find((step) => step.opId === 'select')!.sub).toBe('Kept another occurrence')
  })

  test('several events at one step fold into one entry', () => {
    const chunks = row({ loss_boundary: 'fuse', events: [event('dense', 'introduced', null, 1), event('dense', 'introduced', null, 4), event('fuse', 'demoted', 1, 5), event('fuse', 'demoted', 4, 7)] })
    // The document's rank at a step is its best occurrence's: best input → best output.
    expect(texts(journeySteps(chunks, DEMO_GRAPH, DEMO_STAGES, 3)).slice(0, 2)).toEqual(['Dense found it at rank 1', 'Lexical did not return it'])
    expect(journeySteps(chunks, DEMO_GRAPH, DEMO_STAGES, 3).find((s) => s.opId === 'fuse')!.text).toBe('Fuse moved it 1 → 5')
  })

  test('a step that kept one chunk and brought another back kept the document at its best rank (demo q-invoice, doc-guide at expand)', () => {
    const expand = journeySteps(INVOICE_GUIDE, DEMO_GRAPH, DEMO_STAGES, 3).find((s) => s.opId === 'expand')!
    expect(expand).toMatchObject({ tone: 'neutral', text: 'Expand kept it at rank 2', sub: null })
    const tail = { ...INVOICE_GUIDE, events: INVOICE_GUIDE.events.filter((e) => ['fuse', 'expand_gate', 'expand', 'select'].includes(e.op_id)) }
    expect(ranksTrail(tail, (id) => DEMO_GRAPH.nodes.find((n) => n.node_id === id)!.label)).toBe('Fuse #2 → Expand Gate #2 → Expand #2 → Select #2')
    // "Brought it back" only when no event at the step had the document in its input.
    const back = { ...INVOICE_GUIDE, events: INVOICE_GUIDE.events.filter((e) => !(e.op_id === 'expand' && e.kind === 'retained')) }
    expect(journeySteps(back, DEMO_GRAPH, DEMO_STAGES, 3).find((s) => s.opId === 'expand')!.text).toBe('Expand brought it back at rank 4')
  })
})

describe('verdictSentence', () => {
  test('reads like the design examples', () => {
    expect(verdictSentence(REAL_MISS, REAL_GRAPH, REAL_STAGES, 10)).toBe(
      "Search (dense) found it at rank 14; it was not in Search (bm25)'s top 100; Fuse Hits placed it 36th, below the top 10.",
    )
    expect(verdictSentence(GUIDE, DEMO_GRAPH, DEMO_STAGES, 3)).toBe("Lexical found it at rank 1; it was not in Dense's top 2; Recency Filter removed it (min_score).")
  })

  test('a delivered document names the step that delivered it and leaves out a lane removal', () => {
    expect(verdictSentence(FAQ, DEMO_GRAPH, DEMO_STAGES, 3)).toBe('Dense found it at rank 1; Lexical found it at rank 2; Select delivered it at #1.')
  })

  test('a document no search returned', () => {
    const never = row({ outcome: 'not_observed', observed: false, loss_boundary: 'not_observed' })
    expect(verdictSentence(never, DEMO_GRAPH, DEMO_STAGES, 3)).toBe('No search returned it.')
    expect(texts(journeySteps(never, DEMO_GRAPH, DEMO_STAGES, 3))).toEqual(['Dense did not return it', 'Lexical did not return it', 'Expand was skipped for this question', 'Not delivered'])
  })

  test('ordinals', () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 36, 101, 111, 112, 113].map(ordinal)).toEqual([
      '1st', '2nd', '3rd', '4th', '11th', '12th', '13th', '21st', '22nd', '23rd', '36th', '101st', '111th', '112th', '113th',
    ])
  })
})

describe('ranksTrail', () => {
  const nameOf = (id: string) => DEMO_GRAPH.nodes.find((n) => n.node_id === id)?.label.replace(/ \(.*\)$/, '') ?? id

  test('one hop per step: its rank, or removed', () => {
    expect(ranksTrail(GUIDE, nameOf)).toBe('Lexical #1 → Recency Filter removed')
    expect(ranksTrail(REAL_MISS, (id) => REAL_GRAPH.nodes.find((n) => n.node_id === id)!.label)).toBe('Search (dense) #14 → Fuse Hits #36')
    expect(ranksTrail(row({ events: [] }), nameOf)).toBe('—')
  })

  test('searches that ran side by side share one hop', () => {
    const both = row({ events: [event('dense', 'introduced', null, 3), event('bm25', 'introduced', null, 8), event('rrf', 'promoted', 3, 4)] })
    const realName = (id: string) => REAL_GRAPH.nodes.find((n) => n.node_id === id)!.label
    const isSource = (id: string) => REAL_GRAPH.nodes.find((n) => n.node_id === id)?.op_type === 'SOURCE'
    expect(ranksTrail(both, realName, isSource)).toBe('Search (dense) #3 · Search (bm25) #8 → Fuse Hits #4')
    // Without the graph, a step that only introduced the document counts as a search.
    expect(ranksTrail(both, realName)).toBe('Search (dense) #3 · Search (bm25) #8 → Fuse Hits #4')
  })

  test('more than four hops keep the first three and the last; the searches count as one', () => {
    expect(ranksTrail(FAQ, nameOf)).toBe('Dense #1 · Lexical #2 → Recency Filter removed → Rerank #1 → … → Select #1')
  })

  test('a step that kept one occurrence and removed another shows the kept rank; unknown reads not recorded', () => {
    const twice = row({ events: [event('dense', 'introduced', null, 1), event('select', 'retained', 2, 2), event('select', 'removed', 4, null, chunk2)] })
    expect(ranksTrail(twice, nameOf)).toBe('Dense #1 → Select #2')
    const unknown = row({ events: [event('lexical', 'introduced', null, 1), event('rerank@lexical', 'unknown', 1, null)] })
    expect(ranksTrail(unknown, nameOf)).toBe('Lexical #1 → Rerank not recorded')
  })
})

describe('documentSentence', () => {
  test('correct for how many questions, delivered in and missed in how many', () => {
    const other = row({ query_id: 'q-refund', judgment: 'unjudged', outcome: 'unjudged' })
    // One document (doc-guide) over its questions: dropped for q-outage, delivered for q-invoice.
    const delivered = { ...FAQ, entity_id: 'doc-guide', query_id: 'q-invoice' }
    expect(documentSentence([GUIDE, other], 2)).toBe('Correct for 1 question: delivered in 0, missed in 1.')
    expect(documentSentence([delivered, GUIDE, other], 3)).toBe('Correct for 2 questions: delivered in 1, missed in 1.')
    expect(documentSentence([other], 4)).toBe('Not judged correct for any question; it appears in 4 questions.')
    expect(documentSentence([other], 1)).toBe('Not judged correct for any question; it appears in 1 question.')
  })
})
