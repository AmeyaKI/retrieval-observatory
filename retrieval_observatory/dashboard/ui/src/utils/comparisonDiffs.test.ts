import { describe, expect, it } from 'vitest'
import {
  ALIGNMENT_LABELS,
  alignmentLabel,
  CHANGE_LABELS,
  CHANGE_PRIORITY,
  changeWords,
  compareHeadline,
  diffTotals,
  isCorrect,
  sideWords,
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
  it('every change kind reads in plain words with a tone (never colour alone)', () => {
    for (const kind of KINDS) {
      expect(CHANGE_LABELS[kind].label.length).toBeGreaterThan(0)
      expect(changeWords(kind)).toBe(CHANGE_LABELS[kind])
    }
    expect(KINDS.map((kind) => changeWords(kind).label)).toEqual(['Lost', 'Gained', 'In or out changed', 'Moved', 'Different path', "Can't be compared", 'Unchanged'])
    expect(KINDS.filter((kind) => changeWords(kind).tone !== 'neutral').map((kind) => [kind, changeWords(kind).tone])).toEqual([
      ['lost', 'negative'],
      ['gained', 'positive'],
    ])
    expect(changeWords('novel_kind')).toEqual({ label: 'novel_kind', tone: 'neutral' })
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

describe('sideWords', () => {
  const names: Record<string, string> = { recency_filter: 'Recency Filter', select: 'Select' }
  const nameOf = (opId: string) => names[opId] ?? opId

  it('reads a correct document by its outcome', () => {
    expect(sideWords(side(), 3, nameOf)).toBe('Delivered at #2')
    expect(sideWords(side({ final_rank: null }), 3, nameOf)).toBe('Delivered')
    expect(sideWords(side({ outcome: 'retained_below_cutoff', final_membership: 'excluded', final_rank: 7, loss_boundary: 'select' }), 3, nameOf)).toBe('Ranked too low · #7')
    expect(sideWords(side({ outcome: 'relevant_excluded', final_membership: 'excluded', final_rank: null, loss_boundary: 'recency_filter' }), 3, nameOf)).toBe(
      'Dropped by Recency Filter',
    )
    expect(sideWords(side({ outcome: 'not_observed', final_membership: 'excluded', final_rank: null, loss_boundary: 'not_observed' }), 3, nameOf)).toBe('Never found')
    expect(sideWords(side({ outcome: 'insufficient_evidence', final_membership: 'unknown', final_rank: null }), 3, nameOf)).toBe('Not enough evidence')
    expect(sideWords(null, 3, nameOf)).toBe('No row in this run')
  })

  it('names no step a partly recorded side was dropped by, and falls back to the id without names', () => {
    const dropped = side({ outcome: 'relevant_excluded', final_membership: 'excluded', final_rank: null, loss_boundary: 'recency_filter' })
    expect(sideWords({ ...dropped, capture_state: 'partial' }, 3, nameOf)).toBe('Not delivered')
    expect(sideWords({ ...dropped, loss_boundary: null }, 3, nameOf)).toBe('Not delivered')
    expect(sideWords(dropped, 3)).toBe('Dropped by recency_filter')
  })

  it('reads other rows by membership; judgment changes no words', () => {
    const other = { outcome: 'judged_nonrelevant' as const, judgment: 'nonrelevant' as const }
    expect(sideWords(side({ ...other, final_rank: 1 }), 3, nameOf)).toBe('In the top 3 at #1')
    expect(sideWords(side({ outcome: 'unjudged', judgment: 'unjudged', final_rank: 3 }), 3, nameOf)).toBe('In the top 3 at #3')
    expect(sideWords(side({ ...other, final_membership: 'excluded', final_rank: 4, loss_boundary: 'select' }), 3, nameOf)).toBe('Not in the top 3')
    expect(sideWords(side({ ...other, final_rank: 1 }), null, nameOf)).toBe('Delivered at #1')
    expect(sideWords(side({ ...other, final_membership: 'excluded', final_rank: null }), null, nameOf)).toBe('Not delivered')
    expect(sideWords(side({ ...other, final_membership: 'unknown', final_rank: null }), 3, nameOf)).toBe('Not enough evidence')
  })
})

describe('compareHeadline', () => {
  const unjudged = side({ outcome: 'unjudged', judgment: 'unjudged' })
  const notCorrect = { baseline: unjudged, candidate: unjudged }

  it('counts only correct documents: gained only', () => {
    const rows = [row('gained'), row('lost', notCorrect), row('rank_changed', notCorrect), row('unchanged')]
    expect(compareHeadline(rows, 4, 'base')).toBe('Against baseline base: 1 correct document gained, none lost.')
  })

  it('lost and gained, lost only', () => {
    expect(compareHeadline([row('gained'), row('gained'), row('lost')], 3, 'base')).toBe('Against baseline base: 2 correct documents gained, 1 lost.')
    expect(compareHeadline([row('lost'), row('lost')], 2, 'base')).toBe('Against baseline base: none gained, 2 correct documents lost.')
  })

  it('none gained or lost', () => {
    expect(compareHeadline([row('unchanged'), row('gained', notCorrect)], 2, 'base')).toBe('Against baseline base: no correct document was gained or lost.')
    expect(compareHeadline([], 0, 'base')).toBe('Against baseline base: no correct document was gained or lost.')
  })

  it('adds the correct documents that moved rank, and a row judged relevant in either run counts', () => {
    const rows = [row('gained', { baseline: unjudged }), row('rank_changed'), row('rank_changed'), row('rank_changed', notCorrect)]
    expect(compareHeadline(rows, 4, 'base')).toBe('Against baseline base: 1 correct document gained, none lost. 2 correct documents moved rank.')
    expect(compareHeadline([row('rank_changed')], 1, 'base')).toBe('Against baseline base: no correct document was gained or lost. 1 correct document moved rank.')
  })

  it('says so when only some of the pairs are loaded', () => {
    expect(compareHeadline([row('lost')], 120, 'base')).toBe('Against baseline base: none gained, 1 correct document lost. Counted over the first 1 of 120 documents.')
    expect(compareHeadline([row('lost')], null, 'base')).toBe('Against baseline base: none gained, 1 correct document lost.')
  })

  it('isCorrect reads either side, including a side with no row', () => {
    expect(isCorrect(row('gained', { baseline: null }))).toBe(true)
    expect(isCorrect(row('gained', { baseline: null, candidate: unjudged }))).toBe(false)
  })
})
