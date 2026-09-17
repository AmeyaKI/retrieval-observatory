import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'
// api.ts reads window.location.origin at import time; the node test environment has no window.
vi.hoisted(() => {
  ;(globalThis as { window?: unknown }).window = { location: { origin: 'http://localhost' } }
})
import { CellContent } from './SegmentOperatorGrid'
import { OperatorAttributionRow } from '../api'

const indeterminate: OperatorAttributionRow = {
  op_id: 'rerank',
  pipeline_id: 'hybrid',
  segment: 'all',
  metric: 'recall',
  k: 10,
  delta: null,
  ci_low: null,
  ci_high: null,
  n_pairs: 0,
  replay_policy: 'OBSERVED_ABLATION',
  result_status: 'indeterminate',
  evidence_class: 'unavailable',
  reason: 'Child fuse would decide on documents it never observed.',
  unsupported_descendants: ['fuse'],
}

describe('SegmentOperatorGrid CellContent', () => {
  test('an indeterminate cell shows the reason as visible text with the full text on hover', () => {
    const html = renderToStaticMarkup(<CellContent row={indeterminate} />)
    expect(html).toContain('>?<')
    expect(html).toContain('title="Child fuse would decide on documents it never observed."')
    expect(html).toContain('>Child fuse would decide on documents it never observed.<')
  })

  test('a not_applicable cell shows its reason beneath the dash', () => {
    const row = { ...indeterminate, result_status: 'not_applicable', reason: 'No fired operator trace had usable relevance judgments.' }
    const html = renderToStaticMarkup(<CellContent row={row} />)
    expect(html).toContain('>—<')
    expect(html).toContain('>No fired operator trace had usable relevance judgments.<')
  })

  test('a replayed cell keeps its delta and replay tier badge and shows no reason', () => {
    const row = { ...indeterminate, result_status: 'replayed', delta: 0.0123, reason: null }
    const html = renderToStaticMarkup(<CellContent row={row} />)
    expect(html).toContain('+0.0123')
    expect(html).toContain('title="OBSERVED_ABLATION"')
    expect(html).not.toContain('text-amber-700')
  })
})
