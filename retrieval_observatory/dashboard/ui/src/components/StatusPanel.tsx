import type { ReactNode } from 'react'

export type StatusKind = 'loading' | 'empty' | 'partial' | 'error' | 'invalid' | 'unavailable'

const PRESENTATION: Record<StatusKind, { icon: string; label: string; classes: string }> = {
  loading: { icon: '…', label: 'Loading', classes: 'border-status-neutral/30 bg-status-neutral/10 text-status-neutral' },
  empty: { icon: '∅', label: 'Empty', classes: 'border-status-neutral/30 bg-status-neutral/10 text-status-neutral' },
  partial: { icon: '◐', label: 'Partial evidence', classes: 'border-status-warning/40 bg-status-warning/10 text-status-warning' },
  error: { icon: '!', label: 'Error', classes: 'border-status-negative/40 bg-status-negative/10 text-status-negative' },
  invalid: { icon: '×', label: 'Invalid', classes: 'border-status-negative/40 bg-status-negative/10 text-status-negative' },
  unavailable: { icon: '?', label: 'Unavailable', classes: 'border-status-neutral/30 bg-status-neutral/10 text-status-neutral' },
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
      className={`rounded-lg border p-3 text-sm ${presentation.classes}`}
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
