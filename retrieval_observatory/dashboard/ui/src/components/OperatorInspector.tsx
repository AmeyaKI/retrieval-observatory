import { useEffect, useState } from 'react'
import { fetchOperatorAttribution, OperatorAttributionRow } from '../api'
import NoData from './NoData'
import SectionHeading from './SectionHeading'

interface Props {
  dbId: string
  runId: string
}

export default function OperatorInspector({ dbId, runId }: Props) {
  const [rows, setRows] = useState<OperatorAttributionRow[]>([])
  useEffect(() => {
    fetchOperatorAttribution(dbId, runId).then(setRows).catch(() => setRows([]))
  }, [dbId, runId])

  if (rows.length === 0) return <NoData label="No operator rows to inspect." />

  return (
    <div>
      <SectionHeading title="Operator inspector" />
      <div className="space-y-2">
        {rows.slice(0, 30).map((row) => (
          <div key={`${row.op_id}:${row.segment}`} className="rounded border border-gray-200 bg-white p-2 text-xs">
            <div className="font-mono">{row.op_id}</div>
            <div>segment: {row.segment}</div>
            <div>replay: {row.replay_policy}</div>
            <div>status: {row.result_status}</div>
            <div>delta: {row.delta == null ? '—' : row.delta.toFixed(4)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
