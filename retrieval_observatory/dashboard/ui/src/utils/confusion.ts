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
    className: 'bg-emerald-50 text-emerald-800 border-emerald-300 dark:bg-emerald-950/40 dark:text-emerald-200',
  },
  FP: {
    title: 'False positive',
    short: 'Returned but not relevant',
    className: 'bg-amber-50 text-amber-900 border-amber-300 dark:bg-amber-950/40 dark:text-amber-200',
  },
  FN: {
    title: 'False negative',
    short: 'Relevant but missing',
    className: 'bg-red-50 text-red-800 border-red-300 dark:bg-red-950/40 dark:text-red-200',
  },
  TN: {
    title: 'True negative',
    short: 'Seen mid-pipeline, correctly not final',
    className: 'bg-slate-100 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300',
  },
}

export function countConfusion(rows: CandidateJourneyRow[]): Record<ConfusionLabel, number> {
  const counts: Record<ConfusionLabel, number> = { TP: 0, FP: 0, FN: 0, TN: 0 }
  for (const row of rows) counts[confusionLabel(row)] += 1
  return counts
}
