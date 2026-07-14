import { useEffect, useState } from 'react'
import { fetchTraceDrift, DriftFinding } from '../../api'
import { METRIC_GLOSSARY } from '../../utils/metricGlossary'
import TraceDetail from './TraceDetail'

const SEVERITY_STYLE: Record<string, string> = {
  significant: 'border-rose-200 bg-rose-50 text-rose-700',
  moderate: 'border-amber-200 bg-amber-50 text-amber-700',
  none: 'border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800/60 text-gray-500 dark:text-slate-400',
}

function DistTable({ title, dist }: { title: string; dist: Record<string, number> }) {
  const entries = Object.entries(dist)
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-gray-400 dark:text-slate-500 mb-1">{title}</p>
      <div className="space-y-0.5">
        {entries.map(([k, v]) => (
          <div key={k} className="flex justify-between text-[11px] text-gray-600 dark:text-slate-300">
            <span className="truncate mr-2">{k}</span>
            <span className="tabular-nums">{typeof v === 'number' ? (v < 1 ? v.toFixed(3) : v.toFixed(0)) : v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Finding({ f, onOpenTrace }: { f: DriftFinding; onOpenTrace: (traceId: string) => void }) {
  const [open, setOpen] = useState(f.drifted)
  return (
    <div className={`rounded-lg border ${f.drifted ? 'border-gray-200 dark:border-slate-700' : 'border-gray-100 dark:border-slate-800'} bg-white dark:bg-slate-900`}>
      <button type="button" onClick={() => setOpen((v) => !v)} className="w-full flex items-center justify-between px-4 py-3 text-left">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-800 dark:text-slate-100">{f.feature}</span>
          <span className="text-[10px] text-gray-400 dark:text-slate-500">{f.method} = {f.statistic}</span>
        </div>
        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border capitalize ${SEVERITY_STYLE[f.severity] || SEVERITY_STYLE.none}`}>
          {f.drifted ? f.severity : 'stable'}
        </span>
      </button>
      {open && (
        <div className="px-4 pb-3 border-t border-gray-100 dark:border-slate-800 pt-3">
          <div className="grid grid-cols-2 gap-4"><DistTable title={`Baseline (n=${f.baseline_n})`} dist={f.baseline} /><DistTable title={`Recent (n=${f.recent_n})`} dist={f.recent} /></div>
          <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-ink-faint">
            <span>evidence: {f.evidence_class}</span><span>method: {f.method}</span><span>threshold: {f.threshold}</span><span>baseline: {f.baseline_window.since} → {f.baseline_window.until}</span><span>recent: {f.recent_window.since} → now</span>{f.sample_limited && <span>sample capped at 10,000/window</span>}
            {f.supporting_trace_ids[0] && <button type="button" onClick={() => onOpenTrace(f.supporting_trace_ids[0])} className="ml-auto rounded border px-2 py-1 text-indigo-700 dark:text-indigo-300">Open recent sample trace →</button>}
          </div>
        </div>
      )}
    </div>
  )
}

export default function DriftExplorer({ dbId, service }: { dbId: string; service: string }) {
  const [findings, setFindings] = useState<DriftFinding[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openTraceId, setOpenTraceId] = useState<string | null>(null)

  useEffect(() => {
    setFindings(null)
    fetchTraceDrift(dbId, service).then(setFindings).catch((e) => setError(e.message))
  }, [dbId, service])

  if (error) return <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
  if (!findings) return <div className="text-sm text-gray-400 dark:text-slate-500">Computing drift…</div>

  const drifted = findings.filter((f) => f.drifted)
  return (
    <div>
      <p className="text-xs text-gray-500 dark:text-slate-400 mb-3">
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
        {findings.map((f) => <Finding key={f.feature} f={f} onOpenTrace={setOpenTraceId} />)}
      </div>
      {openTraceId && <TraceDetail dbId={dbId} traceId={openTraceId} onClose={() => setOpenTraceId(null)} />}
    </div>
  )
}
