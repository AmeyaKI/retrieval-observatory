import { CandidateJourneyRow } from '../api'

/** Seen-candidate universe confusion labels (not corpus-wide TN). */
export type ConfusionLabel = 'TP' | 'FP' | 'FN' | 'TN'

export function confusionLabel(row: CandidateJourneyRow): ConfusionLabel {
  if (row.relevant && row.survived) return 'TP'
  if (!row.relevant && row.survived) return 'FP'
  if (row.relevant && !row.survived) return 'FN'
  return 'TN'
}

export const CONFUSION_META: Record<
  ConfusionLabel,
  { title: string; short: string; className: string }
> = {
  TP: {
    title: 'True positive',
    short: 'Relevant & returned',
    className: 'bg-emerald-100 text-emerald-900 border-emerald-600 dark:bg-emerald-950 dark:text-emerald-100',
  },
  FP: {
    title: 'False positive',
    short: 'Returned but not relevant',
    className: 'bg-amber-100 text-amber-950 border-amber-700 dark:bg-amber-950 dark:text-amber-100',
  },
  FN: {
    title: 'False negative',
    short: 'Relevant but missing',
    className: 'bg-red-100 text-red-950 border-red-700 dark:bg-red-950 dark:text-red-100',
  },
  TN: {
    title: 'True negative',
    short: 'Seen mid-pipeline, correctly not final',
    className: 'bg-slate-200 text-slate-900 border-slate-600 dark:bg-slate-800 dark:text-slate-100',
  },
}

export function countConfusion(rows: CandidateJourneyRow[]): Record<ConfusionLabel, number> {
  const counts: Record<ConfusionLabel, number> = { TP: 0, FP: 0, FN: 0, TN: 0 }
  for (const row of rows) counts[confusionLabel(row)] += 1
  return counts
}
