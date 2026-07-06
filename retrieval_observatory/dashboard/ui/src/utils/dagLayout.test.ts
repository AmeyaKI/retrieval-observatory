import { describe, expect, it } from 'vitest'
import { layoutPipelineGraph, NODE_W, COL_GAP, PAD } from './dagLayout'
import type { PipelineGraph } from '../api'

const emptyMetrics = { 'ndcg@10': null, recall: null, latency_p50: null }

const FIXTURE: PipelineGraph = {
  pipeline_id: 'hybrid',
  nodes: [
    { node_id: 'bm25', label: 'BM25', op_type: 'SOURCE', depth: 0, branch_id: null, is_merge: false, metrics: emptyMetrics, candidate_count: 20, source: 'measured' },
    { node_id: 'dense', label: 'Dense', op_type: 'SOURCE', depth: 0, branch_id: null, is_merge: false, metrics: emptyMetrics, candidate_count: 20, source: 'measured' },
    { node_id: 'fuse', label: 'RRF', op_type: 'FUSE', depth: 1, branch_id: null, is_merge: true, metrics: emptyMetrics, candidate_count: 20, source: 'measured' },
    { node_id: 'rerank', label: 'Rerank', op_type: 'RERANK', depth: 2, branch_id: null, is_merge: false, metrics: emptyMetrics, candidate_count: 10, source: 'measured' },
  ],
  edges: [
    { source: 'bm25', target: 'fuse', kind: 'fan_in' },
    { source: 'dense', target: 'fuse', kind: 'fan_in' },
    { source: 'fuse', target: 'rerank', kind: 'flow' },
  ],
}

describe('layoutPipelineGraph', () => {
  it('places four nodes and three edges for hybrid fan-in fixture', () => {
    const layout = layoutPipelineGraph(FIXTURE)
    expect(layout.nodes).toHaveLength(4)
    expect(layout.edges).toHaveLength(3)
    const byId = Object.fromEntries(layout.nodes.map((n) => [n.node_id, n]))
    expect(byId.fuse.x).toBeGreaterThan(byId.bm25.x)
    expect(byId.rerank.x).toBeGreaterThan(byId.fuse.x)
    expect(byId.fuse.is_merge).toBe(true)
  })

  it('is deterministic pure function of graph input', () => {
    const a = layoutPipelineGraph(FIXTURE)
    const b = layoutPipelineGraph(FIXTURE)
    expect(a.nodes.map((n) => [n.node_id, n.x, n.y])).toEqual(b.nodes.map((n) => [n.node_id, n.x, n.y]))
    expect(a.width).toBe(PAD * 2 + 3 * NODE_W + 2 * COL_GAP)
  })
})
