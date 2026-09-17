import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'
// api.ts reads window.location.origin at import time; the node test environment has no window.
vi.hoisted(() => {
  ;(globalThis as { window?: unknown }).window = { location: { origin: 'http://localhost' } }
})
import { NodeInspector, servedNote } from './PipelineDagView'
import { PipelineGraphNode } from '../api'

function node(overrides: Partial<PipelineGraphNode>): PipelineGraphNode {
  return {
    node_id: 'bm25',
    label: 'Bm25',
    op_type: 'SOURCE',
    depth: 0,
    branch_id: 'bm25',
    candidate_count: 20,
    metrics: {
      'ndcg@10': { mean: 0.41, ci_low: 0.35, ci_high: 0.47, n: 12 },
      recall: { mean: 0.6, ci_low: 0.5, ci_high: 0.7, k: 10, n: 12 },
      latency_p50: null,
    },
    is_merge: false,
    source: 'measured',
    input_candidate_count: 0,
    observed_count: 40,
    trace_coverage: 1,
    fire_rate: 0.3,
    status_counts: { FIRED: 12, SKIPPED_BY_GATE: 28 },
    cache_hits: 0,
    latency: { count: 12, mean_ms: 3, p50_ms: 3, p95_ms: 4 },
    is_final_output: false,
    final_output_count: 0,
    configured: null,
    availability: {},
    ...overrides,
  }
}

describe('PipelineDagView served-count note', () => {
  test('a gate-skipped branch node states its denominator next to each value', () => {
    const html = renderToStaticMarkup(<NodeInspector node={node({})} traceCount={40} />)
    expect(html.match(/12 of 40 queries served/g)).toHaveLength(2)
  })

  test('a spine node served on every query shows no note', () => {
    const spine = node({
      branch_id: null,
      fire_rate: 1,
      metrics: { 'ndcg@10': { mean: 0.5, ci_low: 0.4, ci_high: 0.6, n: 40 }, recall: null, latency_p50: null },
    })
    const html = renderToStaticMarkup(<NodeInspector node={spine} traceCount={40} />)
    expect(html).not.toContain('queries served')
  })

  test('a gated spine node (fewer served than the run) still states its denominator', () => {
    const gated = node({
      branch_id: null,
      metrics: { 'ndcg@10': { mean: 0.5, ci_low: 0.4, ci_high: 0.6, n: 25 }, recall: null, latency_p50: null },
    })
    const html = renderToStaticMarkup(<NodeInspector node={gated} traceCount={40} />)
    expect(html).toContain('25 of 40 queries served')
  })

  test('servedNote falls back to the served count alone when the run total is unknown', () => {
    expect(servedNote({ mean: 0.6, ci_low: null, ci_high: null, n: 12 }, node({}))).toBe('on 12 served queries')
    expect(servedNote({ mean: 0.6, ci_low: null, ci_high: null }, node({}))).toBeNull()
  })
})
