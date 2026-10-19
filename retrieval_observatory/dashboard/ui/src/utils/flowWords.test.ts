import { describe, expect, test } from 'vitest'
import type { FlowStep, InvestigationFlow, InvestigationStage, JourneyEvent, PipelineGraph, PipelineGraphNode, StageSummary } from '../api'
import { captureWord, flowStepOf, foldedAggregate, foldedStage, foldFlow, pathCard, questionCard, resultWords, runCard, statusWord, stepKind, stepName } from './flowWords'

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
    // The final result replaces a neutral removal badge; the removal stays in words.
    expect(runCard(SELECT, DEMO_FLOW.steps.select, DEMO_FLOW, DEMO_GRAPH, null)).toMatchObject({
      metric: '4 correct in',
      badge: { tone: 'positive', text: '4 of 6 in top 3' },
      note: 'Removed 1 · all still delivered',
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
    expect(pathCard(SELECT, [event('select', 'promoted', 5, 4)], fired(), 3, true, null, true)).toEqual({
      metric: '',
      badge: { tone: 'negative', text: 'Rank 4' },
      note: 'was 5 · fell below the top 3 · Not delivered',
      noteTone: 'negative',
      ghost: false,
    })
    expect(pathCard(SELECT, [event('select', 'retained', 2, 2)], fired(), 3, true, 2, false)).toMatchObject({ badge: { tone: 'accent', text: 'Rank 2' }, note: 'Delivered at #2', noteTone: 'positive' })
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
