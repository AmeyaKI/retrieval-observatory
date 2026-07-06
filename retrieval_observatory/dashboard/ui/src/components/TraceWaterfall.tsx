import { useMemo } from 'react'
import SectionHeading from './SectionHeading'
import NoData from './NoData'

interface Span {
  op_id: string
  op_type: string
  op_name: string
  status: string
  latency_ms: number
  parent_ids: string[]
}

interface Props {
  spans: Span[]
  onSelectOp?: (opId: string) => void
}

const STATUS_COLORS: Record<string, string> = {
  FIRED: 'bg-blue-400',
  SKIPPED_BY_GATE: 'bg-gray-300',
  ERROR: 'bg-red-400',
  TIMEOUT: 'bg-amber-400',
}

export default function TraceWaterfall({ spans, onSelectOp }: Props) {
  const totalMs = useMemo(
    () => spans.reduce((sum, s) => sum + s.latency_ms, 0),
    [spans],
  )

  if (spans.length === 0) return <NoData label="No spans available for waterfall view." />

  const maxLatency = Math.max(...spans.map((s) => s.latency_ms), 1)

  let cumulativeMs = 0
  const bars = spans.map((span) => {
    const startPct = totalMs > 0 ? (cumulativeMs / totalMs) * 100 : 0
    const widthPct = totalMs > 0 ? (span.latency_ms / totalMs) * 100 : 0
    cumulativeMs += span.latency_ms
    return { ...span, startPct, widthPct }
  })

  return (
    <div>
      <SectionHeading title="Trace waterfall" />
      <div className="border border-gray-200 dark:border-slate-700 rounded bg-white dark:bg-slate-900 p-3">
        <div className="text-[10px] text-gray-400 dark:text-slate-500 mb-2 text-right">
          Total: {totalMs.toFixed(1)}ms
        </div>
        <div className="space-y-1">
          {bars.map((bar) => (
            <div
              key={bar.op_id}
              className="flex items-center gap-2 text-xs cursor-pointer hover:bg-blue-50 rounded px-1 py-0.5"
              onClick={() => onSelectOp?.(bar.op_id)}
            >
              <div className="w-32 truncate font-mono text-[11px]" title={bar.op_id}>
                {bar.op_name}
              </div>
              <div className="flex-1 relative h-5 bg-gray-50 dark:bg-slate-800/60 rounded overflow-hidden">
                <div
                  className={`absolute top-0 h-full rounded ${STATUS_COLORS[bar.status] || 'bg-blue-400'}`}
                  style={{ left: `${bar.startPct}%`, width: `${Math.max(bar.widthPct, 0.5)}%` }}
                  title={`${bar.op_type} · ${bar.latency_ms.toFixed(1)}ms · ${bar.status}`}
                />
              </div>
              <div className="w-16 text-right text-gray-500 dark:text-slate-400 text-[10px]">
                {bar.latency_ms.toFixed(1)}ms
              </div>
              <div className="w-6">
                {bar.status === 'SKIPPED_BY_GATE' && (
                  <span className="text-gray-400 dark:text-slate-500 text-[10px]" title="Skipped by gate">⏭</span>
                )}
                {bar.status === 'ERROR' && (
                  <span className="text-red-500 text-[10px]" title="Error">✕</span>
                )}
                {bar.status === 'TIMEOUT' && (
                  <span className="text-amber-500 text-[10px]" title="Timeout">⏱</span>
                )}
              </div>
            </div>
          ))}
        </div>
        <div className="flex gap-3 text-[10px] text-gray-400 dark:text-slate-500 mt-2 border-t border-gray-100 dark:border-slate-800 pt-1">
          <span><span className="inline-block w-3 h-2 bg-blue-400 rounded mr-1" />Fired</span>
          <span><span className="inline-block w-3 h-2 bg-gray-300 rounded mr-1" />Skipped</span>
          <span><span className="inline-block w-3 h-2 bg-red-400 rounded mr-1" />Error</span>
          <span><span className="inline-block w-3 h-2 bg-amber-400 rounded mr-1" />Timeout</span>
        </div>
      </div>
    </div>
  )
}
