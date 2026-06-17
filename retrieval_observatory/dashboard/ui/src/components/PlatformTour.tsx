import { useState } from 'react'
import type { DemoContext } from '../api'

const STORAGE_KEY = 'retobs_platform_tour_dismissed'

interface Props {
  context: DemoContext
}

const STEPS = [
  {
    title: 'Forge — stress queries',
    body: 'See temporal and alias failure patterns Forge found in the corpus, and the hard queries generated to expose them.',
    href: (ctx: DemoContext) => `#/forge/${ctx.forge_dataset_id || 'demo'}`,
  },
  {
    title: 'Benchmarks — compare runs',
    body: 'Select baseline (BM25 k=20) and degraded (k=1) runs to see recall drops, failure labels, and per-query forensics.',
    href: () => '#/benchmarks',
  },
  {
    title: 'TraceLens — production drift',
    body: 'Open the Drift tab to compare recent traffic vs the baseline window. Failures are suspected proxies, not measured Recall.',
    href: (ctx: DemoContext) => `#/tracelens/${ctx.tracelens_service || 'demo'}`,
  },
  {
    title: 'Advisor — regressions & fixes',
    body: 'Regression center compares baseline vs degraded with significance tests. Recommendations suggest concrete pipeline changes.',
    href: () => '#/advisor',
  },
  {
    title: 'Query lineage — the spine',
    body: 'One query links Forge origin, benchmark scores, and categorical production trace matches.',
    href: (ctx: DemoContext) => `#/query/${encodeURIComponent(ctx.sample_query_id || '')}`,
  },
]

export default function PlatformTour({ context }: Props) {
  const [open, setOpen] = useState(() => localStorage.getItem(STORAGE_KEY) !== '1')
  const [step, setStep] = useState(0)

  if (!open || !context.baseline_run_id) return null

  const current = STEPS[step]
  const href = current.href(context)

  const dismiss = () => {
    localStorage.setItem(STORAGE_KEY, '1')
    setOpen(false)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-w-md w-full rounded-xl bg-white shadow-xl border border-gray-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-indigo-50 via-amber-50 to-teal-50">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Reliability platform tour</p>
          <h2 className="text-lg font-bold text-gray-900 mt-0.5">{current.title}</h2>
          <p className="text-xs text-gray-500 mt-1">Step {step + 1} of {STEPS.length}</p>
        </div>
        <div className="px-5 py-4">
          <p className="text-sm text-gray-700 leading-relaxed">{current.body}</p>
          <p className="text-[11px] text-gray-400 mt-3">
            Demo DB: baseline <span className="font-mono">{context.baseline_run_id}</span> vs degraded{' '}
            <span className="font-mono">{context.candidate_run_id}</span>
          </p>
        </div>
        <div className="px-5 py-3 border-t border-gray-100 flex items-center justify-between gap-2">
          <button type="button" onClick={dismiss} className="text-xs text-gray-500 hover:text-gray-700">
            Dismiss
          </button>
          <div className="flex gap-2">
            {step > 0 && (
              <button
                type="button"
                onClick={() => setStep((s) => s - 1)}
                className="px-3 py-1.5 rounded border border-gray-200 text-xs text-gray-600"
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
