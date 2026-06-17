import { useEffect, useState } from 'react'
import { fetchTraces, TraceRow } from '../../api'
import { difficultyChipClass } from '../../utils/difficulty'
import SuspectedFailureChip from './SuspectedFailureChip'
import TraceDetail from './TraceDetail'

interface Props {
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

export default function LiveTraces({ service, since, initialFilter }: Props) {
  const [rows, setRows] = useState<TraceRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState(initialFilter?.status || '')
  const [difficultyFilter, setDifficultyFilter] = useState(initialFilter?.difficulty || '')
  const [suspectedOnly, setSuspectedOnly] = useState(initialFilter?.suspected_only || false)

  useEffect(() => {
    setRows(null)
    fetchTraces(service, {
      since,
      status: statusFilter || undefined,
      difficulty: difficultyFilter || undefined,
      suspected_only: suspectedOnly || undefined,
    })
      .then(setRows)
      .catch((e) => setError(e.message))
  }, [service, since, statusFilter, difficultyFilter, suspectedOnly])

  if (error) return <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 mb-3 text-xs">
        <label className="flex items-center gap-1 text-gray-600">
          Status:
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="border border-gray-200 rounded px-1.5 py-1 bg-white">
            <option value="">all</option><option value="OK">OK</option><option value="ERROR">ERROR</option><option value="TIMEOUT">TIMEOUT</option>
          </select>
        </label>
        <label className="flex items-center gap-1 text-gray-600">
          Difficulty:
          <select value={difficultyFilter} onChange={(e) => setDifficultyFilter(e.target.value)} className="border border-gray-200 rounded px-1.5 py-1 bg-white">
            <option value="">all</option><option value="easy">easy</option><option value="medium">medium</option><option value="hard">hard</option><option value="extreme">extreme</option>
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-gray-600">
          <input type="checkbox" className="accent-teal-500" checked={suspectedOnly} onChange={(e) => setSuspectedOnly(e.target.checked)} />
          Suspected failures only
        </label>
        <span className="text-gray-400 ml-auto">{rows?.length ?? '…'} traces</span>
      </div>

      <div className="border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 text-gray-500">
            <tr>
              <th className="text-left font-medium px-3 py-2 w-40">Time</th>
              <th className="text-left font-medium px-3 py-2">Query</th>
              <th className="text-left font-medium px-3 py-2 w-28">Pipeline</th>
              <th className="text-left font-medium px-3 py-2 w-20">Status</th>
              <th className="text-right font-medium px-3 py-2 w-20">Latency</th>
              <th className="text-left font-medium px-3 py-2 w-24">Difficulty</th>
              <th className="text-left font-medium px-3 py-2 w-56">Suspected</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows?.map((r) => (
              <tr key={r.trace_id} className="hover:bg-gray-50 cursor-pointer" onClick={() => setOpenId(r.trace_id)}>
                <td className="px-3 py-2 text-gray-500 whitespace-nowrap">{fmtTime(r.timestamp)}</td>
                <td className="px-3 py-2 text-gray-800 truncate max-w-0">{r.query_text}</td>
                <td className="px-3 py-2 text-gray-600 font-mono">{r.pipeline_id}</td>
                <td className="px-3 py-2">
                  <span className={r.status === 'OK' ? 'text-green-600' : 'text-rose-600 font-medium'}>{r.status}</span>
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-gray-600">{r.total_latency_ms.toFixed(0)} ms</td>
                <td className="px-3 py-2">
                  {r.predicted_difficulty && (
                    <span className={`px-1.5 py-0.5 rounded border text-[10px] font-medium capitalize ${difficultyChipClass(r.predicted_difficulty)}`}>
                      {r.predicted_difficulty}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1">
                    {r.suspected_failures.map((s) => <SuspectedFailureChip key={s} signal={s} />)}
                  </div>
                </td>
              </tr>
            ))}
            {rows && rows.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-gray-400">No traces match these filters.</td></tr>
            )}
            {!rows && (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-gray-400">Loading traces…</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {openId && <TraceDetail traceId={openId} onClose={() => setOpenId(null)} />}
    </div>
  )
}
