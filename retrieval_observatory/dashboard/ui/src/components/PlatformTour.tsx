import { useState } from 'react'
import type { DemoContext } from '../api'

export const PLATFORM_TOUR_STORAGE_KEY = 'retobs_platform_tour_dismissed'

interface Props {
  context: DemoContext
  open: boolean
  onClose: () => void
}

const STEPS = [
  {
    title: 'Test Sets — stress queries',
    body: 'See temporal and alias failure patterns found in the corpus, and the hard queries generated to expose them.',
    href: (ctx: DemoContext) => `#/test-sets/${ctx.forge_dataset_id || 'demo'}`,
  },
  {
    title: 'Compare — baseline and candidate',
    body: 'Select baseline (BM25 k=20) and degraded (k=1) runs to see recall drops, failure labels, and per-query forensics.',
    href: () => '#/compare',
  },
  {
    title: 'Production — drift evidence',
    body: 'Open the Drift tab to compare recent traffic vs the baseline window. Failures are suspected proxies, not measured Recall.',
    href: (ctx: DemoContext) => `#/production/${ctx.tracelens_service || 'demo'}`,
  },
  {
    title: 'Run findings — regressions & fixes',
    body: 'Regression center compares baseline vs degraded with significance tests. Recommendations suggest concrete pipeline changes.',
    href: () => '#/runs',
  },
  {
    title: 'Query lineage — the spine',
    body: 'One query links Test Set origin, evaluation scores, and categorical production trace matches.',
    href: (ctx: DemoContext) => `#/queries/${encodeURIComponent(ctx.sample_query_id || '')}`,
  },
]

export default function PlatformTour({ context, open, onClose }: Props) {
  const [step, setStep] = useState(0)

  if (!open || !context.baseline_run_id) return null

  const current = STEPS[step]
  const href = current.href(context)

  const dismiss = () => {
    localStorage.setItem(PLATFORM_TOUR_STORAGE_KEY, '1')
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-w-md w-full rounded-xl bg-white dark:bg-slate-900 shadow-xl border border-gray-200 dark:border-slate-700 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 dark:border-slate-800 bg-gradient-to-r from-indigo-50 via-amber-50 to-teal-50">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">Reliability platform tour</p>
          <h2 className="text-lg font-bold text-gray-900 dark:text-slate-100 mt-0.5">{current.title}</h2>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-1">Step {step + 1} of {STEPS.length}</p>
        </div>
        <div className="px-5 py-4">
          <p className="text-sm text-gray-700 dark:text-slate-200 leading-relaxed">{current.body}</p>
          <p className="text-[11px] text-gray-400 dark:text-slate-500 mt-3">
            Demo DB: baseline <span className="font-mono">{context.baseline_run_id}</span> vs degraded{' '}
            <span className="font-mono">{context.candidate_run_id}</span>
          </p>
          <p className="text-[11px] text-gray-400 dark:text-slate-500 mt-2">
            Reopen anytime from the left rail (Platform tour) or the demo bar at the top.
          </p>
        </div>
        <div className="px-5 py-3 border-t border-gray-100 dark:border-slate-800 flex items-center justify-between gap-2">
          <button type="button" onClick={dismiss} className="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700">
            Dismiss
          </button>
          <div className="flex gap-2">
            {step > 0 && (
              <button
                type="button"
                onClick={() => setStep((s) => s - 1)}
                className="px-3 py-1.5 rounded border border-gray-200 dark:border-slate-700 text-xs text-gray-600 dark:text-slate-300"
              >
                Back
              </button>
            )}
            {step < STEPS.length - 1 ? (
              <button
                type="button"
                onClick={() => setStep((s) => s + 1)}
                className="px-3 py-1.5 rounded bg-indigo-600 text-white text-xs font-medium"
              >
                Next
              </button>
            ) : (
              <a
                href={href}
                onClick={dismiss}
                className="px-3 py-1.5 rounded bg-indigo-600 text-white text-xs font-medium"
              >
                Open lineage
              </a>
            )}
            {step < STEPS.length - 1 && (
              <a
                href={href}
                className="px-3 py-1.5 rounded border border-indigo-200 text-indigo-700 text-xs font-medium"
              >
                Go there
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
