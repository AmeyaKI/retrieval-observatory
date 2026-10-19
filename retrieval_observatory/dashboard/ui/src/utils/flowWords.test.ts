import { describe, expect, test } from 'vitest'
import type { FlowMiss, FlowStep, InvestigationFlow, InvestigationStage, JourneyEvent, PipelineGraph, PipelineGraphNode, StageSummary } from '../api'
import {
  captureWord,
  filterMissed,
  flowStepOf,
  foldedAggregate,
  foldedStage,
  foldFlow,
  missedDocuments,
  missedQuestions,
  missLine,
  pathCard,
  questionCard,
  reasonChips,
  resultWords,
  runCard,
  runHeadline,
  statusWord,
  stepKind,
  stepName,
} from './flowWords'

const emptyMetrics = { 'ndcg@10': null, recall: null, latency_p50: null }
const emptyLatency = { count: 0, mean_ms: null, p50_ms: null, p95_ms: null }

function node(node_id: string, op_type: string, extra: Partial<PipelineGraphNode> = {}): PipelineGraphNode {
  return {
    node_id,
    label: node_id,
    op_type,
    depth: 0,
    branch_id: null,
    candidate_count: 3,
    metrics: emptyMetrics,
    is_merge: false,
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
    ...extra,
  }
}

function graphOf(nodes: PipelineGraphNode[], trace_count: number): PipelineGraph {
  return {
    pipeline_id: 'p',
    contract_version: 2,
    projection_mode: 'run_union',
    trace_count,
    complete_trace_count: trace_count,
    status_counts: {},
    final_output_ids: nodes.filter((n) => n.is_final_output).map((n) => n.node_id),
    timing_semantics: {},
    warnings: [],
    nodes,
    edges: [],
  }
}

function step(seen: number, input: number, output: number, in_top_k: number, removed = 0, removed_but_delivered = 0, lost: Partial<FlowStep['lost']> = {}): FlowStep {
  const full = { dropped: 0, ranked_low: 0, pushed_out: 0, unknown: 0, ...lost }
  return { seen, input, output, in_top_k, removed, removed_but_delivered, lost: full, lost_total: full.dropped + full.ranked_low + full.pushed_out }
}

function flowOf(k: number, relevant: number, delivered: number, steps: Record<string, FlowStep>, copresence: Record<string, number> = {}): InvestigationFlow {
  return {
    k,
    totals: { relevant, delivered, missed: relevant - delivered, never_found: 0, insufficient: 0, questions: 3, questions_judged: 3, questions_with_miss: 0, questions_with_none: 0 },
    steps,
    copresence,
    misses: [],
  }
}

// The real run bf9b1a02 (rag_search-retrieval).
const DENSE = node('dense', 'SOURCE', { label: 'Search (dense)', status_counts: { FIRED: 300 } })
const RRF = node('rrf', 'FUSE', { label: 'Fuse Hits', is_final_output: true, status_counts: { FIRED: 300 } })
const REAL_GRAPH = graphOf([DENSE, node('bm25', 'SOURCE', { label: 'Search (bm25)' }), RRF], 300)
const REAL_FLOW = flowOf(10, 339, 288, {
  dense: step(321, 0, 321, 283),
  bm25: step(311, 0, 311, 272),
  rrf: step(331, 331, 328, 288, 3, 0, { dropped: 3, ranked_low: 26, pushed_out: 14 }),
})

// The seeded demo run c25c2be3 (golden-hybrid).
const RECENCY = node('recency_filter', 'FILTER', { label: 'Recency Filter' })
const RERANK_LEXICAL = node('rerank@lexical', 'RERANK', { label: 'Rerank (rerank@lexical)' })
const EXPAND = node('expand', 'EXPAND', { label: 'Expand', fire_rate: 1 / 3, status_counts: { FIRED: 1, SKIPPED_BY_GATE: 2 } })
const SELECT = node('select', 'TRANSFORM', { label: 'Select', is_final_output: true })
const DEMO_GRAPH = graphOf([RECENCY, RERANK_LEXICAL, EXPAND, SELECT], 3)
const DEMO_FLOW = flowOf(3, 6, 4, {
  recency_filter: step(5, 5, 0, 0, 5, 4, { dropped: 1 }),
  expand: step(2, 2, 2, 2),
  select: step(4, 4, 4, 4, 1, 1),
})

function stage(op_id: string, status: string, extra: Partial<InvestigationStage> = {}): InvestigationStage {
  return {
    op_id,
    operator_id: op_id,
    invocation_id: null,
    op_type: 'RERANK',
    status,
    branch: null,
    parent_ids: [],
    input_capture: 'recorded',
    output_capture: 'recorded',
    received: 3,
    emitted: 3,
    removed: 0,
    introduced: 0,
    ...extra,
  }
}

function event(op_id: string, kind: JourneyEvent['kind'], input_rank: number | null, output_rank: number | null, reason: string | null = null): JourneyEvent {
  return {
    op_id,
    operator_id: op_id,
    invocation_id: null,
    branch: null,
    occurrence_entity_id: 'e',
    candidate_id: 'e',
    kind,
    input_present: input_rank != null,
    output_present: output_rank != null,
    input_rank,
    output_rank,
    input_occurrences: 1,
    reason,
    reason_evidence: 'recorded',
    boundary_complete: true,
    input_evidence: 'recorded',
    source_occurrences: [],
  }
}

describe('plain words', () => {
  test('step kinds, statuses and capture states', () => {
    expect(['SOURCE', 'FUSE', 'RERANK', 'BOOST', 'EXPAND', 'FILTER', 'GATE', 'TRANSFORM', 'GENERATE', 'CUSTOM'].map(stepKind)).toEqual([
      'Retrieval',
      'Fusion',
      'Reranking',
      'Boost',
      'Expansion',
      'Filter',
      'Gate',
      'Step',
      'Generation',
      'Step',
    ])
    expect(['FIRED', 'SKIPPED_BY_GATE', 'ERROR', 'TIMEOUT', 'CACHE_HIT'].map(statusWord)).toEqual(['Ran', 'Skipped by a gate', 'Failed', 'Timed out', 'cache hit'])
    expect(['recorded', 'not_applicable', 'unavailable', 'partial', 'truncated', 'positional', 'inferred'].map(captureWord)).toEqual([
      'Recorded',
      '',
      'Not recorded',
      'Partly recorded',
      'Partly recorded',
      'Partly recorded',
      'Partly recorded',
    ])
  })

  test('step names split a "Name (id)" label and show the id only when the label does not', () => {
    expect(stepName({ label: 'Rerank (rerank@dense)', node_id: 'rerank@dense' })).toEqual({ name: 'Rerank', id: 'rerank@dense' })
    expect(stepName({ label: 'Search (dense)', node_id: 'dense' })).toEqual({ name: 'Search (dense)', id: null })
    expect(stepName({ label: 'Fuse Hits', node_id: 'rrf' })).toEqual({ name: 'Fuse Hits', id: 'rrf' })
    expect(stepName({ label: 'Dense', node_id: 'dense' })).toEqual({ name: 'Dense', id: 'dense' })
    expect(stepName({ label: 'select', node_id: 'select' })).toEqual({ name: 'select', id: null })
    expect(stepName({ label: 'A long descriptive step name', node_id: 'x' })).toEqual({ name: 'A long descriptive step name', id: 'x' })
    expect(stepName({ label: 'a_very_long_node_identifier', node_id: 'a_very_long_node_identifier' })).toEqual({ name: 'a_very_long_node_identifier', id: null })
  })
})

describe('folding repeated invocations', () => {
  const flow = flowOf(3, 2, 1, { source: step(2, 0, 2, 2), rerank: step(2, 2, 2, 1), 'rerank#2': step(2, 2, 1, 1, 1, 0, { dropped: 1 }) }, { 'source→rerank': 2, 'source→rerank#2': 2, 'rerank→rerank#2': 2 })

  test('sums op#N onto op and drops self-pairs; identity when expanded', () => {
    expect(foldFlow(flow, false)).toBe(flow)
    expect(foldFlow(null, true)).toBeNull()
    const folded = foldFlow(flow, true)!
    expect(Object.keys(folded.steps).sort()).toEqual(['rerank', 'source'])
    expect(folded.steps.rerank).toMatchObject({ seen: 4, input: 4, output: 3, removed: 1, lost: { dropped: 1 }, lost_total: 1 })
    expect(folded.copresence).toEqual({ 'source→rerank': 4 })
  })

  test('the misses name the folded step too', () => {
    const lost = { ...flow, misses: [miss('q1', 'd1', 'relevant_excluded', 'rerank#2', { best_op: 'rerank#2', best_rank: 1 }), miss('q2', 'd2', 'not_observed', 'not_observed')] }
    expect(foldFlow(lost, true)!.misses.map((m) => [m.loss_boundary, m.best_op])).toEqual([
      ['rerank', 'rerank'],
      ['not_observed', null],
    ])
    expect(foldFlow(lost, false)!.misses[0].loss_boundary).toBe('rerank#2')
  })

  test('a step missing from a loaded flow counts zeros; no flow stays null', () => {
    expect(flowStepOf(flow, 'ghost')).toMatchObject({ seen: 0, input: 0, lost_total: 0 })
    expect(flowStepOf(null, 'source')).toBeNull()
  })

  test('aggregates and one question’s spans fold the same way', () => {
    const summaries: StageSummary[] = [
      { op_id: 'rerank', operator_id: 'rerank', queries_served: 3, queries_skipped: 0, candidates_received: 9, removal_events: 1, introduced: 0, partial_boundaries: 0 },
      { op_id: 'rerank#2', operator_id: 'rerank', queries_served: 2, queries_skipped: 1, candidates_received: 4, removal_events: 2, introduced: 0, partial_boundaries: 1 },
    ]
    expect(foldedAggregate(summaries, 'rerank', true)).toMatchObject({ op_id: 'rerank', queries_served: 5, queries_skipped: 1, candidates_received: 13, removal_events: 3, partial_boundaries: 1 })
    expect(foldedAggregate(summaries, 'rerank', false)).toMatchObject({ queries_served: 3 })
    expect(foldedAggregate(null, 'rerank', true)).toBeNull()
    const spans = [stage('rerank', 'FIRED'), stage('rerank#2', 'ERROR', { output_capture: 'truncated', received: 2, emitted: 1 })]
    expect(foldedStage(spans, 'rerank', true)).toMatchObject({ op_id: 'rerank', status: 'ERROR', output_capture: 'truncated', received: 5, emitted: 4 })
    expect(foldedStage(spans, 'rerank#2', false)).toBe(spans[1])
    expect(foldedStage(null, 'rerank', true)).toBeUndefined()
  })
})

describe('runCard', () => {
  test('the real run: a search finds, the fusion loses and delivers', () => {
    expect(runCard(DENSE, REAL_FLOW.steps.dense, REAL_FLOW, REAL_GRAPH, null)).toEqual({
      metric: 'Found 321 of 339',
      note: '283 in its top 10',
      noteTone: null,
      badge: null,
      ghost: false,
    })
    // The only final output with a loss: the result moves into the note.
    expect(runCard(RRF, REAL_FLOW.steps.rrf, REAL_FLOW, REAL_GRAPH, null)).toEqual({
      metric: '331 correct in',
      note: '288 of 339 in top 10',
      noteTone: 'positive',
      badge: { tone: 'negative', text: 'Lost 43' },
      ghost: false,
    })
    // With a separate result card the final step carries only its own facts.
    expect(runCard(RRF, REAL_FLOW.steps.rrf, REAL_FLOW, REAL_GRAPH, null, true)).toMatchObject({ note: null, badge: { tone: 'negative', text: 'Lost 43' } })
  })

  test('the demo run: removals, an empty lane, a gated step and the final result', () => {
    expect(runCard(RECENCY, DEMO_FLOW.steps.recency_filter, DEMO_FLOW, DEMO_GRAPH, null)).toMatchObject({
      metric: '5 correct in',
      badge: { tone: 'negative', text: 'Lost 1' },
      note: 'Removed 5 · 4 still delivered',
    })
    expect(runCard(RERANK_LEXICAL, flowStepOf(DEMO_FLOW, 'rerank@lexical'), DEMO_FLOW, DEMO_GRAPH, null)).toMatchObject({ metric: 'None reached it', badge: null, note: null })
    expect(runCard(EXPAND, DEMO_FLOW.steps.expand, DEMO_FLOW, DEMO_GRAPH, null)).toMatchObject({ metric: '2 correct in', ghost: true, note: 'Ran for 1 of 3 questions' })
    // The final result replaces a neutral removal badge; the removal stays in the title (and the step panel).
    expect(runCard(SELECT, DEMO_FLOW.steps.select, DEMO_FLOW, DEMO_GRAPH, null)).toMatchObject({
      metric: '4 correct in',
      badge: { tone: 'positive', text: '4 of 6 in top 3' },
      note: null,
      fullNote: 'Removed 1 · all still delivered',
    })
    expect(runCard(SELECT, DEMO_FLOW.steps.select, DEMO_FLOW, DEMO_GRAPH, null, true)).toMatchObject({
      badge: { tone: 'neutral', text: 'Removed 1' },
      note: 'all still delivered',
    })
  })

  test('a removal with nothing lost is neutral and never blames a lane', () => {
    const flow = flowOf(3, 6, 4, { f: step(4, 4, 2, 2, 2, 1) })
    const words = runCard(node('f', 'FILTER'), flow.steps.f, flow, graphOf([node('f', 'FILTER')], 3), null)
    expect(words.badge).toEqual({ tone: 'neutral', text: 'Removed 2' })
    expect(words.note).toBe('1 still delivered')
    expect(JSON.stringify(words)).not.toContain('lane')
  })

  test('several final outputs get no result badge', () => {
    const a = node('a', 'TRANSFORM', { is_final_output: true })
    const flow = flowOf(3, 6, 4, { a: step(4, 4, 4, 4) })
    expect(runCard(a, flow.steps.a, flow, graphOf([a, node('b', 'TRANSFORM', { is_final_output: true })], 3), null).badge).toBeNull()
  })

  test('without judgments it falls back to the stored candidate counts', () => {
    const aggregate: StageSummary = { op_id: 'dense', operator_id: 'dense', queries_served: 300, queries_skipped: 0, candidates_received: 0, removal_events: 0, introduced: 30000, partial_boundaries: 0 }
    expect(runCard(DENSE, null, null, REAL_GRAPH, aggregate)).toEqual({ metric: 'Ran for 300 of 300 questions', note: '30000 candidates found', noteTone: null, badge: null, ghost: false })
    const unjudged = flowOf(10, 0, 0, {})
    expect(runCard(RRF, null, unjudged, REAL_GRAPH, { ...aggregate, op_id: 'rrf', candidates_received: 60000, introduced: 0 })).toMatchObject({ note: '60000 candidates in', badge: null })
    expect(runCard(EXPAND, null, null, DEMO_GRAPH, null)).toMatchObject({ metric: 'Ran for 1 of 3 questions', ghost: true })
  })
})

describe('pathCard', () => {
  const fired = (op_type = 'RERANK') => stage('x', 'FIRED', { op_type, emitted: 100 })

  test('a step that found, kept, moved or removed the document', () => {
    expect(pathCard(node('lexical', 'SOURCE'), [event('lexical', 'introduced', null, 1, 'retrieved')], fired('SOURCE'), 3, false, null, false)).toMatchObject({
      badge: { tone: 'accent', text: 'Rank 1' },
      note: 'Found it',
    })
    expect(pathCard(RECENCY, [event('recency_filter', 'removed', 1, null, 'min_score')], fired(), 3, false, null, false)).toMatchObject({ badge: { tone: 'negative', text: 'Removed' }, note: 'min_score' })
    expect(pathCard(RECENCY, [event('recency_filter', 'removed', 1, null)], fired(), 3, false, null, false).note).toBe('No reason recorded')
    expect(pathCard(node('fuse', 'FUSE'), [event('fuse', 'demoted', 1, 2)], fired(), 3, false, null, false)).toMatchObject({ badge: { tone: 'accent', text: 'Rank 2' }, note: 'was 1' })
    expect(pathCard(node('fuse', 'FUSE'), [event('fuse', 'retained', 2, 2)], fired(), 3, false, null, false).note).toBeNull()
    expect(pathCard(node('r', 'RERANK'), [event('r', 'unknown', 2, null)], fired(), 3, false, null, false).badge).toEqual({ tone: 'warning', text: 'Not recorded' })
  })

  test('the loss boundary says the document fell below the top k; the final step says whether it was delivered', () => {
    // The card's note fits a phone (below the top k at the final step is not delivered); the title keeps the full words.
    expect(pathCard(SELECT, [event('select', 'promoted', 5, 4)], fired(), 3, true, null, true)).toEqual({
      metric: '',
      badge: { tone: 'negative', text: 'Rank 4' },
      note: 'was 5 · below top 3',
      fullNote: 'was 5 · fell below the top 3 · Not delivered',
      noteTone: 'negative',
      ghost: false,
    })
    expect(pathCard(RERANK_LEXICAL, [event('rerank@lexical', 'demoted', 2, 14)], fired(), 10, false, null, true)).toMatchObject({ note: 'was 2 · below top 10', fullNote: 'was 2 · fell below the top 10' })
    expect(pathCard(SELECT, [event('select', 'retained', 2, 2)], fired(), 3, true, 2, false)).toMatchObject({ badge: { tone: 'accent', text: 'Rank 2' }, note: 'Delivered at #2', noteTone: 'positive' })
  })

  test('a step that removed a duplicate chunk but kept the document at its output rank (demo q-invoice, doc-guide at select)', () => {
    const chunk = (e: JourneyEvent, occurrence: string): JourneyEvent => ({ ...e, occurrence_entity_id: occurrence, candidate_id: `kb:${occurrence}` })
    const kept = chunk(event('select', 'retained', 2, 2), 'doc-guide/chunk-1')
    const duplicate = chunk(event('select', 'removed', 4, null, 'duplicate_document'), 'doc-guide/chunk-2')
    expect(pathCard(SELECT, [kept, duplicate], fired(), 3, false, null, false)).toMatchObject({ badge: { tone: 'accent', text: 'Rank 2' }, note: 'Removed a duplicate occurrence' })
    // On the final card the delivery leads; the removal of the duplicate stays in the title (and the journey card).
    expect(pathCard(SELECT, [kept, duplicate], fired(), 3, true, 2, false)).toMatchObject({
      badge: { tone: 'accent', text: 'Rank 2' },
      note: 'Delivered at #2',
      fullNote: 'Removed a duplicate occurrence · Delivered at #2',
      noteTone: 'positive',
    })
    // A removal reason that does not say duplicate (or was not recorded) only says another occurrence was kept.
    expect(pathCard(SELECT, [kept, { ...duplicate, reason: 'min_score' }], fired(), 3, false, null, false).note).toBe('Kept another occurrence')
    expect(pathCard(SELECT, [kept, { ...duplicate, reason_evidence: 'inferred' }], fired(), 3, false, null, false).note).toBe('Kept another occurrence')
    // The same occurrence kept by one invocation and removed by the next (folded) was removed.
    expect(pathCard(SELECT, [kept, chunk(event('select', 'removed', 2, null, 'min_score'), 'doc-guide/chunk-1')], fired(), 3, false, null, false)).toMatchObject({
      badge: { tone: 'negative', text: 'Removed' },
      note: 'min_score',
    })
  })

  test('a step that kept one chunk and brought another back shows the best rank (demo q-invoice, doc-guide at expand)', () => {
    const chunk = (e: JourneyEvent, occurrence: string): JourneyEvent => ({ ...e, occurrence_entity_id: occurrence, candidate_id: `kb:${occurrence}` })
    const events = [chunk(event('expand', 'retained', 2, 2), 'doc-guide/chunk-1'), chunk(event('expand', 'recovered', null, 4, 'expanded'), 'doc-guide/chunk-2')]
    expect(pathCard(EXPAND, events, fired(), 3, false, null, false)).toMatchObject({ badge: { tone: 'accent', text: 'Rank 2' }, note: null })
  })

  test('a step with no event for the document', () => {
    expect(pathCard(EXPAND, [], undefined, 3, false, null, false)).toMatchObject({ ghost: true, note: 'Not run for this question' })
    expect(pathCard(EXPAND, [], stage('expand', 'SKIPPED_BY_GATE'), 3, false, null, false)).toMatchObject({ ghost: true, note: 'Skipped for this question' })
    expect(pathCard(EXPAND, [], stage('expand', 'ERROR'), 3, false, null, false).badge).toEqual({ tone: 'warning', text: 'Failed' })
    expect(pathCard(EXPAND, [], stage('expand', 'TIMEOUT'), 3, false, null, false).badge).toEqual({ tone: 'warning', text: 'Timed out' })
    expect(pathCard(DENSE, [], fired('SOURCE'), 10, false, null, false)).toMatchObject({ ghost: false, note: 'Not in its top 100' })
    expect(pathCard(RERANK_LEXICAL, [], fired(), 3, false, null, false).note).toBe("Didn't reach it")
    // Spans not loaded (a document's view): no claim that the step did not run.
    expect(pathCard(DENSE, [], null, 10, false, null, false)).toMatchObject({ ghost: false, note: "Didn't find it" })
  })
})

describe('questionCard', () => {
  test('candidates in and out with the status and capture in words', () => {
    expect(questionCard(RERANK_LEXICAL, stage('rerank@lexical', 'FIRED', { output_capture: 'truncated' }))).toEqual({
      metric: '3 in · 3 out',
      note: 'Ran · Partly recorded',
      noteTone: null,
      badge: null,
      ghost: false,
    })
    expect(questionCard(EXPAND, stage('expand', 'SKIPPED_BY_GATE', { output_capture: 'unavailable', received: 0, emitted: 0 }))).toMatchObject({ ghost: true, note: 'Skipped by a gate' })
    expect(questionCard(EXPAND, undefined)).toMatchObject({ ghost: true, note: 'Not run for this question' })
    expect(questionCard(EXPAND, stage('expand', 'ERROR', { output_capture: 'unavailable' }))).toMatchObject({ note: 'Failed · Not recorded', noteTone: 'warning' })
  })
})

describe('resultWords', () => {
  test('the result card states the run’s delivered share, or one document’s fate', () => {
    expect(resultWords('run', REAL_FLOW, 10, null)).toEqual({ name: 'Top 10', figure: '288 of 339', note: 'correct delivered · 85%', noteTone: null })
    expect(resultWords('run', null, 10, null)).toMatchObject({ figure: null, note: 'No correct answers recorded' })
    expect(resultWords('path', REAL_FLOW, 10, 2)).toMatchObject({ note: 'Delivered at #2', noteTone: 'positive' })
    expect(resultWords('path', REAL_FLOW, 10, null)).toMatchObject({ note: 'Not delivered', noteTone: null })
    expect(resultWords('question', REAL_FLOW, 10, null).figure).toBeNull()
  })
})

function miss(query_id: string, entity_id: string, outcome: FlowMiss['outcome'], loss_boundary: string | null, extra: Partial<FlowMiss> = {}): FlowMiss {
  return {
    query_id,
    query_text: null,
    namespace: 'default',
    entity_id,
    trace_id: `t:${query_id}`,
    outcome,
    loss_boundary,
    final_rank: outcome === 'retained_below_cutoff' ? 36 : null,
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

/** The real run's 51 misses: at rrf 14 pushed out of the top 10, 26 ranked too low, 3 dropped; 8 never found. */
function realMisses(): FlowMiss[] {
  const list: FlowMiss[] = []
  for (let i = 0; i < 14; i += 1) list.push(miss(`p${i}`, `e${i}`, 'retained_below_cutoff', 'rrf', { best_op: 'dense', best_rank: 6, final_rank: 19, pushed_out: true }))
  for (let i = 0; i < 26; i += 1) list.push(miss(`r${i}`, `e${i}`, 'retained_below_cutoff', 'rrf', { best_op: 'dense', best_rank: 14 }))
  for (let i = 0; i < 3; i += 1) list.push(miss(`d${i}`, `e${i}`, 'relevant_excluded', 'rrf', { best_op: 'bm25', best_rank: 57 }))
  for (let i = 0; i < 8; i += 1) list.push(miss(`n${i}`, `e${i}`, 'not_observed', 'not_observed'))
  return list
}

describe('runHeadline', () => {
  const REAL: InvestigationFlow = { ...REAL_FLOW, totals: { ...REAL_FLOW.totals, never_found: 8, questions: 300 }, misses: realMisses() }

  test('the real run: one step loses the most, and the lede says how many were in the top k before', () => {
    expect(runHeadline(REAL, REAL_GRAPH)).toEqual({
      headline: 'Fuse Hits loses the most correct documents: 43 of the 51 that missed the top 10.',
      lede: [
        '288 of 339 correct documents (85%) reached the top 10 across 300 questions.',
        'Of the 43 lost at Fuse Hits, 14 were in the top 10 at an earlier step; 29 never were.',
        '8 were never found by any search.',
      ],
      lost: '43 of the 51',
    })
  })

  test('the demo run: the one document lost at the filter was in the top 3 at an earlier step', () => {
    const demo: InvestigationFlow = {
      ...DEMO_FLOW,
      totals: { ...DEMO_FLOW.totals, missed: 2, never_found: 1 },
      misses: [miss('q-outage', 'doc-guide', 'relevant_excluded', 'recency_filter', { best_op: 'lexical', best_rank: 1 }), miss('q-invoice', 'doc-archive', 'not_observed', 'not_observed')],
    }
    expect(runHeadline(demo, DEMO_GRAPH)).toEqual({
      headline: 'Recency Filter loses the most correct documents: 1 of the 2 that missed the top 3.',
      lede: ['4 of 6 correct documents (67%) reached the top 3 across 3 questions.', 'The one lost at Recency Filter was in the top 3 at an earlier step.', '1 was never found by any search.'],
      lost: '1 of the 2',
    })
    const never = { ...demo, misses: [{ ...demo.misses[0], best_rank: 5 }] }
    expect(runHeadline(never, DEMO_GRAPH).lede[1]).toBe('The one lost at Recency Filter was not in the top 3 at any earlier step.')
  })

  test('the earlier-step sentence: none, all, some, singular and plural', () => {
    const at = (before: number, lost: number) => {
      const misses = Array.from({ length: lost }, (_, i) => miss(`q${i}`, `e${i}`, 'retained_below_cutoff', 'rrf', { best_rank: i < before ? 2 : 40, pushed_out: i < before }))
      const flow = flowOf(10, 20, 20 - lost, { rrf: step(20, 20, 20, 20 - lost, 0, 0, { ranked_low: lost - before, pushed_out: before }) })
      return runHeadline({ ...flow, misses }, REAL_GRAPH).lede[1]
    }
    expect(at(0, 3)).toBe('None of the 3 lost at Fuse Hits was in the top 10 at an earlier step.')
    expect(at(3, 3)).toBe('All 3 lost at Fuse Hits were in the top 10 at an earlier step.')
    expect(at(1, 3)).toBe('Of the 3 lost at Fuse Hits, 1 was in the top 10 at an earlier step; 2 never were.')
    expect(at(2, 3)).toBe('Of the 3 lost at Fuse Hits, 2 were in the top 10 at an earlier step; 1 never was.')
  })

  test('steps that tie share the headline, in pipeline order', () => {
    const flow = flowOf(3, 6, 2, { select: step(4, 4, 2, 2, 2, 0, { dropped: 2 }), recency_filter: step(5, 5, 3, 3, 2, 0, { dropped: 2 }) })
    expect(runHeadline(flow, DEMO_GRAPH)).toEqual({
      headline: 'Recency Filter and Select each lose 2 of the 4 correct documents that missed the top 3.',
      lede: ['2 of 6 correct documents (33%) reached the top 3 across 3 questions.'],
      lost: '2 of the 4',
    })
    const three = flowOf(3, 6, 0, { select: step(4, 4, 2, 2, 2, 0, { dropped: 2 }), recency_filter: step(5, 5, 3, 3, 2, 0, { dropped: 2 }), expand: step(2, 2, 0, 0, 2, 0, { dropped: 2 }) })
    expect(runHeadline(three, DEMO_GRAPH).headline).toBe('Recency Filter, Expand and Select each lose 2 of the 6 correct documents that missed the top 3.')
  })

  test('nothing missed, only never-found misses, untraceable misses, no judgments', () => {
    expect(runHeadline(flowOf(10, 4, 4, { rrf: step(4, 4, 4, 4) }), REAL_GRAPH)).toEqual({
      headline: 'All 4 correct documents reached the top 10.',
      lede: ['4 of 4 correct documents (100%) reached the top 10 across 3 questions.'],
      lost: null,
    })
    const never = flowOf(10, 4, 3, { rrf: step(3, 3, 3, 3) })
    expect(runHeadline({ ...never, totals: { ...never.totals, never_found: 1 } }, REAL_GRAPH)).toEqual({
      headline: 'No step lost a correct document; 1 was never found by any search.',
      lede: ['3 of 4 correct documents (75%) reached the top 10 across 3 questions.'],
      lost: null,
    })
    const both = { ...never, totals: { ...never.totals, missed: 3, delivered: 1, never_found: 2, insufficient: 1 } }
    expect(runHeadline(both, REAL_GRAPH).headline).toBe('No step lost a correct document; 2 were never found by any search.')
    expect(runHeadline(both, REAL_GRAPH).lede[1]).toBe('1 could not be traced fully.')
    const unknown = { ...never, totals: { ...never.totals, insufficient: 1 } }
    expect(runHeadline(unknown, REAL_GRAPH).headline).toBe('No step lost a correct document; 1 could not be traced fully.')
    expect(runHeadline(flowOf(10, 0, 0, {}), REAL_GRAPH)).toEqual({ headline: "This run has no correct answers recorded, so losses can't be counted.", lede: [], lost: null })
  })

  test('a step without a graph node is named by its id', () => {
    expect(runHeadline(REAL, null).headline).toBe('rrf loses the most correct documents: 43 of the 51 that missed the top 10.')
  })
})

describe('the questions that missed a correct document', () => {
  const nameOf = (id: string) => ({ rrf: 'Fuse Hits', dense: 'Search (dense)', bm25: 'Search (bm25)', recency_filter: 'Recency Filter', lexical: 'Lexical' })[id] ?? id

  test('one plain line per missed document, with the step that ranked it best when the line does not say', () => {
    expect(missLine(miss('1', 'a', 'retained_below_cutoff', 'rrf', { best_op: 'dense', best_rank: 14 }), 10, nameOf)).toEqual({ text: 'Ranked too low at Fuse Hits · #36', sub: 'Search (dense) had it at #14' })
    expect(missLine(miss('1', 'a', 'retained_below_cutoff', 'rrf', { best_op: 'dense', best_rank: 6, final_rank: 19, pushed_out: true }), 10, nameOf)).toEqual({
      text: 'Pushed out of the top 10 by Fuse Hits · #6 → #19',
      sub: null,
    })
    expect(missLine(miss('1', 'a', 'relevant_excluded', 'rrf', { best_op: 'bm25', best_rank: 57 }), 10, nameOf)).toEqual({ text: 'Dropped by Fuse Hits', sub: 'Search (bm25) had it at #57' })
    expect(missLine(miss('1', 'a', 'not_observed', 'not_observed'), 10, nameOf)).toEqual({ text: 'Never found by any search', sub: null })
    expect(missLine(miss('1', 'a', 'insufficient_evidence', 'rrf'), 10, nameOf)).toEqual({ text: 'Not enough evidence at Fuse Hits', sub: null })
    // The rank at the losing step itself is already in the line.
    expect(missLine(miss('1', 'a', 'retained_below_cutoff', 'rrf', { best_op: 'rrf', best_rank: 36 }), 10, nameOf).sub).toBeNull()
  })

  const invoice = { question_relevant: 3, question_delivered: 1 }
  const split = { question_relevant: 2, question_delivered: 0 }
  const flow: InvestigationFlow = {
    ...DEMO_FLOW,
    misses: [
      miss('q-outage', 'doc-guide', 'relevant_excluded', 'recency_filter', { query_text: 'why is the site down', best_op: 'lexical', best_rank: 1 }),
      miss('q-invoice', 'doc-archive', 'not_observed', 'not_observed', { query_text: 'invoice for order 42', ...invoice }),
      miss('q-invoice', 'doc-late', 'retained_below_cutoff', 'select', { best_op: 'lexical', best_rank: 2, pushed_out: true, ...invoice }),
      miss('q-split', 'doc-x', 'retained_below_cutoff', 'select', { trace_id: 't:a', ...split }),
      miss('q-split', 'doc-y', 'retained_below_cutoff', 'select', { trace_id: 't:b', ...split }),
    ],
  }

  test('grouped by question in the server order, each with its own correct and delivered counts', () => {
    const questions = missedQuestions(flow)
    expect(questions.map((q) => [q.query_id, q.query_text, q.trace_id, q.misses.length, q.delivered, q.relevant])).toEqual([
      ['q-outage', 'why is the site down', 't:q-outage', 1, 0, 1],
      ['q-invoice', 'invoice for order 42', 't:q-invoice', 2, 1, 3],
      ['q-split', null, null, 2, 0, 2],
    ])
  })

  test('filters by a miss of the outcome and by the step that lost it', () => {
    const questions = missedQuestions(flow)
    expect(filterMissed(questions, { outcome: 'retained_below_cutoff' }).map((q) => q.query_id)).toEqual(['q-invoice', 'q-split'])
    expect(filterMissed(questions, { stage: 'recency_filter' }).map((q) => q.query_id)).toEqual(['q-outage'])
    expect(filterMissed(questions, { stage: 'select', outcome: 'not_observed' }).map((q) => q.query_id)).toEqual(['q-invoice'])
    expect(filterMissed(questions, { stage: null, outcome: null })).toEqual(questions)
  })

  test('missed documents: grouped by document, the most-missed first, filtered and counted like questions', () => {
    const twice = { ...flow, misses: [...flow.misses, miss('q-outage', 'doc-late', 'relevant_excluded', 'recency_filter')] }
    const documents = missedDocuments(twice)
    expect(documents.map((d) => [d.entity, d.misses.map((m) => m.query_id)])).toEqual([
      ['default:doc-late', ['q-invoice', 'q-outage']],
      ['default:doc-archive', ['q-invoice']],
      ['default:doc-guide', ['q-outage']],
      ['default:doc-x', ['q-split']],
      ['default:doc-y', ['q-split']],
    ])
    expect(filterMissed(documents, { stage: 'recency_filter' }).map((d) => d.entity_id)).toEqual(['doc-late', 'doc-guide'])
    expect(reasonChips(documents).map((chip) => chip.label)).toEqual(['Ranked too low or pushed out · 3 (1 pushed out)', 'Dropped · 2', 'Never found · 1'])
  })

  test('the reason chips count questions; the first also counts the documents pushed out', () => {
    expect(reasonChips(missedQuestions(flow)).map((chip) => chip.label)).toEqual(['Ranked too low or pushed out · 2 (1 pushed out)', 'Dropped · 1', 'Never found · 1'])
    const unknown = { ...flow, misses: [...flow.misses, miss('q-z', 'doc-z', 'insufficient_evidence', 'select')] }
    expect(reasonChips(missedQuestions(unknown)).map((chip) => [chip.outcome, chip.questions])).toEqual([
      ['retained_below_cutoff', 2],
      ['relevant_excluded', 1],
      ['not_observed', 1],
      ['insufficient_evidence', 1],
    ])
  })
})
