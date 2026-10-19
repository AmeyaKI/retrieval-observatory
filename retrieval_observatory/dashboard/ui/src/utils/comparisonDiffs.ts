import { JourneyAlignment, JourneyChangeKind, JourneyDiffRow, JourneySide } from '../api'
import { plural } from './flowWords'

// Pure helpers over paired journey rows (run comparison). Changes read in plain words with a tone,
// never colour alone; ordering mirrors the server's priority so a re-sort is a no-op.

export type ChangeTone = 'negative' | 'positive' | 'neutral'

export const CHANGE_LABELS: Record<JourneyChangeKind, { label: string; tone: ChangeTone }> = {
  lost: { label: 'Lost', tone: 'negative' },
  gained: { label: 'Gained', tone: 'positive' },
  membership_changed: { label: 'In or out changed', tone: 'neutral' },
  rank_changed: { label: 'Moved', tone: 'neutral' },
  path_changed: { label: 'Different path', tone: 'neutral' },
  unchanged: { label: 'Unchanged', tone: 'neutral' },
  unaligned: { label: "Can't be compared", tone: 'neutral' },
}

export function changeWords(kind: JourneyChangeKind | string): { label: string; tone: ChangeTone } {
  return CHANGE_LABELS[kind as JourneyChangeKind] ?? { label: kind, tone: 'neutral' }
}

export const ALIGNMENT_LABELS: Record<JourneyAlignment, string> = {
  aligned: 'Aligned',
  query_unaligned: 'Question input differs',
  entity_revision_changed: 'Document revision changed',
  missing_in_baseline: 'Missing in baseline',
  missing_in_candidate: 'Missing in candidate',
  corpus_changed: 'Corpus changed',
}

export function alignmentLabel(alignment: JourneyAlignment | string): string {
  return ALIGNMENT_LABELS[alignment as JourneyAlignment] ?? alignment
}

export const CHANGE_PRIORITY: Record<JourneyChangeKind, number> = {
  lost: 0,
  gained: 1,
  membership_changed: 2,
  rank_changed: 3,
  path_changed: 4,
  unaligned: 5,
  unchanged: 6,
}

const CHANGE_KINDS = Object.keys(CHANGE_PRIORITY) as JourneyChangeKind[]

function priorityOf(kind: JourneyChangeKind | string): number {
  return CHANGE_PRIORITY[kind as JourneyChangeKind] ?? CHANGE_KINDS.length
}

/** A new array in display order: change priority, then query_id, namespace, entity_id. */
export function sortDiffRows<Row extends JourneyDiffRow>(rows: Row[]): Row[] {
  return [...rows].sort(
    (a, b) =>
      priorityOf(a.change) - priorityOf(b.change) ||
      a.query_id.localeCompare(b.query_id) ||
      a.namespace.localeCompare(b.namespace) ||
      a.entity_id.localeCompare(b.entity_id),
  )
}

/** A correct document: judged relevant in either run. */
export function isCorrect(row: JourneyDiffRow): boolean {
  return row.baseline?.judgment === 'relevant' || row.candidate?.judgment === 'relevant'
}

/** One side of a pair in words. Correct documents read by outcome (`Delivered at #2`, `Dropped by
 * Recency Filter`); other rows by membership (`In the top 3 at #1`). A partly recorded side names no
 * step it was dropped by. */
export function sideWords(side: JourneySide | null, k: number | null, stepNameOf: (opId: string) => string = (opId) => opId): string {
  if (!side) return 'No row in this run'
  const rank = side.final_rank
  switch (side.outcome) {
    case 'relevant_delivered':
      return rank != null ? `Delivered at #${rank}` : 'Delivered'
    case 'retained_below_cutoff':
      return rank != null ? `Ranked too low · #${rank}` : 'Ranked too low'
    case 'relevant_excluded':
      return side.loss_boundary && side.capture_state !== 'partial' ? `Dropped by ${stepNameOf(side.loss_boundary)}` : 'Not delivered'
    case 'not_observed':
      return 'Never found'
    case 'insufficient_evidence':
      return 'Not enough evidence'
  }
  if (side.final_membership === 'included') {
    const top = k != null ? `In the top ${k}` : 'Delivered'
    return rank != null ? `${top} at #${rank}` : top
  }
  if (side.final_membership === 'excluded') return k != null ? `Not in the top ${k}` : 'Not delivered'
  return 'Not enough evidence'
}

/** The compare headline over correct documents only: `Against baseline b: 1 correct document gained,
 * none lost. 2 correct documents moved rank.` Says so when only some of the pairs are loaded. */
export function compareHeadline(rows: JourneyDiffRow[], total: number | null, baseline: string): string {
  const correct = rows.filter(isCorrect)
  const count = (kind: JourneyChangeKind) => correct.filter((row) => row.change === kind).length
  const gained = count('gained')
  const lost = count('lost')
  const moved = count('rank_changed')
  const first =
    gained === 0 && lost === 0
      ? 'no correct document was gained or lost.'
      : gained === 0
        ? `none gained, ${plural(lost, 'correct document')} lost.`
        : `${plural(gained, 'correct document')} gained, ${lost === 0 ? 'none' : lost} lost.`
  const sentences = [`Against baseline ${baseline}: ${first}`]
  if (moved > 0) sentences.push(`${plural(moved, 'correct document')} moved rank.`)
  if (total != null && rows.length < total) sentences.push(`Counted over the first ${rows.length} of ${total} documents.`)
  return sentences.join(' ')
}

export interface DiffTotals {
  pairs: number
  byChange: Record<JourneyChangeKind, number>
  captureLimited: number
}

export function diffTotals(rows: JourneyDiffRow[]): DiffTotals {
  const byChange = Object.fromEntries(CHANGE_KINDS.map((kind) => [kind, 0])) as Record<JourneyChangeKind, number>
  let captureLimited = 0
  for (const row of rows) {
    if (row.change in byChange) byChange[row.change] += 1
    if (row.capture_limited) captureLimited += 1
  }
  return { pairs: rows.length, byChange, captureLimited }
}
