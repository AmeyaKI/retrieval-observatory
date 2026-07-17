import { describe, expect, it } from 'vitest'
import { confusionLabel, countConfusion } from './confusion'
import type { CandidateJourneyRow } from '../api'

function row(partial: Partial<CandidateJourneyRow> & Pick<CandidateJourneyRow, 'doc_id' | 'relevant' | 'survived'>): CandidateJourneyRow {
  return {
    query_id: 'q0',
    query_text: 'q',
    doc_preview: 'preview',
    pipeline_id: 'p',
    trace_id: 't',
    grade: null,
    final_rank: null,
    introduced_at: 'bm25',
    dropped_at: null,
    drop_reason: null,
    drop_reason_inferred: false,
    miss_type: null,
    evidence_class: 'measured',
    ...partial,
  }
}

describe('confusionLabel', () => {
  it('labels the seen-candidate universe', () => {
    expect(confusionLabel(row({ doc_id: 'a', relevant: true, survived: true }))).toBe('TP')
    expect(confusionLabel(row({ doc_id: 'b', relevant: false, survived: true }))).toBe('FP')
    expect(confusionLabel(row({ doc_id: 'c', relevant: true, survived: false }))).toBe('FN')
    expect(confusionLabel(row({ doc_id: 'd', relevant: false, survived: false }))).toBe('TN')
  })

  it('counts buckets', () => {
    const counts = countConfusion([
      row({ doc_id: 'a', relevant: true, survived: true }),
      row({ doc_id: 'b', relevant: false, survived: true }),
      row({ doc_id: 'c', relevant: true, survived: false }),
      row({ doc_id: 'd', relevant: false, survived: false }),
      row({ doc_id: 'e', relevant: true, survived: false }),
    ])
    expect(counts).toEqual({ TP: 1, FP: 1, FN: 2, TN: 1 })
  })
})
