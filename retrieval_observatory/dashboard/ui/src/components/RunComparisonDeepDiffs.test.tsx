import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'

// api.ts reads window.location.origin at import time; the node test environment has no window.
vi.hoisted(() => {
  ;(globalThis as { window?: unknown }).window = { location: { origin: 'http://localhost' } }
})

import RunComparisonDeepDiffs, { queryDeltaClass, queryDiffRoute } from './RunComparisonDeepDiffs'
import { QueryDiffs } from '../api'

const baseline = { dbId: 'demo', runId: 'base' }
const candidate = { dbId: 'demo', runId: 'cand' }

const queryDiffs: QueryDiffs = {
  metric: 'bm25|stage0|ndcg@10',
  run_a: 'base',
  run_b: 'cand',
  orientation: {
    a: 'baseline',
    b: 'candidate',
    effect: 'candidate_minus_baseline',
    baseline: { db_id: 'demo', run_id: 'base' },
    candidate: { db_id: 'demo', run_id: 'cand' },
  },
  rows: [
    { query_id: 'q-better', a: 0.2, b: 0.6, delta: 0.4 },
    { query_id: 'q-worse', a: 0.7, b: 0.1, delta: -0.6 },
  ],
}

describe('query-level winners & losers orientation', () => {
  test('green means the candidate scored higher, red means it regressed', () => {
    expect(queryDeltaClass(0.4)).toBe('text-emerald-700')
    expect(queryDeltaClass(-0.6)).toBe('text-red-600')
    expect(queryDeltaClass(0)).toBe('text-ink-faint')
  })

  test('diff link opens the candidate run against the baseline run', () => {
    expect(queryDiffRoute('q-1', baseline, candidate)).toBe('#/runs/cand/queries/q-1/diff?against=base')
    expect(queryDiffRoute('q-1', { dbId: 'other', runId: 'base' }, candidate)).toBe(
      '#/runs/cand/queries/q-1/diff?against=base&against_db=other',
    )
  })

  test('renders rows with the candidate-minus-baseline labelling', () => {
    const html = renderToStaticMarkup(
      <RunComparisonDeepDiffs selections={[baseline, candidate]} queryDiffs={queryDiffs} />,
    )
    expect(html).toContain('candidate (B) minus baseline (A)')
    expect(html).toContain('+0.400')
    expect(html).toContain('-0.600')
    expect(html).toContain('#/runs/cand/queries/q-worse/diff?against=base')
  })
})
