import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'
import CandidateLineageGraph from './CandidateLineageGraph'
import { CandidateLineageNode } from '../api'

function node(nodeId: string, candidateId: string, branch: string | null): CandidateLineageNode {
  return {
    node_id: nodeId,
    trace_id: 'trace-1',
    pipeline_id: 'pipeline-1',
    candidate_id: candidateId,
    logical_chunk_id: candidateId,
    source: { document_id: candidateId, document_revision: null, content_hash: null, char_start: null, char_end: null, preview: null },
    parent_candidate_ids: [],
    routes: [{
      candidate_ids: [candidateId],
      operator_ids: ['retrieve', branch ? `rerank-${branch}` : 'fuse'],
      branch_ids: branch ? [branch] : [],
      stages: [
        { op_id: 'retrieve', op_type: 'RETRIEVE', branch_id: null, rank: 1, score: 0.8, score_components: {} },
        { op_id: `rerank-${branch}`, op_type: 'RERANK', branch_id: branch, rank: 1, score: 0.9, score_components: {} },
        { op_id: 'fuse', op_type: 'FUSE', branch_id: null, rank: 1, score: 0.9, score_components: {} },
      ],
      lineage_evidence: 'recorded',
    }],
    relevance: { kind: 'unknown', grade: null, evidence: 'unavailable' },
    outcome: { kind: 'unknown_relevance', evidence: 'recorded', operator_id: null, branch_id: branch, reason: null },
    lineage_evidence: 'recorded',
    final_context_member: true,
    removed_at: null,
    removal_branch_id: null,
    removal_reason: null,
    removal_evidence: 'unavailable',
    derived_child_ids: [],
  }
}

describe('CandidateLineageGraph', () => {
  test('renders branch-aware static paths with a keyboard-selectable textual alternative', () => {
    const nodes = [node('trace-1:a', 'a', 'lexical'), node('trace-1:b', 'b', 'dense')]
    const html = renderToStaticMarkup(
      <CandidateLineageGraph nodes={nodes} edges={[]} selectedNodeId={null} onSelect={vi.fn()} />,
    )

    expect(html).toContain('<svg')
    expect(html).toContain('Recorded candidate routes')
    expect(html).toContain('lexical')
    expect(html).toContain('dense')
    expect(html).toContain('<button')
    expect(html).toContain('Filter by branch')
    expect(html).toContain('Showing 2 of 2 candidates')
  })
})
