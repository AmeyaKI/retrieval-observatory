import { useEffect, useMemo, useState } from 'react'
import { fetchOperatorAttribution, OperatorAttributionRow } from '../api'
import NoData from './NoData'
import SectionHeading from './SectionHeading'

interface Props {
  dbId: string
  runId: string
}

export default function SegmentOperatorGrid({ dbId, runId }: Props) {
  const [rows, setRows] = useState<OperatorAttributionRow[]>([])
  useEffect(() => {
    fetchOperatorAttribution(dbId, runId).then(setRows).catch(() => setRows([]))
  }, [dbId, runId])

  const segments = useMemo(() => Array.from(new Set(rows.map((row) => row.segment))).sort(), [rows])
  const ops = useMemo(() => Array.from(new Set(rows.map((row) => row.op_id))).sort(), [rows])
  const byKey = useMemo(() => {
    const m = new Map<string, OperatorAttributionRow>()
    for (const row of rows) m.set(`${row.op_id}|${row.segment}`, row)
    return m
  }, [rows])

  if (rows.length === 0) return <NoData label="No operator attribution available for this run." />

  return (
    <div>
      <SectionHeading title="Segment operator attribution" />
      <div className="overflow-x-auto border border-gray-200 rounded bg-white">
        <table className="min-w-full text-xs">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left px-3 py-2">Operator</th>
              {segments.map((segment) => (
                <th key={segment} className="text-right px-3 py-2">{segment}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {ops.map((opId) => (
              <tr key={opId}>
                <td className="px-3 py-2 font-mono">{opId}</td>
                {segments.map((segment) => {
                  const row = byKey.get(`${opId}|${segment}`)
                  const text =
                    !row || row.result_status !== 'measured' || row.delta == null
                      ? row?.result_status ?? 'not_applicable'
                      : row.delta.toFixed(4)
                  return (
                    <td key={`${opId}:${segment}`} className="px-3 py-2 text-right">
                      {text}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
