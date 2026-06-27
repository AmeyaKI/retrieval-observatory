import { useEffect, useState } from 'react'
import { fetchTraceDrift, DriftFinding } from '../../api'
import { METRIC_GLOSSARY } from '../../utils/metricGlossary'

const SEVERITY_STYLE: Record<string, string> = {
  significant: 'border-rose-200 bg-rose-50 text-rose-700',
  moderate: 'border-amber-200 bg-amber-50 text-amber-700',
  none: 'border-gray-200 bg-gray-50 text-gray-500',
}

function DistTable({ title, dist }: { title: string; dist: Record<string, number> }) {
  const entries = Object.entries(dist)
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">{title}</p>
      <div className="space-y-0.5">
        {entries.map(([k, v]) => (
          <div key={k} className="flex justify-between text-[11px] text-gray-600">
            <span className="truncate mr-2">{k}</span>
            <span className="tabular-nums">{typeof v === 'number' ? (v < 1 ? v.toFixed(3) : v.toFixed(0)) : v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Finding({ f }: { f: DriftFinding }) {
  const [open, setOpen] = useState(f.drifted)
  return (
    <div className={`rounded-lg border ${f.drifted ? 'border-gray-200' : 'border-gray-100'} bg-white`}>
      <button type="button" onClick={() => setOpen((v) => !v)} className="w-full flex items-center justify-between px-4 py-3 text-left">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-800">{f.feature}</span>
          <span className="text-[10px] text-gray-400">{f.method} = {f.statistic}</span>
        </div>
        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border capitalize ${SEVERITY_STYLE[f.severity] || SEVERITY_STYLE.none}`}>
          {f.drifted ? f.severity : 'stable'}
        </span>
      </button>
      {open && (
        <div className="px-4 pb-3 grid grid-cols-2 gap-4 border-t border-gray-100 pt-3">
          <DistTable title="Baseline" dist={f.baseline} />
          <DistTable title="Recent" dist={f.recent} />
        </div>
      )}
    </div>
  )
}

export default function DriftExplorer({ service }: { service: string }) {
  const [findings, setFindings] = useState<DriftFinding[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setFindings(null)
    fetchTraceDrift(service).then(setFindings).catch((e) => setError(e.message))
  }, [service])

  if (error) return <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
  if (!findings) return <div className="text-sm text-gray-400">Computing drift…</div>

  const drifted = findings.filter((f) => f.drifted)
  return (
    <div>
      <p className="text-xs text-gray-500 mb-3">
        Fixed windows: baseline = prior 8d→24h ago, recent = last 24h. PSI flags categorical shifts and KS flags latency shifts.
        {' '}Visible thresholds: PSI ≥0.10 = moderate, PSI ≥0.25 = significant; latency drift uses a KS test.
        {' '}{METRIC_GLOSSARY.tracelens_drift_thresholds}
      </p>
      {drifted.length === 0 && (
        <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-xs text-green-700 mb-3">
          No significant drift detected between the two windows.
        </div>
      )}
      <div className="space-y-2">
        {findings.map((f) => <Finding key={f.feature} f={f} />)}
      </div>
    </div>
  )
}
