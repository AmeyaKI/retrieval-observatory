import { useEffect, useState } from 'react'
import { fetchTraceSummary, TraceSummary } from '../../api'
import { METRIC_GLOSSARY } from '../../utils/metricGlossary'

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint: string; tone?: 'bad' | 'warn' | 'ok' }) {
  const valueColor = tone === 'bad' ? 'text-rose-600' : tone === 'warn' ? 'text-amber-600' : 'text-gray-900 dark:text-slate-100'
  return (
    <div className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-4" title={hint}>
      <p className="text-xs text-gray-500 dark:text-slate-400">{label}</p>
      <p className={`text-2xl font-bold tabular-nums ${valueColor}`}>{value}</p>
    </div>
  )
}

export default function TraceLensOverview({ service, since }: { service: string; since?: string }) {
  const [summary, setSummary] = useState<TraceSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setSummary(null)
    fetchTraceSummary(service, since).then(setSummary).catch((e) => setError(e.message))
  }, [service, since])

  if (error) return <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
  if (!summary) {
    return (
      <div className="flex items-center gap-2 text-gray-400 dark:text-slate-500 text-sm">
        <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 dark:border-slate-600 border-t-teal-500" />
        Loading summary…
      </div>
    )
  }

  return (
    <div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Kpi label="Traces" value={summary.trace_count.toLocaleString()} hint="Total traces in this window." />
        <Kpi
          label="Error rate (>5% warn)"
          value={`${(summary.error_rate * 100).toFixed(1)}%`}
          hint={`Fraction of traces whose pipeline raised an error. ${METRIC_GLOSSARY.tracelens_error_rate_threshold}`}
          tone={summary.error_rate > 0.05 ? 'bad' : 'ok'}
        />
        <Kpi
          label="Suspected-failure rate (>10% warn)"
          value={`${(summary.suspected_failure_rate * 100).toFixed(1)}%`}
          hint={`Fraction of traces carrying at least one label-free proxy failure signal. Not measured Recall. ${METRIC_GLOSSARY.tracelens_suspected_rate_threshold}`}
          tone={summary.suspected_failure_rate > 0.1 ? 'warn' : 'ok'}
        />
        <Kpi label="OK rate" value={`${(summary.ok_rate * 100).toFixed(1)}%`} hint="Fraction of traces that completed without error." />
        <Kpi label="Latency p50" value={`${summary.latency_p50.toFixed(0)} ms`} hint="Median total latency." />
        <Kpi label="Latency p95 (>2000ms warn)" value={`${summary.latency_p95.toFixed(0)} ms`} hint={`95th-percentile total latency (tail). ${METRIC_GLOSSARY.tracelens_latency_p95_threshold}`} tone={summary.latency_p95 > 2000 ? 'warn' : 'ok'} />
      </div>
    </div>
  )
}
