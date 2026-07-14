import type { ReactNode } from 'react'

export type StatusKind = 'loading' | 'empty' | 'partial' | 'error' | 'invalid' | 'unavailable'

const PRESENTATION: Record<StatusKind, { icon: string; label: string; classes: string }> = {
  loading: { icon: '…', label: 'Loading', classes: 'border-slate-200 bg-slate-50 text-slate-700' },
  empty: { icon: '∅', label: 'Empty', classes: 'border-slate-200 bg-slate-50 text-slate-700' },
  partial: { icon: '◐', label: 'Partial evidence', classes: 'border-amber-300 bg-amber-50 text-amber-900' },
  error: { icon: '!', label: 'Error', classes: 'border-red-300 bg-red-50 text-red-900' },
  invalid: { icon: '×', label: 'Invalid', classes: 'border-red-300 bg-red-50 text-red-900' },
  unavailable: { icon: '?', label: 'Unavailable', classes: 'border-slate-300 bg-slate-50 text-slate-700' },
}

export default function StatusPanel({
  kind,
  message,
  title,
}: {
  kind: StatusKind
  message: ReactNode
  title?: string
}) {
  const presentation = PRESENTATION[kind]
  const urgent = kind === 'error' || kind === 'invalid'
  return (
    <div
      className={`rounded-lg border p-3 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 ${presentation.classes}`}
      data-state={kind}
      role={urgent ? 'alert' : 'status'}
      aria-live={urgent ? 'assertive' : 'polite'}
    >
      <div className="flex items-start gap-2">
        <span aria-hidden="true" className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-current font-bold">
          {presentation.icon}
        </span>
        <div>
          <div className="font-semibold">{title ?? presentation.label}</div>
          <div className="mt-0.5 text-current/90">{message}</div>
        </div>
      </div>
    </div>
  )
}
