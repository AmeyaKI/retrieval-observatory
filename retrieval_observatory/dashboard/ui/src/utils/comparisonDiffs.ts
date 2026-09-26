import { JourneyAlignment, JourneyChangeKind, JourneyDiffRow, JourneySide } from '../api'

// Pure helpers over paired journey rows (run comparison). Labels carry a glyph and text,
// never colour alone; ordering mirrors the server's priority so a re-sort is a no-op.

export const CHANGE_LABELS: Record<JourneyChangeKind, { glyph: string; label: string }> = {
  lost: { glyph: '✕', label: 'Lost' },
  gained: { glyph: '✓', label: 'Gained' },
  membership_changed: { glyph: '◐', label: 'Membership changed' },
  rank_changed: { glyph: '↕', label: 'Rank changed' },
  path_changed: { glyph: '⇢', label: 'Path changed' },
  unchanged: { glyph: '=', label: 'Unchanged' },
  unaligned: { glyph: '∅', label: 'Unaligned' },
}

export function changeLabel(kind: JourneyChangeKind | string): string {
  return CHANGE_LABELS[kind as JourneyChangeKind]?.label ?? kind
}

export function changeGlyph(kind: JourneyChangeKind | string): string {
  return CHANGE_LABELS[kind as JourneyChangeKind]?.glyph ?? '?'
}

export const ALIGNMENT_LABELS: Record<JourneyAlignment, string> = {
  aligned: 'Aligned',
  query_unaligned: 'Query input differs',
  entity_revision_changed: 'Entity revision changed',
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

/** One side of a pair in words: `included #2 · relevant`, `excluded at select · unjudged`,
 * `membership unknown · relevant`, or `no row` when the run holds no row for the entity. */
export function sideSummary(side: JourneySide | null): string {
  if (!side) return 'no row'
  const membership = side.final_membership === 'included' ? 'included' : side.final_membership === 'excluded' ? 'excluded' : 'membership unknown'
  const rank = side.final_rank != null ? ` #${side.final_rank}` : ''
  const boundary = side.final_membership === 'excluded' && side.loss_boundary ? ` at ${side.loss_boundary}` : ''
  return `${membership}${rank}${boundary} · ${side.judgment}`
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
