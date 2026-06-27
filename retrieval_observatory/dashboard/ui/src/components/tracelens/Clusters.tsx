import { useEffect, useState } from 'react'
import { fetchTraceClusters, QueryClusterRow } from '../../api'

export default function Clusters({ service, since }: { service: string; since?: string }) {
  const [clusters, setClusters] = useState<QueryClusterRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setClusters(null)
    fetchTraceClusters(service, since).then(setClusters).catch((e) => setError(e.message))
  }, [service, since])

  if (error) return <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
  if (!clusters) return <div className="text-sm text-gray-400">Clustering traffic…</div>
  if (clusters.length === 0) return <p className="text-sm text-gray-400">No traffic to cluster in this window.</p>

  return (
    <div>
      <p className="text-xs text-gray-500 mb-3">
        Current clustering method: heuristic buckets by predicted difficulty × query length. Use these as
        operational segments; embedding-based semantic clustering is not in this view yet.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {clusters.map((c) => (
          <div key={c.cluster} className="rounded-lg border border-gray-200 bg-white p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-800">{c.cluster}</span>
              <span className="text-xs text-gray-400">{c.size} ({Math.round(c.share * 100)}%)</span>
            </div>
            <div className="flex gap-4 mt-1.5 text-[11px] text-gray-500">
              <span>suspected {(c.suspected_rate * 100).toFixed(0)}%</span>
              <span>p50 {c.latency_p50.toFixed(0)} ms</span>
            </div>
            {c.examples.length > 0 && (
              <ul className="mt-2 space-y-0.5">
                {c.examples.map((ex, i) => (
                  <li key={i} className="text-[11px] text-gray-500 truncate">· {ex}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
