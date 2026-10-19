import { describe, expect, test } from 'vitest'
import type { InvestigationStage, JourneyEvent, JourneyRow, PipelineGraph, PipelineGraphNode } from '../api'
import { journeySteps, ordinal, verdictSentence } from './journeyWords'

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

  test('several events at one step fold into one entry', () => {
    const chunks = row({ loss_boundary: 'fuse', events: [event('dense', 'introduced', null, 1), event('dense', 'introduced', null, 4), event('fuse', 'demoted', 1, 5), event('fuse', 'demoted', 4, 7)] })
    expect(texts(journeySteps(chunks, DEMO_GRAPH, DEMO_STAGES, 3)).slice(0, 2)).toEqual(['Dense found it at rank 4', 'Lexical did not return it'])
    expect(journeySteps(chunks, DEMO_GRAPH, DEMO_STAGES, 3).find((s) => s.opId === 'fuse')!.text).toBe('Fuse moved it 1 → 7')
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
