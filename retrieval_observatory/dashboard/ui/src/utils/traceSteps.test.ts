import { describe, expect, it } from 'vitest'
import { buildReplaySteps, diffStep, droppedDocIds, stepOutputs } from './traceSteps'
import { TraceOperatorSpan } from '../api'

function span(overrides: Partial<TraceOperatorSpan> & { op_id: string }): TraceOperatorSpan {
  return {
    op_type: 'TRANSFORM',
    op_name: overrides.op_id,
    parent_ids: [],
    status: 'FIRED',
    deterministic: true,
    replay_policy: 'EXACT',
    latency_ms: 1,
    inputs: [],
    outputs: [],
    params: {},
    gate_values: {},
    input_variant: 'raw',
    error: null,
    ...overrides,
  }
}

describe('buildReplaySteps', () => {
  it('puts parallel fusion arms in the same step', () => {
    const spans = [
      span({ op_id: 'bm25', parent_ids: [] }),
      span({ op_id: 'dense', parent_ids: [] }),
      span({ op_id: 'rrf', parent_ids: ['bm25', 'dense'] }),
    ]
    const steps = buildReplaySteps(spans)
    expect(steps.length).toBe(2)
    expect(steps[0].spans.map((s) => s.op_id).sort()).toEqual(['bm25', 'dense'])
    expect(steps[1].spans.map((s) => s.op_id)).toEqual(['rrf'])
  })

  it('handles a plain linear chain', () => {
    const spans = [
      span({ op_id: 'a', parent_ids: [] }),
      span({ op_id: 'b', parent_ids: ['a'] }),
      span({ op_id: 'c', parent_ids: ['b'] }),
    ]
    const steps = buildReplaySteps(spans)
    expect(steps.map((s) => s.level)).toEqual([0, 1, 2])
  })
})

describe('diffStep / stepOutputs', () => {
  it('flags appeared, disappeared, and rank-changed candidates', () => {
    const prev = new Map([['a', 1], ['b', 2]])
    const curr = new Map([['a', 2], ['c', 1]])
    const diff = diffStep(prev, curr)
    const byId = Object.fromEntries(diff.map((d) => [d.doc_id, d.status]))
    expect(byId.a).toBe('rank_changed')
    expect(byId.b).toBe('disappeared')
    expect(byId.c).toBe('appeared')
  })

  it('stepOutputs unions FIRED spans only, skipping SKIPPED_BY_GATE', () => {
    const step = {
      level: 0,
      spans: [
        span({ op_id: 'x', status: 'FIRED', outputs: [{ doc_id: 'd1', score: 1, rank: 1, input_rank: null, output_rank: 1, origin_op_ids: [], score_components: {}, add_reason: 'retrieved', drop_reason: null }] }),
        span({ op_id: 'y', status: 'SKIPPED_BY_GATE', outputs: [{ doc_id: 'd2', score: 1, rank: 1, input_rank: null, output_rank: 1, origin_op_ids: [], score_components: {}, add_reason: 'retrieved', drop_reason: null }] }),
      ],
    }
    const out = stepOutputs(step)
    expect(out.has('d1')).toBe(true)
    expect(out.has('d2')).toBe(false)
  })
})

describe('droppedDocIds', () => {
  it('finds candidates present early but absent from the final step', () => {
    const spans = [
      span({
        op_id: 'source',
        parent_ids: [],
        outputs: [
          { doc_id: 'keep', score: 1, rank: 1, input_rank: null, output_rank: 1, origin_op_ids: [], score_components: {}, add_reason: 'retrieved', drop_reason: null },
          { doc_id: 'drop', score: 1, rank: 2, input_rank: null, output_rank: 2, origin_op_ids: [], score_components: {}, add_reason: 'retrieved', drop_reason: null },
        ],
      }),
      span({
        op_id: 'filter',
        parent_ids: ['source'],
        outputs: [
          { doc_id: 'keep', score: 1, rank: 1, input_rank: null, output_rank: 1, origin_op_ids: [], score_components: {}, add_reason: 'retrieved', drop_reason: null },
        ],
      }),
    ]
    expect(droppedDocIds(spans)).toEqual(['drop'])
  })
})
