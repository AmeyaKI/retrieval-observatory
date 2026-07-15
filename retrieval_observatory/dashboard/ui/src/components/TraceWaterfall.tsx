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
  FIRED: 'bg-accent',
  SKIPPED_BY_GATE: 'bg-ink-faint/40',
  ERROR: 'bg-status-negative',
  TIMEOUT: 'bg-status-warning',
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
      <div className="border border-hairline rounded bg-surface p-3">
        <div className="text-[10px] text-ink-faint mb-2 text-right">
          Total: {totalMs.toFixed(1)}ms
        </div>
        <div className="space-y-1">
          {bars.map((bar) => (
            <div
              key={bar.op_id}
              className="flex items-center gap-2 text-xs cursor-pointer hover:bg-accent/10 hover:shadow-card rounded px-1 py-0.5 transition-shadow"
              onClick={() => onSelectOp?.(bar.op_id)}
            >
              <div className="w-32 truncate font-mono text-[11px]" title={bar.op_id}>
                {bar.op_name}
              </div>
              <div className="flex-1 relative h-5 bg-surface-muted rounded overflow-hidden">
                <div
                  className={`absolute top-0 h-full rounded ${STATUS_COLORS[bar.status] || 'bg-accent'}`}
                  style={{ left: `${bar.startPct}%`, width: `${Math.max(bar.widthPct, 0.5)}%` }}
                  title={`${bar.op_type} · ${bar.latency_ms.toFixed(1)}ms · ${bar.status}`}
                />
              </div>
              <div className="w-16 text-right text-ink-muted text-[10px]">
                {bar.latency_ms.toFixed(1)}ms
              </div>
              <div className="w-6">
                {bar.status === 'SKIPPED_BY_GATE' && (
                  <span className="text-ink-faint text-[10px]" title="Skipped by gate">⏭</span>
                )}
                {bar.status === 'ERROR' && (
                  <span className="text-status-negative text-[10px]" title="Error">✕</span>
                )}
                {bar.status === 'TIMEOUT' && (
                  <span className="text-status-warning text-[10px]" title="Timeout">⏱</span>
                )}
              </div>
            </div>
          ))}
        </div>
        <div className="flex gap-3 text-[10px] text-ink-faint mt-2 border-t border-hairline pt-1">
          <span><span className="inline-block w-3 h-2 bg-accent rounded mr-1" />Fired</span>
          <span><span className="inline-block w-3 h-2 bg-ink-faint/40 rounded mr-1" />Skipped</span>
          <span><span className="inline-block w-3 h-2 bg-status-negative rounded mr-1" />Error</span>
          <span><span className="inline-block w-3 h-2 bg-status-warning rounded mr-1" />Timeout</span>
        </div>
      </div>
    </div>
  )
}
