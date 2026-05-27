import { useEffect, useState } from 'react'
import { fetchRunOverview, RunOverview as Overview } from '../api'
import { formatMetricKey } from '../utils/formatMetricKey'

export default function ExperimentOverview({ runId }: { runId: string }) {
  const [overview, setOverview] = useState<Overview | null>(null)

  useEffect(() => {
    setOverview(null)
    fetchRunOverview(runId).then(setOverview).catch(() => setOverview(null))
  }, [runId])

  if (!overview) return null

  const buckets = Object.entries(overview.diagnostics.difficulty_buckets || {})
  const labels = Object.entries(overview.diagnostics.failure_labels || {})

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      <div className="border border-gray-200 rounded p-3 bg-white">
        <div className="text-xs uppercase tracking-wide text-gray-500">Headline</div>
        <div className="mt-1 text-sm font-semibold text-gray-900">
          {overview.headline_winner ? formatMetricKey(overview.headline_winner.metric) : 'No winner yet'}
        </div>
        {overview.headline_winner && (
          <div className="text-2xl font-bold tabular-nums mt-1">{overview.headline_winner.mean.toFixed(4)}</div>
        )}
      </div>
      <div className="border border-gray-200 rounded p-3 bg-white">
        <div className="text-xs uppercase tracking-wide text-gray-500">Difficulty</div>
        <div className="mt-2 flex flex-wrap gap-2">
          {buckets.length ? buckets.map(([name, count]) => (
            <span key={name} className="text-xs px-2 py-1 rounded bg-gray-100 text-gray-700">{name}: {count}</span>
          )) : <span className="text-xs text-gray-400">No diagnostics</span>}
        </div>
      </div>
      <div className="border border-gray-200 rounded p-3 bg-white">
        <div className="text-xs uppercase tracking-wide text-gray-500">Failure Labels</div>
        <div className="mt-2 flex flex-wrap gap-2">
          {labels.length ? labels.map(([name, count]) => (
            <span key={name} className="text-xs px-2 py-1 rounded bg-red-50 text-red-700">{name}: {count}</span>
          )) : <span className="text-xs text-gray-400">No labeled failures</span>}
        </div>
      </div>
      {overview.warnings.length > 0 && (
        <div className="md:col-span-3 border border-amber-200 rounded p-3 bg-amber-50 text-sm text-amber-800">
          {overview.warnings.join(' ')}
        </div>
      )}
    </div>
  )
}
