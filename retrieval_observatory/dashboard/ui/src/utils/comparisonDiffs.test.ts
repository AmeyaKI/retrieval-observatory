import { describe, expect, it } from 'vitest'
import { diffAttribution, diffRecommendations } from './comparisonDiffs'
import { OperatorAttributionRow, Recommendation } from '../api'

function attrRow(overrides: Partial<OperatorAttributionRow> & { op_id: string }): OperatorAttributionRow {
  return {
    segment: 'all',
    metric: 'recall',
    k: 10,
    delta: 0,
    ci_low: null,
    ci_high: null,
    n_pairs: 10,
    replay_policy: 'EXACT',
    result_status: 'replayed',
    evidence_class: 'replayed',
    unsupported_descendants: [],
    significant: false,
    ...overrides,
  }
}

describe('diffAttribution', () => {
  it('flags a sign flip', () => {
    const a = [attrRow({ op_id: 'rerank', delta: 0.05 })]
    const b = [attrRow({ op_id: 'rerank', delta: -0.03 })]
    const flips = diffAttribution(a, b)
    expect(flips).toHaveLength(1)
    expect(flips[0].reason).toBe('direction_flipped')
  })

  it('flags a significance change with no sign flip', () => {
    const a = [attrRow({ op_id: 'boost', delta: 0.02, significant: true })]
    const b = [attrRow({ op_id: 'boost', delta: 0.01, significant: false })]
    const flips = diffAttribution(a, b)
    expect(flips).toHaveLength(1)
    expect(flips[0].reason).toBe('significance_changed')
  })

  it('ignores operators only present in one run', () => {
    const a = [attrRow({ op_id: 'only_a', delta: 0.1 })]
    const b = [attrRow({ op_id: 'only_b', delta: -0.1 })]
    expect(diffAttribution(a, b)).toHaveLength(0)
  })

  it('picks the row with the most paired queries when an op has multiple segments', () => {
    const a = [
      attrRow({ op_id: 'gate', segment: 'hard', delta: 0.5, n_pairs: 2 }),
      attrRow({ op_id: 'gate', segment: 'all', delta: 0.05, n_pairs: 50 }),
    ]
    const b = [attrRow({ op_id: 'gate', segment: 'all', delta: -0.02, n_pairs: 50 })]
    const flips = diffAttribution(a, b)
    expect(flips).toHaveLength(1)
    expect(flips[0].a.n_pairs).toBe(50)
  })

  it('no flips when both runs agree', () => {
    const a = [attrRow({ op_id: 'x', delta: 0.1, significant: true })]
    const b = [attrRow({ op_id: 'x', delta: 0.2, significant: true })]
    expect(diffAttribution(a, b)).toHaveLength(0)
  })
})

function rec(action: string): Recommendation {
  return { action, rationale: '', evidence: [], priority: 1 }
}

describe('diffRecommendations', () => {
  it('splits into new, resolved, and persisting', () => {
    const a = [rec('swap reranker'), rec('add filter')]
    const b = [rec('add filter'), rec('tune fusion')]
    const diff = diffRecommendations(a, b)
    expect(diff.newRecs.map((r) => r.action)).toEqual(['swap reranker'])
    expect(diff.resolvedRecs.map((r) => r.action)).toEqual(['tune fusion'])
    expect(diff.persisting.map((r) => r.action)).toEqual(['add filter'])
  })

  it('handles two empty lists', () => {
    const diff = diffRecommendations([], [])
    expect(diff.newRecs).toHaveLength(0)
    expect(diff.resolvedRecs).toHaveLength(0)
    expect(diff.persisting).toHaveLength(0)
  })
})
