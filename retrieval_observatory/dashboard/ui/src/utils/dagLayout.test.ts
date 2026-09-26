import { describe, expect, it } from 'vitest'
import { collapseInvocations, collapsedNodeId, layoutPipelineGraph, NODE_W, NODE_H, COL_GAP, PAD, nodeCardHeight, repeatedInvocationCount } from './dagLayout'
import type { PipelineGraph } from '../api'

const emptyMetrics = { 'ndcg@10': null, recall: null, latency_p50: null }
const emptyLatency = { count: 0, mean_ms: null, p50_ms: null, p95_ms: null }
const nodeEvidence = { topology: 'measured' as const, metrics: 'unavailable' as const }

const FIXTURE: PipelineGraph = {
  pipeline_id: 'hybrid',
  contract_version: 2,
  projection_mode: 'run_union',
  trace_count: 1,
  complete_trace_count: 1,
  status_counts: { OK: 1 },
  final_output_ids: ['rerank'],
  timing_semantics: { total_latency_ms: 'wall_clock_ms' },
  warnings: [],
  nodes: [
    { node_id: 'bm25', label: 'BM25', op_type: 'SOURCE', depth: 0, branch_id: null, is_merge: false, metrics: emptyMetrics, candidate_count: 20, source: 'measured', input_candidate_count: 0, observed_count: 1, trace_coverage: 1, fire_rate: 1, status_counts: { FIRED: 1 }, cache_hits: 0, latency: emptyLatency, is_final_output: false, final_output_count: 0, configured: null, availability: nodeEvidence },
    { node_id: 'dense', label: 'Dense', op_type: 'SOURCE', depth: 0, branch_id: null, is_merge: false, metrics: emptyMetrics, candidate_count: 20, source: 'measured', input_candidate_count: 0, observed_count: 1, trace_coverage: 1, fire_rate: 1, status_counts: { FIRED: 1 }, cache_hits: 0, latency: emptyLatency, is_final_output: false, final_output_count: 0, configured: null, availability: nodeEvidence },
    { node_id: 'fuse', label: 'RRF', op_type: 'FUSE', depth: 1, branch_id: null, is_merge: true, metrics: emptyMetrics, candidate_count: 20, source: 'measured', input_candidate_count: 40, observed_count: 1, trace_coverage: 1, fire_rate: 1, status_counts: { FIRED: 1 }, cache_hits: 0, latency: emptyLatency, is_final_output: false, final_output_count: 0, configured: null, availability: nodeEvidence },
    { node_id: 'rerank', label: 'Rerank', op_type: 'RERANK', depth: 2, branch_id: null, is_merge: false, metrics: emptyMetrics, candidate_count: 10, source: 'measured', input_candidate_count: 20, observed_count: 1, trace_coverage: 1, fire_rate: 1, status_counts: { FIRED: 1 }, cache_hits: 0, latency: emptyLatency, is_final_output: true, final_output_count: 1, configured: null, availability: nodeEvidence },
  ],
  edges: [
    { source: 'bm25', target: 'fuse', kind: 'fan_in', observed_count: 1, trace_coverage: 1, conditional: false, source_evidence: 'measured' },
    { source: 'dense', target: 'fuse', kind: 'fan_in', observed_count: 1, trace_coverage: 1, conditional: false, source_evidence: 'measured' },
    { source: 'fuse', target: 'rerank', kind: 'flow', observed_count: 1, trace_coverage: 1, conditional: false, source_evidence: 'measured' },
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
    expect(byId.bm25.h).toBeGreaterThanOrEqual(NODE_H)
  })

  it('uses the caller card height for every node and anchors edges at its middle', () => {
    const layout = layoutPipelineGraph(FIXTURE, () => 131)
    expect(layout.nodes.every((n) => n.h === 131)).toBe(true)
    const byId = Object.fromEntries(layout.nodes.map((n) => [n.node_id, n]))
    const toRerank = layout.edges.find((e) => e.source === 'fuse')!
    expect(toRerank.path.startsWith(`M ${byId.fuse.x + NODE_W} ${byId.fuse.y + 131 / 2}`)).toBe(true)
    // The default (metric cards) is unchanged.
    expect(layoutPipelineGraph(FIXTURE).nodes.map((n) => n.h)).toEqual(FIXTURE.nodes.map(() => NODE_H))
  })

  it('grows node height when metrics are present', () => {
    const withMetrics: PipelineGraph = {
      ...FIXTURE,
      nodes: FIXTURE.nodes.map((n) =>
        n.node_id === 'rerank'
          ? {
              ...n,
              metrics: {
                'ndcg@10': { mean: 0.5, ci_low: 0.4, ci_high: 0.6, k: 10 },
                recall: { mean: 0.7, ci_low: 0.6, ci_high: 0.8, k: 10 },
                latency_p50: { mean: 12, ci_low: null, ci_high: null, k: null },
              },
            }
          : n,
      ),
    }
    const layout = layoutPipelineGraph(withMetrics)
    const byId = Object.fromEntries(layout.nodes.map((n) => [n.node_id, n]))
    expect(byId.rerank.h).toBeGreaterThan(byId.bm25.h)
    expect(byId.rerank.h).toBeGreaterThanOrEqual(nodeCardHeight(withMetrics.nodes.find((n) => n.node_id === 'rerank')!))
  })

  it('is deterministic pure function of graph input', () => {
    const a = layoutPipelineGraph(FIXTURE)
    const b = layoutPipelineGraph(FIXTURE)
    expect(a.nodes.map((n) => [n.node_id, n.x, n.y, n.h])).toEqual(b.nodes.map((n) => [n.node_id, n.x, n.y, n.h]))
    expect(a.width).toBe(PAD * 2 + 3 * NODE_W + 2 * COL_GAP)
  })
})

describe('collapseInvocations', () => {
  const node = (node_id: string, depth: number, extra: Partial<PipelineGraph['nodes'][number]> = {}) => ({ ...FIXTURE.nodes[0], node_id, label: node_id, depth, ...extra })
  const edge = (source: string, target: string, kind: 'flow' | 'fan_in' = 'flow') => ({ ...FIXTURE.edges[0], source, target, kind })
  const REPEATED: PipelineGraph = {
    ...FIXTURE,
    final_output_ids: ['fuse'],
    nodes: [
      node('source', 0, { op_type: 'SOURCE' }),
      node('rerank', 1, { op_type: 'RERANK', observed_count: 3, candidate_count: 10, trace_coverage: 1, status_counts: { FIRED: 3 } }),
      node('rerank#2', 2, { op_type: 'RERANK', observed_count: 2, candidate_count: 4, trace_coverage: 0.5, status_counts: { FIRED: 1, SKIPPED_BY_GATE: 1 } }),
      node('fuse', 3, { op_type: 'FUSE', is_merge: true }),
    ],
    edges: [edge('source', 'rerank'), edge('rerank', 'rerank#2'), edge('rerank', 'fuse', 'fan_in'), edge('rerank#2', 'fuse', 'fan_in')],
  }

  it('maps a repeat suffix to the stable operator id', () => {
    expect(collapsedNodeId('rerank#2')).toBe('rerank')
    expect(collapsedNodeId('rerank@dense')).toBe('rerank@dense')
    expect(repeatedInvocationCount(REPEATED)).toBe(1)
    expect(repeatedInvocationCount(FIXTURE)).toBe(0)
  })

  it('folds rerank#2 into rerank, summing counts and de-duplicating remapped edges', () => {
    const collapsed = collapseInvocations(REPEATED)
    expect(collapsed.nodes.map((n) => n.node_id)).toEqual(['source', 'rerank', 'fuse'])
    const rerank = collapsed.nodes.find((n) => n.node_id === 'rerank')!
    expect(rerank.label).toBe('rerank')
    expect(rerank.depth).toBe(1)
    expect(rerank.observed_count).toBe(5)
    expect(rerank.candidate_count).toBe(14)
    expect(rerank.trace_coverage).toBe(1)
    expect(rerank.status_counts).toEqual({ FIRED: 4, SKIPPED_BY_GATE: 1 })
    expect(collapsed.edges.map((e) => [e.source, e.target])).toEqual([
      ['source', 'rerank'],
      ['rerank', 'fuse'],
    ])
    expect(collapsed.final_output_ids).toEqual(['fuse'])
    expect(REPEATED.nodes).toHaveLength(4)
  })

  it('returns a graph without repeats unchanged and lays it out identically', () => {
    const collapsed = collapseInvocations(FIXTURE)
    expect(collapsed).toEqual(FIXTURE)
    expect(layoutPipelineGraph(collapsed)).toEqual(layoutPipelineGraph(FIXTURE))
  })

  it('lays the collapsed graph out deterministically', () => {
    const a = layoutPipelineGraph(collapseInvocations(REPEATED))
    const b = layoutPipelineGraph(collapseInvocations(REPEATED))
    expect(a).toEqual(b)
    expect(a.nodes.map((n) => n.node_id)).toEqual(['source', 'rerank', 'fuse'])
    expect(a.edges).toHaveLength(2)
  })
})
