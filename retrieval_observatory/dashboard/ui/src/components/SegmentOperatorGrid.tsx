import { useEffect, useMemo, useState } from 'react'
import { fetchOperatorAttribution, OperatorAttributionRow } from '../api'
import NoData from './NoData'
import SectionHeading from './SectionHeading'

interface Props {
  dbId: string
  runId: string
  onSelectOp?: (opId: string) => void
}

const REPLAY_BADGES: Record<string, { label: string; color: string }> = {
  EXACT: { label: 'E', color: 'bg-green-100 text-green-700' },
  OBSERVED_ABLATION: { label: 'O', color: 'bg-yellow-100 text-yellow-700' },
  NOT_REPLAYABLE: { label: 'N', color: 'bg-red-100 text-red-700' },
}

function CellContent({ row }: { row: OperatorAttributionRow | undefined }) {
  if (!row) return <span className="text-gray-300 dark:text-slate-600">—</span>
  if (row.result_status === 'not_applicable') return <span className="text-gray-400 dark:text-slate-500">—</span>
  if (row.result_status === 'indeterminate') return <span className="text-gray-400 dark:text-slate-500">?</span>
  if (row.delta == null) return <span className="text-gray-400 dark:text-slate-500">—</span>

  const badge = REPLAY_BADGES[row.replay_policy]
  const deltaColor = row.delta > 0 ? 'text-green-700' : row.delta < 0 ? 'text-red-700' : 'text-gray-700 dark:text-slate-200'
  const sigMark = row.significant === true ? '*' : row.significant === false ? '' : ''

  return (
    <div className="flex flex-col items-end gap-0.5">
      <div className="flex items-center gap-1">
        <span className={`font-medium ${deltaColor}`}>
          {row.delta > 0 ? '+' : ''}{row.delta.toFixed(4)}{sigMark}
        </span>
        {badge && (
          <span className={`inline-block px-1 rounded text-[10px] font-mono ${badge.color}`} title={row.replay_policy}>
            {badge.label}
          </span>
        )}
      </div>
      {row.ci_low != null && row.ci_high != null && (
        <span className="text-[10px] text-gray-400 dark:text-slate-500">
          [{row.ci_low.toFixed(3)}, {row.ci_high.toFixed(3)}]
        </span>
      )}
      {row.low_power && row.n_pairs < 20 && (
        <span className="text-[10px] text-amber-500" title={`n=${row.n_pairs} < 20`}>⚠ low-power</span>
      )}
    </div>
  )
}

export default function SegmentOperatorGrid({ dbId, runId, onSelectOp }: Props) {
  const [rows, setRows] = useState<OperatorAttributionRow[]>([])
  const [metric, setMetric] = useState('recall')
  const [k, setK] = useState(10)

  useEffect(() => {
    fetchOperatorAttribution(dbId, runId, metric, k).then(setRows).catch(() => setRows([]))
  }, [dbId, runId, metric, k])

  const segments = useMemo(() => Array.from(new Set(rows.map((r) => r.segment))).sort(), [rows])
  const ops = useMemo(() => Array.from(new Set(rows.map((r) => r.op_id))).sort(), [rows])
  const byKey = useMemo(() => {
    const m = new Map<string, OperatorAttributionRow>()
    for (const r of rows) m.set(`${r.op_id}|${r.segment}`, r)
    return m
  }, [rows])

  if (rows.length === 0) return <NoData label="No operator attribution available for this run." />

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <SectionHeading title="Segment × operator attribution" />
        <div className="flex items-center gap-2 text-xs">
          <select value={metric} onChange={(e) => setMetric(e.target.value)} className="border rounded px-1 py-0.5">
            {['recall', 'ndcg', 'precision', 'mrr', 'map'].map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
          <select value={k} onChange={(e) => setK(Number(e.target.value))} className="border rounded px-1 py-0.5">
            {[5, 10, 20, 50, 100].map((v) => (
              <option key={v} value={v}>@{v}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="overflow-x-auto border border-gray-200 dark:border-slate-700 rounded bg-white dark:bg-slate-900">
        <table className="min-w-full text-xs">
          <thead className="bg-gray-50 dark:bg-slate-800/60">
            <tr>
              <th className="text-left px-3 py-2 sticky left-0 bg-gray-50 dark:bg-slate-800/60 z-10">Operator</th>
              <th className="text-right px-3 py-2">Fire rate</th>
              {segments.map((seg) => (
                <th key={seg} className="text-right px-3 py-2">{seg}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {ops.map((opId) => {
              const firstRow = rows.find((r) => r.op_id === opId)
              return (
                <tr
                  key={opId}
                  className="hover:bg-blue-50 cursor-pointer"
                  onClick={() => onSelectOp?.(opId)}
                >
                  <td className="px-3 py-2 font-mono sticky left-0 bg-white dark:bg-slate-900 z-10">{opId}</td>
                  <td className="px-3 py-2 text-right text-gray-500 dark:text-slate-400">
                    {firstRow?.fire_rate != null ? `${(firstRow.fire_rate * 100).toFixed(0)}%` : '—'}
                  </td>
                  {segments.map((seg) => (
                    <td key={`${opId}:${seg}`} className="px-3 py-2 text-right" title={`n=${byKey.get(`${opId}|${seg}`)?.n_pairs ?? 0}`}>
                      <CellContent row={byKey.get(`${opId}|${seg}`)} />
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="text-[10px] text-gray-400 dark:text-slate-500 mt-1 flex gap-3">
        <span><span className="bg-green-100 text-green-700 px-1 rounded">E</span> = Exact replay</span>
        <span><span className="bg-yellow-100 text-yellow-700 px-1 rounded">O</span> = Observed ablation</span>
        <span><span className="bg-red-100 text-red-700 px-1 rounded">N</span> = Not replayable</span>
        <span>* = significant (BH q &lt; 0.05)</span>
      </div>
    </div>
  )
}
