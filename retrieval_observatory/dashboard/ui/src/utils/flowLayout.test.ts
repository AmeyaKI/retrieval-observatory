import { describe, expect, test } from 'vitest'
import type { PipelineGraph, PipelineGraphNode } from '../api'
import { CARD_MIN_W, FlowLayout, FlowNode, layoutFlow } from './flowLayout'

const emptyMetrics = { 'ndcg@10': null, recall: null, latency_p50: null }
const emptyLatency = { count: 0, mean_ms: null, p50_ms: null, p95_ms: null }

function node(node_id: string, op_type: string, depth: number, extra: Partial<PipelineGraphNode> = {}): PipelineGraphNode {
  return {
    node_id,
    label: node_id,
    op_type,
    depth,
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
    ...extra,
  }
}

function edge(source: string, target: string, kind: 'flow' | 'fan_in' = 'flow', conditional = false): PipelineGraph['edges'][number] {
  return { source, target, kind, observed_count: 3, trace_coverage: 1, conditional, source_evidence: 'measured' }
}

function graph(pipeline_id: string, nodes: PipelineGraphNode[], edges: PipelineGraph['edges']): PipelineGraph {
  return {
    pipeline_id,
    contract_version: 2,
    projection_mode: 'run_union',
    trace_count: 3,
    complete_trace_count: 3,
    status_counts: { OK: 3 },
    final_output_ids: [nodes[nodes.length - 1].node_id],
    timing_semantics: {},
    warnings: [],
    nodes,
    edges,
  }
}

// The golden-hybrid demo graph (same as InvestigationWorkspace.test.tsx); depth is deliberately not the column.
const DEMO = graph(
  'golden-hybrid',
  [
    node('dense', 'SOURCE', 0),
    node('lexical', 'SOURCE', 0),
    node('recency_filter', 'FILTER', 1),
    node('rerank@dense', 'RERANK', 1),
    node('rerank@lexical', 'RERANK', 2),
    node('fuse', 'FUSE', 3),
    node('expand_gate', 'GATE', 4),
    node('expand', 'EXPAND', 5, { fire_rate: 1 / 3, status_counts: { FIRED: 1, SKIPPED_BY_GATE: 2 } }),
    node('select', 'TRANSFORM', 6, { is_final_output: true }),
  ],
  [
    edge('dense', 'rerank@dense'),
    edge('lexical', 'recency_filter'),
    edge('recency_filter', 'rerank@lexical'),
    edge('rerank@dense', 'fuse', 'fan_in'),
    edge('rerank@lexical', 'fuse', 'fan_in'),
    edge('fuse', 'expand_gate'),
    edge('expand_gate', 'expand'),
    edge('expand', 'select', 'fan_in', true),
    edge('expand_gate', 'select', 'fan_in', true),
  ],
)

// The real 3-step run: two searches fused.
const REAL = graph(
  'rag_search-retrieval',
  [node('bm25', 'SOURCE', 0, { label: 'Search (bm25)' }), node('dense', 'SOURCE', 0, { label: 'Search (dense)' }), node('rrf', 'FUSE', 1, { label: 'Fuse Hits', is_final_output: true })],
  [edge('bm25', 'rrf', 'fan_in'), edge('dense', 'rrf', 'fan_in')],
)

// 15 steps: three source lanes of three steps each, one fuse, then five more steps.
const LONG = graph(
  'long',
  [
    ...['a', 'b', 'c'].flatMap((lane) => [node(`${lane}1`, 'SOURCE', 0), node(`${lane}2`, 'RERANK', 1), node(`${lane}3`, 'FILTER', 2)]),
    node('fuse', 'FUSE', 3),
    ...[1, 2, 3, 4, 5].map((i) => node(`s${i}`, 'TRANSFORM', 3 + i)),
  ],
  [
    ...['a', 'b', 'c'].flatMap((lane) => [edge(`${lane}1`, `${lane}2`), edge(`${lane}2`, `${lane}3`), edge(`${lane}3`, 'fuse', 'fan_in')]),
    edge('fuse', 's1'),
    ...[1, 2, 3, 4].map((i) => edge(`s${i}`, `s${i + 1}`)),
  ],
)

const columns = (layout: FlowLayout) => Object.fromEntries(layout.nodes.map((n) => [n.node_id, n.col]))
const centre = (n: FlowNode) => ({ x: n.x + n.w / 2, y: n.y + n.h / 2 })

function overlaps(a: FlowNode, b: FlowNode): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
}

/** Liang–Barsky: does the segment p→q cross the rectangle's interior? */
function segmentHitsRect(p: { x: number; y: number }, q: { x: number; y: number }, r: FlowNode): boolean {
  let t0 = 0
  let t1 = 1
  const dx = q.x - p.x
  const dy = q.y - p.y
  for (const [pk, qk] of [
    [-dx, p.x - r.x],
    [dx, r.x + r.w - p.x],
    [-dy, p.y - r.y],
    [dy, r.y + r.h - p.y],
  ]) {
    if (pk === 0) {
      if (qk <= 0) return false
      continue
    }
    const t = qk / pk
    if (pk < 0) t0 = Math.max(t0, t)
    else t1 = Math.min(t1, t)
    if (t0 >= t1) return false
  }
  return true
}

function expectClean(layout: FlowLayout) {
  const boxes: FlowNode[] = layout.result ? [...layout.nodes, { ...layout.nodes[0], ...layout.result, node_id: 'result' }] : layout.nodes
  for (const [i, a] of boxes.entries()) for (const b of boxes.slice(i + 1)) expect(overlaps(a, b), `${a.node_id} overlaps ${b.node_id}`).toBe(false)
  const at = new Map(boxes.map((n) => [n.node_id, n]))
  const edges = layout.result ? [...layout.edges, { ...layout.result.edge, target: 'result' }] : layout.edges
  for (const e of edges) {
    const s = at.get(e.source)!
    const t = at.get(e.target)!
    for (const other of boxes) {
      if (other === s || other === t) continue
      expect(segmentHitsRect(centre(s), centre(t), other), `${e.source}→${e.target} runs under ${other.node_id}`).toBe(false)
    }
  }
}

describe('layoutFlow', () => {
  test('places every step as late as possible before its earliest child', () => {
    expect(columns(layoutFlow(DEMO, { width: 1200 }))).toEqual({
      dense: 0,
      lexical: 0,
      recency_filter: 1,
      'rerank@dense': 2,
      'rerank@lexical': 2,
      fuse: 3,
      expand_gate: 4,
      expand: 5,
      select: 6,
    })
    expect(columns(layoutFlow(REAL, { width: 1200 }))).toEqual({ bm25: 0, dense: 0, rrf: 1 })
    const long = columns(layoutFlow(LONG, { width: 1200 }))
    expect([long.a1, long.b2, long.c3, long.fuse, long.s5]).toEqual([0, 1, 2, 3, 8])
  })

  test('parallel reranks share a column and the gated step moves onto the nearest lane off the gate-to-merge line', () => {
    const layout = layoutFlow(DEMO, { width: 1200 })
    const at = Object.fromEntries(layout.nodes.map((n) => [n.node_id, n]))
    expect(at['rerank@dense'].col).toBe(at['rerank@lexical'].col)
    expect(at['rerank@dense'].row).not.toBe(at['rerank@lexical'].row)
    // expand leaves the straight expand_gate → select line for the upper of the two nearest lanes (Dense).
    expect(Math.abs(at.expand.row - at.expand_gate.row)).toBeGreaterThanOrEqual(0.5)
    expect(at.expand.row).toBe(at.dense.row)
    expect(at.select.row).toBe(at.expand_gate.row)
    expect(Math.min(...layout.nodes.map((n) => n.row))).toBe(0)
    // So the demo keeps exactly its two lanes.
    expect(Math.max(...layout.nodes.map((n) => n.row)) + 1).toBe(2)
  })

  test('a step on an integer lane line moves a whole row beside it', () => {
    const g = graph('gap', [node('a', 'SOURCE', 0), node('b', 'RERANK', 1), node('c', 'FILTER', 2), node('m', 'TRANSFORM', 2)], [edge('a', 'b'), edge('b', 'c'), edge('a', 'm'), edge('c', 'm')])
    // a → m spans two columns on row 0; b would sit on it.
    const at = Object.fromEntries(layoutFlow(g, { width: 1200 }).nodes.map((n) => [n.node_id, n]))
    expect(Math.abs(at.b.row - at.a.row)).toBe(1)
  })

  test('no two cards overlap and no edge runs under a third card, in both orientations', () => {
    // The check can fail: a segment through a card hits it, one beside it does not.
    const card = { x: 10, y: 10, w: 20, h: 20 } as FlowNode
    expect(segmentHitsRect({ x: 0, y: 20 }, { x: 40, y: 20 }, card)).toBe(true)
    expect(segmentHitsRect({ x: 0, y: 40 }, { x: 40, y: 40 }, card)).toBe(false)
    for (const g of [DEMO, REAL, LONG]) {
      for (const orientation of ['horizontal', 'vertical'] as const) expectClean(layoutFlow(g, { width: 1200, orientation }))
      expectClean(layoutFlow(g, { width: 1600 }))
      expectClean(layoutFlow(g, { width: 330 }))
    }
  })

  test('the demo runs left to right at 1200 px (and on a 1280 px laptop) with every card inside the width', () => {
    expect(layoutFlow(DEMO, { width: 1100 }).orientation).toBe('horizontal')
    const layout = layoutFlow(DEMO, { width: 1200 })
    expect(layout.orientation).toBe('horizontal')
    expect(layout.overflowX).toBe(false)
    expect(layout.width).toBeLessThanOrEqual(1200)
    for (const n of layout.nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0)
      expect(n.x + n.w).toBeLessThanOrEqual(1200)
      expect(n.w).toBeGreaterThanOrEqual(CARD_MIN_W)
    }
  })

  test('narrow containers and long pipelines turn top to bottom', () => {
    expect(layoutFlow(DEMO, { width: 700 }).orientation).toBe('vertical')
    const long = layoutFlow(LONG, { width: 1200 })
    expect(long.orientation).toBe('vertical')
    expect(long.overflowX).toBe(false)
    const phone = layoutFlow(LONG, { width: 330 })
    expect(phone.orientation).toBe('vertical')
    expect(phone.overflowX).toBe(true)
    const real = layoutFlow(REAL, { width: 330 })
    expect(real.orientation).toBe('vertical')
    expect(real.overflowX).toBe(false)
    // Two lanes fit a phone: no sideways scroll for the demo either.
    const demo = layoutFlow(DEMO, { width: 330 })
    expect(demo.orientation).toBe('vertical')
    expect(demo.overflowX).toBe(false)
    expect(demo.width).toBeLessThanOrEqual(330)
  })

  test('the only final step gets a result card in its own last column when that column fits', () => {
    const real = layoutFlow(REAL, { width: 1200 })
    const rrf = real.nodes.find((n) => n.node_id === 'rrf')!
    expect(real.result).not.toBeNull()
    expect(real.result!.x).toBeGreaterThan(rrf.x + rrf.w)
    expect(real.result!.y).toBe(rrf.y)
    expect(real.result!.edge.source).toBe('rrf')
    expect(real.width).toBeLessThanOrEqual(1200)
    // Wide gaps leave room for an edge label between the cards.
    expect(real.result!.x - (rrf.x + rrf.w)).toBeGreaterThanOrEqual(100)
    // The demo's eighth column does not fit 1200 px; top to bottom never has one.
    expect(layoutFlow(DEMO, { width: 1200 }).result).toBeNull()
    expect(layoutFlow(DEMO, { width: 1300 }).result).not.toBeNull()
    expect(layoutFlow(REAL, { width: 330 }).result).toBeNull()
    const twoFinals = { ...REAL, nodes: REAL.nodes.map((n) => ({ ...n, is_final_output: true })) }
    expect(layoutFlow(twoFinals, { width: 1200 }).result).toBeNull()
  })

  test('the diagram never exceeds the width unless it says it overflows', () => {
    for (const g of [DEMO, REAL, LONG]) {
      for (const width of [300, 324, 330, 390, 700, 768, 1000, 1200, 1440]) {
        const layout = layoutFlow(g, { width })
        if (!layout.overflowX) expect(layout.width, `${g.pipeline_id} at ${width}`).toBeLessThanOrEqual(width)
        for (const n of layout.nodes) expect(n.w).toBeGreaterThanOrEqual(CARD_MIN_W)
      }
    }
  })

  test('edges attach right-middle to left-middle, spreading several edges over one side', () => {
    const layout = layoutFlow(REAL, { width: 1200 })
    const rrf = layout.nodes.find((n) => n.node_id === 'rrf')!
    const ends = layout.edges.map((e) => e.path.split(' ').slice(-2).map(Number))
    expect(ends.every(([x]) => x === rrf.x)).toBe(true)
    const ys = ends.map(([, y]) => y).sort((a, b) => a - b)
    expect(ys[0]).toBeGreaterThanOrEqual(rrf.y + rrf.h * 0.2)
    expect(ys[1]).toBeLessThanOrEqual(rrf.y + rrf.h * 0.8)
    expect(ys[0]).toBeLessThan(ys[1])
    // mid is the curve's t = 0.5 point: halfway between the two ends.
    for (const e of layout.edges) {
      const [x1, y1] = e.path.split(' ').slice(1, 3).map(Number)
      const [x2, y2] = e.path.split(' ').slice(-2).map(Number)
      expect(e.mid).toEqual({ x: (x1 + x2) / 2, y: (y1 + y2) / 2 })
    }
    const vertical = layoutFlow(REAL, { width: 330 })
    const vrrf = vertical.nodes.find((n) => n.node_id === 'rrf')!
    for (const e of vertical.edges) expect(Number(e.path.split(' ').slice(-1)[0])).toBe(vrrf.y)
  })

  test('is a pure function of its input', () => {
    expect(layoutFlow(DEMO, { width: 1200 })).toEqual(layoutFlow(DEMO, { width: 1200 }))
  })
})
