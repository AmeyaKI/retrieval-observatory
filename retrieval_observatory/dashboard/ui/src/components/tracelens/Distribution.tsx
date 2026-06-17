import { useEffect, useState } from 'react'
import { fetchTraceDistribution, TraceDistribution } from '../../api'
import { difficultyBarColor, DIFFICULTY_ORDER } from '../../utils/difficulty'

function Bars({ counts, total, colorFor }: { counts: Record<string, number>; total: number; colorFor?: (k: string) => string }) {
  const entries = Object.entries(counts)
  if (!entries.length) return <p className="text-xs text-gray-400">No data</p>
  const max = Math.max(...entries.map(([, n]) => n)) || 1
  return (
    <div className="space-y-1.5">
      {entries.map(([k, n]) => (
        <div key={k} className="flex items-center gap-2 text-xs">
          <span className="w-28 shrink-0 text-gray-600 truncate" title={k}>{k}</span>
          <div className="flex-1 bg-gray-100 rounded-full h-2.5 overflow-hidden">
            <div className="h-full rounded-full" style={{ width: `${(n / max) * 100}%`, backgroundColor: colorFor ? colorFor(k) : '#14b8a6' }} />
          </div>
          <span className="w-16 text-right tabular-nums text-gray-500">{n} ({Math.round((n / total) * 100)}%)</span>
        </div>
      ))}
    </div>
  )
}

function Card({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <p className="text-sm font-semibold text-gray-700">{title}</p>
      {subtitle && <p className="text-[11px] text-gray-400 mb-2">{subtitle}</p>}
      <div className="mt-2">{children}</div>
    </div>
  )
}

// Order difficulty buckets consistently easy→extreme.
function orderDifficulty(counts: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {}
  for (const d of DIFFICULTY_ORDER) if (counts[d] != null) out[d] = counts[d]
  for (const k of Object.keys(counts)) if (!(k in out)) out[k] = counts[k]
  return out
}

export default function Distribution({ service, since }: { service: string; since?: string }) {
  const [dist, setDist] = useState<TraceDistribution | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setDist(null)
    fetchTraceDistribution(service, since).then(setDist).catch((e) => setError(e.message))
  }, [service, since])

  if (error) return <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
  if (!dist) return <div className="text-sm text-gray-400">Loading distribution…</div>
  if (dist.n === 0) return <p className="text-sm text-gray-400">No traces in this window.</p>

  const lat = dist.latency_percentiles
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <Card title="Predicted difficulty" subtitle="Heuristic difficulty of incoming queries">
        <Bars counts={orderDifficulty(dist.by_difficulty)} total={dist.n} colorFor={difficultyBarColor} />
      </Card>
      <Card title="Query length" subtitle="Tokens per query">
        <Bars counts={dist.by_length_bin} total={dist.n} />
      </Card>
      <Card title="Status" subtitle="Pipeline completion status">
        <Bars counts={dist.by_status} total={dist.n} />
      </Card>
      <Card title="Suspected failure signals" subtitle="Label-free proxy signals (a trace may carry several)">
        {Object.keys(dist.by_failure_label).length ? (
          <Bars counts={dist.by_failure_label} total={dist.n} colorFor={() => '#fb7185'} />
        ) : (
          <p className="text-xs text-gray-400">No suspected failures in this window.</p>
        )}
      </Card>
      <Card title="Latency percentiles" subtitle="Total latency (ms)">
        <div className="grid grid-cols-4 gap-2 text-center">
          {(['p50', 'p90', 'p95', 'p99'] as const).map((p) => (
            <div key={p}>
              <p className="text-[10px] text-gray-400 uppercase">{p}</p>
              <p className="text-lg font-bold text-gray-800 tabular-nums">{lat[p]?.toFixed(0)}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
