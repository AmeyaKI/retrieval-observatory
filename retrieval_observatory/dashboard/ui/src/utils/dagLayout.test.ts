import { describe, expect, it } from 'vitest'
import { layoutPipelineGraph, NODE_W, NODE_H, COL_GAP, PAD, nodeCardHeight } from './dagLayout'
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
