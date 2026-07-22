import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test } from 'vitest'
import CandidateLineageDiff from './CandidateLineageDiff'
import { CandidateLineageDiffResponse } from '../api'

const blocked: CandidateLineageDiffResponse = {
  baseline_run_id: 'baseline',
  candidate_run_id: 'candidate',
  query_id: 'q-1',
  readiness: {
    scope: 'lineage_diff',
    status: 'BLOCK',
    findings: [{
      code: 'lineage_topology_unaligned', scope: 'lineage_diff', status: 'BLOCK',
      observed: 'different', required: 'aligned', detail: 'Stage semantics are not aligned.',
      next_action: 'Inspect both recorded paths side by side.',
    }],
  },
  diffs: [{
    status: 'BLOCK',
    reasons: ['Stage semantics are not aligned.'],
    baseline: { trace_id: 'base-trace', run_id: 'baseline', query_id: 'q-1', pipeline_id: 'pipeline', topology_hash: 'a', candidates: {}, edges: [] },
    candidate: { trace_id: 'candidate-trace', run_id: 'candidate', query_id: 'q-1', pipeline_id: 'pipeline', topology_hash: 'b', candidates: {}, edges: [] },
    changed: [],
  }],
}

describe('CandidateLineageDiff', () => {
  test('shows blocked alignment before side-by-side recorded paths', () => {
    const html = renderToStaticMarkup(<CandidateLineageDiff response={blocked} />)

    expect(html).toMatch(/Lineage diff[\s\S]*BLOCK/)
    expect(html).toContain('Stage semantics are not aligned.')
    expect(html).toContain('Baseline recorded path')
    expect(html).toContain('Candidate recorded path')
    expect(html).not.toMatch(/caused|cause of/i)
  })
})
