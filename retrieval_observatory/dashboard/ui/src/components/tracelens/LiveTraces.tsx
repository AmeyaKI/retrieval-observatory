import { useEffect, useState } from 'react'
import { fetchTraces, TraceRow } from '../../api'
import { difficultyChipClass } from '../../utils/difficulty'
import SuspectedFailureChip from './SuspectedFailureChip'
import TraceDetail from './TraceDetail'
import { useDashboardContext } from '../../context/DashboardContext'

interface Props {
  dbId: string
  service: string
  since?: string
  initialFilter?: { difficulty?: string; status?: string; suspected_only?: boolean }
}

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return iso
  }
}

export default function LiveTraces({ dbId, service, since, initialFilter }: Props) {
  const { selection, updateSelection } = useDashboardContext()
  const urlFilters = Object.fromEntries(selection.filters.map(value => value.split(/=(.*)/s).slice(0, 2)))
  const [rows, setRows] = useState<TraceRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState(initialFilter?.status || urlFilters.status || '')
  const [difficultyFilter, setDifficultyFilter] = useState(initialFilter?.difficulty || urlFilters.difficulty || '')
  const [suspectedOnly, setSuspectedOnly] = useState(initialFilter?.suspected_only || urlFilters.suspected === 'true')
  const [offset, setOffset] = useState(Number(urlFilters.offset || 0))
  const [total, setTotal] = useState(0)

  useEffect(() => {
    setRows(null)
    fetchTraces(dbId, service, {
      since,
      status: statusFilter || undefined,
      difficulty: difficultyFilter || undefined,
      suspected_only: suspectedOnly || undefined, limit: 100, offset,
    })
      .then((page) => { setRows(page.items); setTotal(page.total) })
      .catch((e) => setError(e.message))
  }, [dbId, service, since, statusFilter, difficultyFilter, suspectedOnly, offset])

  useEffect(() => {
    const filters = [statusFilter && `status=${statusFilter}`, difficultyFilter && `difficulty=${difficultyFilter}`, suspectedOnly && 'suspected=true', offset && `offset=${offset}`].filter(Boolean) as string[]
    if (filters.join('|') !== selection.filters.join('|')) updateSelection({ filters }, 'replace')
  }, [statusFilter, difficultyFilter, suspectedOnly, offset])

  if (error) return <div className="p-3 bg-status-negative/10 border border-status-negative/30 rounded text-sm text-status-negative">{error}</div>

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 mb-3 text-xs">
        <label className="flex items-center gap-1 text-ink-muted">
          Status:
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="border border-hairline rounded px-1.5 py-1 bg-surface">
            <option value="">all</option><option value="OK">OK</option><option value="ERROR">ERROR</option><option value="TIMEOUT">TIMEOUT</option>
          </select>
        </label>
        <label className="flex items-center gap-1 text-ink-muted">
          Difficulty:
          <select value={difficultyFilter} onChange={(e) => setDifficultyFilter(e.target.value)} className="border border-hairline rounded px-1.5 py-1 bg-surface">
            <option value="">all</option><option value="easy">easy</option><option value="medium">medium</option><option value="hard">hard</option><option value="extreme">extreme</option>
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-ink-muted">
          <input type="checkbox" className="accent-accent" checked={suspectedOnly} onChange={(e) => setSuspectedOnly(e.target.checked)} />
          Suspected failures only
        </label>
        <span className="text-ink-faint ml-auto">{rows ? `${offset + 1}–${offset + rows.length} of ${total}` : '…'} traces</span>
      </div>

      <div className="flex justify-end gap-2 mt-2">
        <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 100))} className="px-2 py-1 border rounded disabled:opacity-40">Previous</button>
        <button type="button" disabled={offset + 100 >= total} onClick={() => setOffset(offset + 100)} className="px-2 py-1 border rounded disabled:opacity-40">Next</button>
      </div>

      <div className="border border-hairline rounded-lg overflow-hidden">
        <div className="max-h-[32rem] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 z-10 bg-surface-muted/95 backdrop-blur-sm text-ink-muted">
              <tr>
                <th className="text-left font-medium px-3 py-1.5 w-40">Time</th>
                <th className="text-left font-medium px-3 py-1.5">Query</th>
                <th className="text-left font-medium px-3 py-1.5 w-28">Pipeline</th>
                <th className="text-left font-medium px-3 py-1.5 w-20">Status</th>
                <th className="text-right font-medium px-3 py-1.5 w-20">Latency</th>
                <th className="text-left font-medium px-3 py-1.5 w-24">Difficulty</th>
                <th className="text-left font-medium px-3 py-1.5 w-56">Suspected</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {rows?.map((r) => (
                <tr key={r.trace_id} className="hover:bg-surface-muted cursor-pointer" onClick={() => setOpenId(r.trace_id)}>
                  <td className="px-3 py-1 text-ink-muted font-mono tabular-nums whitespace-nowrap">{fmtTime(r.timestamp)}</td>
                  <td className="px-3 py-1 text-ink truncate max-w-0">{r.query_text}</td>
                  <td className="px-3 py-1 text-ink-muted font-mono">{r.pipeline_id}</td>
                  <td className="px-3 py-1">
                    <span className={r.status === 'OK' ? 'text-status-positive' : 'text-status-negative font-medium'}>{r.status}</span>
                  </td>
                  <td className="px-3 py-1 text-right tabular-nums font-mono text-ink-muted">{r.total_latency_ms.toFixed(0)} ms</td>
                  <td className="px-3 py-1">
                    {r.predicted_difficulty && (
                      <span className={`px-1.5 py-0.5 rounded border text-[10px] font-medium capitalize ${difficultyChipClass(r.predicted_difficulty)}`}>
                        {r.predicted_difficulty}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-1">
                    <div className="flex flex-wrap gap-1">
                      {r.suspected_failures.map((s) => <SuspectedFailureChip key={s} signal={s} />)}
                    </div>
                  </td>
                </tr>
              ))}
              {rows && rows.length === 0 && (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-ink-faint">No traces match these filters.</td></tr>
              )}
              {!rows && (
                <tr><td colSpan={7} className="px-3 py-8 text-center text-ink-faint">Loading traces…</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

          {openId && <TraceDetail dbId={dbId} traceId={openId} onClose={() => setOpenId(null)} />}
    </div>
  )
}
