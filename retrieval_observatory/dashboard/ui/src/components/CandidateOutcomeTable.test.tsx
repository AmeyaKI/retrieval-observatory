import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'
import CandidateMissTable from './CandidateMissTable'
import { CandidateJourneyRow } from '../api'

const irrelevantRemovedRow: CandidateJourneyRow = {
  query_id: 'q-1',
  query_text: null,
  doc_id: 'doc-1',
  doc_preview: 'Removed distractor',
  pipeline_id: 'pipeline-1',
  trace_id: 'trace-1',
  relevant: false,
  grade: 0,
  survived: false,
  final_rank: null,
  introduced_at: 'retrieve',
  dropped_at: 'filter',
  drop_reason: 'below threshold',
  drop_reason_inferred: false,
  miss_type: null,
  outcome: 'irrelevant_removed',
  outcome_evidence: 'recorded',
  evidence_class: 'recorded',
}

describe('CandidateOutcomeTable', () => {
  test('never renders TN for an observed irrelevant removed candidate', () => {
    const html = renderToStaticMarkup(
      <CandidateMissTable rows={[irrelevantRemovedRow]} selectedDocId={null} onSelect={vi.fn()} />,
    )

    expect(html).toContain('Irrelevant removed')
    expect(html).not.toMatch(/>TN</)
  })
})
