import { useEffect, useMemo, useState } from 'react'
import { fetchOperatorAttribution, fetchOperatorDag, OperatorAttributionRow, OperatorDagNode } from '../api'
import NoData from './NoData'
import SectionHeading from './SectionHeading'

const REPLAY_COLORS: Record<string, string> = {
  EXACT: 'bg-green-100 text-green-800 border-green-200',
  OBSERVED_ABLATION: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  NOT_REPLAYABLE: 'bg-red-100 text-red-800 border-red-200',
}

interface Props {
  dbId: string
  runId: string
  selectedOpId?: string | null
}

export default function OperatorInspector({ dbId, runId, selectedOpId }: Props) {
  const [rows, setRows] = useState<OperatorAttributionRow[]>([])
  const [dagNodes, setDagNodes] = useState<OperatorDagNode[]>([])

  useEffect(() => {
    fetchOperatorAttribution(dbId, runId).then(setRows).catch(() => setRows([]))
    fetchOperatorDag(dbId, runId).then((dag) => setDagNodes(dag.nodes)).catch(() => setDagNodes([]))
  }, [dbId, runId])

  const opIds = useMemo(() => {
    const ids = Array.from(new Set(rows.map((r) => r.op_id))).sort()
    if (selectedOpId && ids.includes(selectedOpId)) {
      return [selectedOpId, ...ids.filter((id) => id !== selectedOpId)]
    }
    return ids
  }, [rows, selectedOpId])

  const rowsByOp = useMemo(() => {
    const m = new Map<string, OperatorAttributionRow[]>()
    for (const r of rows) m.set(r.op_id, [...(m.get(r.op_id) || []), r])
    return m
  }, [rows])

  const dagByOp = useMemo(() => {
    const m = new Map<string, OperatorDagNode>()
    for (const n of dagNodes) m.set(n.op_id, n)
    return m
  }, [dagNodes])

  if (rows.length === 0) return <NoData label="No operator rows to inspect." />

  return (
    <div>
      <SectionHeading title="Operator inspector" />
      <div className="space-y-3">
        {opIds.map((opId) => {
          const opRows = rowsByOp.get(opId) || []
          const dagNode = dagByOp.get(opId)
          const firstRow = opRows[0]
          if (!firstRow) return null
          const isSelected = opId === selectedOpId
          const replayColor = REPLAY_COLORS[firstRow.replay_policy] || 'bg-gray-100 dark:bg-slate-800'

          return (
            <div
              key={opId}
              className={`rounded border p-3 text-xs ${isSelected ? 'border-blue-400 bg-blue-50 ring-1 ring-blue-200' : 'border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900'}`}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono font-semibold text-sm">{opId}</span>
                  {dagNode && (
                    <span className="text-gray-400 dark:text-slate-500 text-[10px]">{dagNode.op_type}</span>
                  )}
                </div>
                <span className={`px-2 py-0.5 rounded border text-[10px] font-medium ${replayColor}`}>
                  {firstRow.replay_policy}
                </span>
              </div>

              <div className="grid grid-cols-3 gap-3 mb-2">
                <div>
                  <div className="text-gray-500 dark:text-slate-400 mb-0.5">Fire rate</div>
                  <div className="font-medium">
                    {firstRow.fire_rate != null ? `${(firstRow.fire_rate * 100).toFixed(1)}%` : '—'}
                  </div>
                </div>
                <div>
                  <div className="text-gray-500 dark:text-slate-400 mb-0.5">Avg latency</div>
                  <div className="font-medium">
                    {dagNode?.avg_latency_ms != null ? `${dagNode.avg_latency_ms.toFixed(1)}ms` : '—'}
                  </div>
                </div>
                <div>
                  <div className="text-gray-500 dark:text-slate-400 mb-0.5">Result</div>
                  <div className="font-medium">{firstRow.result_status}</div>
                </div>
              </div>

              <div className="border-t border-gray-100 dark:border-slate-800 pt-2">
                <div className="text-gray-500 dark:text-slate-400 mb-1 font-medium">Attribution by segment</div>
                <div className="grid gap-1">
                  {opRows.map((row) => (
                    <div key={`${row.op_id}:${row.segment}`} className="flex items-center justify-between">
                      <span className="text-gray-600 dark:text-slate-300">{row.segment}</span>
                      <div className="flex items-center gap-2">
                        <span className={row.delta != null && row.delta > 0 ? 'text-green-700' : row.delta != null && row.delta < 0 ? 'text-red-700' : 'text-gray-500 dark:text-slate-400'}>
                          {row.delta == null ? '—' : `${row.delta > 0 ? '+' : ''}${row.delta.toFixed(4)}`}
                        </span>
                        {row.ci_low != null && row.ci_high != null && (
                          <span className="text-gray-400 dark:text-slate-500 text-[10px]">
                            [{row.ci_low.toFixed(3)}, {row.ci_high.toFixed(3)}]
                          </span>
                        )}
                        {row.significant === true && (
                          <span className="text-green-600 text-[10px]">sig</span>
                        )}
                        <span className="text-gray-400 dark:text-slate-500 text-[10px]">n={row.n_pairs}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
