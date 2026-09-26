import { describe, expect, it } from 'vitest'
import {
  ALIGNMENT_LABELS,
  alignmentLabel,
  CHANGE_LABELS,
  CHANGE_PRIORITY,
  changeGlyph,
  changeLabel,
  diffTotals,
  sideSummary,
  sortDiffRows,
} from './comparisonDiffs'
import { JourneyAlignment, JourneyChangeKind, JourneyDiffRow, JourneySide } from '../api'

const KINDS = Object.keys(CHANGE_PRIORITY) as JourneyChangeKind[]
const ALIGNMENTS = Object.keys(ALIGNMENT_LABELS) as JourneyAlignment[]

function side(overrides: Partial<JourneySide> = {}): JourneySide {
  return {
    trace_id: 't1',
    outcome: 'relevant_delivered',
    final_membership: 'included',
    in_final_output: true,
    final_rank: 2,
    loss_boundary: null,
    capture_state: 'complete',
    judgment: 'relevant',
    grade: 1,
    events_summary: [],
    investigation_link: '#/investigate?run=cand',
    ...overrides,
  }
}

function row(change: JourneyChangeKind, overrides: Partial<JourneyDiffRow> = {}): JourneyDiffRow {
  return {
    query_id: 'q1',
    namespace: 'kb',
    entity_id: 'doc-1',
    unit: 'document',
    alignment: 'aligned',
    change,
    detail: '',
    baseline: side(),
    candidate: side(),
    capture_limited: false,
    priority: CHANGE_PRIORITY[change],
    ...overrides,
  }
}

describe('change and alignment vocabulary', () => {
  it('every change kind has a glyph and a text label (never colour alone)', () => {
    for (const kind of KINDS) {
      expect(CHANGE_LABELS[kind].glyph.length).toBeGreaterThan(0)
      expect(CHANGE_LABELS[kind].label.length).toBeGreaterThan(0)
      expect(changeGlyph(kind)).toBe(CHANGE_LABELS[kind].glyph)
      expect(changeLabel(kind)).toBe(CHANGE_LABELS[kind].label)
    }
    expect(changeLabel('novel_kind')).toBe('novel_kind')
    expect(changeGlyph('novel_kind')).toBe('?')
  })

  it('every alignment has a label', () => {
    for (const alignment of ALIGNMENTS) {
      expect(ALIGNMENT_LABELS[alignment].length).toBeGreaterThan(0)
      expect(alignmentLabel(alignment)).toBe(ALIGNMENT_LABELS[alignment])
    }
    expect(alignmentLabel('novel')).toBe('novel')
  })
})

describe('sortDiffRows', () => {
  it('puts lost first and unchanged last, breaking ties by query then entity', () => {
    const rows = [
      row('unchanged', { query_id: 'q1', entity_id: 'a' }),
      row('lost', { query_id: 'q2', entity_id: 'b' }),
      row('lost', { query_id: 'q2', entity_id: 'a' }),
      row('gained', { query_id: 'q9', entity_id: 'a' }),
      row('lost', { query_id: 'q1', entity_id: 'z' }),
    ]
    const sorted = sortDiffRows(rows)
    expect(sorted.map((r) => `${r.change}:${r.query_id}:${r.entity_id}`)).toEqual([
      'lost:q1:z',
      'lost:q2:a',
      'lost:q2:b',
      'gained:q9:a',
      'unchanged:q1:a',
    ])
    expect(sorted).not.toBe(rows)
    expect(rows[0].change).toBe('unchanged')
  })
})

describe('diffTotals', () => {
  it('counts pairs by kind and the evidence-limited rows, with every kind present', () => {
    const totals = diffTotals([row('lost'), row('lost', { capture_limited: true }), row('gained'), row('path_changed', { capture_limited: true })])
    expect(totals.pairs).toBe(4)
    expect(totals.captureLimited).toBe(2)
    expect(totals.byChange).toEqual({ lost: 2, gained: 1, membership_changed: 0, rank_changed: 0, path_changed: 1, unaligned: 0, unchanged: 0 })
    expect(diffTotals([]).byChange.lost).toBe(0)
  })
})

describe('sideSummary', () => {
  it('reads membership, rank, loss boundary and judgment in words', () => {
    expect(sideSummary(side())).toBe('included #2 · relevant')
    expect(sideSummary(side({ final_membership: 'excluded', final_rank: null, loss_boundary: 'select', judgment: 'unjudged' }))).toBe(
      'excluded at select · unjudged',
    )
    expect(sideSummary(side({ final_membership: 'excluded', final_rank: null, loss_boundary: 'not_observed' }))).toBe('excluded at not_observed · relevant')
    expect(sideSummary(side({ final_membership: 'unknown', final_rank: null }))).toBe('membership unknown · relevant')
    expect(sideSummary(null)).toBe('no row')
  })
})
