import { useEffect, useMemo, useState } from 'react'
import { CandidateEvent, CandidateFlow, CandidateFlowPipeline } from '../api'
import { OP_ACCENT, OP_LABEL } from '../utils/opTypeColors'
import NoData from './NoData'

type Step =
  | { kind: 'event'; event: CandidateEvent; index: number }
  | { kind: 'terminal'; survived: boolean; final_rank: number | null }

const NODE_W = 140
const NODE_H = 64
const GAP_X = 48
const PAD = 16

function stepsFor(pipeline: CandidateFlowPipeline): Step[] {
  const events = pipeline.history.events.map((event, index) => ({ kind: 'event' as const, event, index }))
  return [
    ...events,
    {
      kind: 'terminal',
      survived: pipeline.history.survived,
      final_rank: pipeline.history.final_rank,
    },
  ]
}

function FlowchartLane({
  pipeline,
  stepIndex,
  onSelectStep,
}: {
  pipeline: CandidateFlowPipeline
  stepIndex: number
  onSelectStep: (index: number) => void
}) {
  const steps = useMemo(() => stepsFor(pipeline), [pipeline])
  const clamped = Math.min(Math.max(stepIndex, 0), Math.max(steps.length - 1, 0))
  const active = steps[clamped]
  const width = PAD * 2 + steps.length * NODE_W + Math.max(0, steps.length - 1) * GAP_X
  const height = PAD * 2 + NODE_H + 28

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 bg-surface p-3 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-sm font-semibold">{pipeline.pipeline_id}</span>
        {pipeline.history.survived ? (
          <span className="rounded px-2 py-0.5 text-xs bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
            survived · rank {pipeline.history.final_rank ?? '—'}
          </span>
        ) : (
          <span className="rounded px-2 py-0.5 text-xs bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300">
            filtered at {pipeline.history.dropped_at ?? '—'} · {pipeline.history.dropped_reason ?? 'unknown'}
          </span>
        )}
      </div>

      <div className="overflow-x-auto">
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          className="block min-w-max"
          role="img"
          aria-label={`Chunk path through ${pipeline.pipeline_id}`}
        >
          <defs>
            <marker id={`flow-arrow-${pipeline.trace_id}`} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <path d="M0,0 L8,4 L0,8 Z" fill="rgb(148 163 184)" />
            </marker>
          </defs>
          {steps.slice(0, -1).map((_, i) => {
            const x1 = PAD + i * (NODE_W + GAP_X) + NODE_W
            const x2 = PAD + (i + 1) * (NODE_W + GAP_X)
            const y = PAD + NODE_H / 2
            const traversed = i < clamped
            return (
              <path
                key={`e-${i}`}
                d={`M ${x1} ${y} L ${x2} ${y}`}
                fill="none"
                stroke={traversed ? 'rgb(79 70 229)' : 'rgb(203 213 225)'}
                strokeWidth={traversed ? 2.5 : 1.5}
                markerEnd={`url(#flow-arrow-${pipeline.trace_id})`}
                className={traversed ? 'transition-all duration-300' : ''}
              />
            )
          })}
          {steps.map((step, i) => {
            const x = PAD + i * (NODE_W + GAP_X)
            const y = PAD
            const isActive = i === clamped
            const isPast = i < clamped
            if (step.kind === 'terminal') {
              const ok = step.survived
              return (
                <g key={`t-${i}`} onClick={() => onSelectStep(i)} className="cursor-pointer">
                  <rect
                    x={x}
                    y={y}
                    width={NODE_W}
                    height={NODE_H}
                    rx={12}
                    fill={ok ? 'rgb(209 250 229)' : 'rgb(254 226 226)'}
                    stroke={isActive ? 'rgb(79 70 229)' : ok ? 'rgb(52 211 153)' : 'rgb(248 113 113)'}
                    strokeWidth={isActive ? 3 : 1.5}
                    className={isActive ? 'transition-all duration-200' : ''}
                    style={isActive ? { filter: 'drop-shadow(0 0 6px rgb(99 102 241 / 0.55))' } : undefined}
                  />
                  <text x={x + NODE_W / 2} y={y + 28} textAnchor="middle" className="fill-ink text-[11px] font-semibold">
                    {ok ? 'Survived' : 'Dropped'}
                  </text>
                  <text x={x + NODE_W / 2} y={y + 46} textAnchor="middle" className="fill-slate-500 text-[10px]">
                    {ok ? `rank ${step.final_rank ?? '—'}` : 'not in final@K'}
                  </text>
                </g>
              )
            }
            const { event } = step
            const accent = OP_ACCENT[event.op_type]
            const dropped = event.event === 'dropped'
            const fill = dropped ? 'rgb(254 226 226)' : accent?.fill ?? 'rgb(241 245 249)'
            const stroke = isActive
              ? 'rgb(79 70 229)'
              : dropped
                ? 'rgb(248 113 113)'
                : isPast
                  ? 'rgb(99 102 241)'
                  : accent?.stroke ?? 'rgb(148 163 184)'
            return (
              <g key={`${event.op_id}-${i}`} onClick={() => onSelectStep(i)} className="cursor-pointer">
                <rect
                  x={x}
                  y={y}
                  width={NODE_W}
                  height={NODE_H}
                  rx={12}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={isActive ? 3 : 1.5}
                  style={
                    isActive
                      ? { filter: 'drop-shadow(0 0 8px rgb(99 102 241 / 0.6))', transformOrigin: 'center' }
                      : undefined
                  }
                />
                <text
                  x={x + 10}
                  y={y + 18}
                  className="text-[9px] font-bold uppercase"
                  fill={accent?.text ?? 'rgb(71 85 105)'}
                >
                  {OP_LABEL[event.op_type] ?? event.op_type}
                </text>
                <text x={x + 10} y={y + 36} className="fill-ink text-[11px] font-semibold">
                  {event.op_name.length > 16 ? `${event.op_name.slice(0, 14)}…` : event.op_name}
                </text>
                <text x={x + 10} y={y + 52} className="fill-slate-500 text-[10px] capitalize">
                  {event.event}
                  {event.output_rank != null ? ` · #${event.output_rank}` : ''}
                </text>
                {isActive && (
                  <circle
                    cx={x + NODE_W - 14}
                    cy={y + 14}
                    r={6}
                    fill="rgb(79 70 229)"
                    className="animate-pulse"
                  />
                )}
              </g>
            )
          })}
        </svg>
      </div>

      {active && (
        <div className="rounded border border-slate-100 dark:border-slate-800 bg-surface-muted px-3 py-2 text-xs text-ink-muted">
          {active.kind === 'terminal' ? (
            active.survived ? (
              <span>
                Chunk remained in the final result set
                {active.final_rank != null ? ` at rank ${active.final_rank}` : ''}.
              </span>
            ) : (
              <span>Chunk did not survive to the final result set for this pipeline.</span>
            )
          ) : (
            <dl className="grid gap-1 sm:grid-cols-2">
              <div>
                <dt className="text-ink-faint">Operator</dt>
                <dd className="font-mono text-ink">
                  {active.event.op_name} · {active.event.op_type}
                </dd>
              </div>
              <div>
                <dt className="text-ink-faint">Event</dt>
                <dd className="capitalize text-ink">{active.event.event}</dd>
              </div>
              <div>
                <dt className="text-ink-faint">Ranks</dt>
                <dd className="font-mono text-ink">
                  in {active.event.input_rank ?? '—'} → out {active.event.output_rank ?? '—'}
                </dd>
              </div>
              <div>
                <dt className="text-ink-faint">Score Δ</dt>
                <dd className="font-mono text-ink">
                  {active.event.score_delta == null
                    ? '—'
                    : `${active.event.score_delta >= 0 ? '+' : ''}${active.event.score_delta.toFixed(4)}`}
                </dd>
              </div>
              {active.event.drop_reason && (
                <div className="sm:col-span-2">
                  <dt className="text-ink-faint">Drop reason</dt>
                  <dd className="text-red-700 dark:text-red-300">
                    {active.event.drop_reason}
                    {active.event.drop_reason_inferred ? ' (inferred from operator type)' : ' (recorded)'}
                  </dd>
                </div>
              )}
              {active.event.note && (
                <div className="sm:col-span-2">
                  <dt className="text-ink-faint">Note</dt>
                  <dd>{active.event.note}</dd>
                </div>
              )}
            </dl>
          )}
        </div>
      )}
    </div>
  )
}

/** Animated per-pipeline flowchart for one document/chunk. */
export default function DocumentPathSimulator({ flow }: { flow: CandidateFlow | null }) {
  const [stepByPipeline, setStepByPipeline] = useState<Record<string, number>>({})
  const [playing, setPlaying] = useState(false)

  useEffect(() => {
    setStepByPipeline({})
    setPlaying(false)
  }, [flow?.doc_id, flow?.query_id])

  useEffect(() => {
    if (!playing || !flow) return
    const id = window.setInterval(() => {
      setStepByPipeline((prev) => {
        const next = { ...prev }
        let advanced = false
        for (const pipeline of flow.pipelines) {
          const max = Math.max(stepsFor(pipeline).length - 1, 0)
          const cur = prev[pipeline.trace_id] ?? 0
          if (cur < max) {
            next[pipeline.trace_id] = cur + 1
            advanced = true
          }
        }
        if (!advanced) setPlaying(false)
        return next
      })
    }, 450)
    return () => window.clearInterval(id)
  }, [playing, flow])

  if (!flow) {
    return <NoData label="Select a chunk in the table below to animate its path through each stage." />
  }
  if (flow.pipelines.length === 0) {
    return <NoData label="No pipeline traces available for this document." />
  }

  const maxSteps = Math.max(...flow.pipelines.map((p) => stepsFor(p).length), 1)

  const bumpAll = (delta: number) => {
    setPlaying(false)
    setStepByPipeline((prev) => {
      const next = { ...prev }
      for (const pipeline of flow.pipelines) {
        const max = Math.max(stepsFor(pipeline).length - 1, 0)
        const cur = prev[pipeline.trace_id] ?? 0
        next[pipeline.trace_id] = Math.min(max, Math.max(0, cur + delta))
      }
      return next
    })
  }

  return (
    <div className="space-y-3" id="candidate-flow-diagram">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            Stage flowchart · <span className="font-mono">{flow.doc_id}</span>
            {flow.relevant ? (
              <span className="ml-2 rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">
                relevant{flow.grade != null ? ` · grade ${flow.grade}` : ''}
              </span>
            ) : (
              <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                not in qrels
              </span>
            )}
          </h3>
          <p className="text-xs text-ink-muted mt-0.5">
            Play animates the chunk through each retrieval stage — where it was introduced, passed, or filtered out.
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            className="rounded border border-slate-200 dark:border-slate-700 px-2 py-1 text-xs hover:border-indigo-300"
            onClick={() => bumpAll(-1)}
          >
            Prev
          </button>
          <button
            type="button"
            className="rounded border border-indigo-300 bg-indigo-50 dark:bg-indigo-950/40 px-2.5 py-1 text-xs font-medium text-indigo-800 dark:text-indigo-200"
            onClick={() => {
              if (playing) {
                setPlaying(false)
                return
              }
              const atEnd = flow.pipelines.every((p) => {
                const max = Math.max(stepsFor(p).length - 1, 0)
                return (stepByPipeline[p.trace_id] ?? 0) >= max
              })
              if (atEnd) {
                setStepByPipeline(Object.fromEntries(flow.pipelines.map((p) => [p.trace_id, 0])))
              }
              setPlaying(true)
            }}
          >
            {playing ? 'Pause' : 'Play'}
          </button>
          <button
            type="button"
            className="rounded border border-slate-200 dark:border-slate-700 px-2 py-1 text-xs hover:border-indigo-300"
            onClick={() => bumpAll(1)}
          >
            Next
          </button>
          <span className="text-[10px] text-ink-faint ml-1">~{maxSteps} steps · 450ms</span>
        </div>
      </div>

      <div className="space-y-3">
        {flow.pipelines.map((pipeline) => (
          <FlowchartLane
            key={pipeline.trace_id}
            pipeline={pipeline}
            stepIndex={stepByPipeline[pipeline.trace_id] ?? 0}
            onSelectStep={(index) => {
              setPlaying(false)
              setStepByPipeline((prev) => ({ ...prev, [pipeline.trace_id]: index }))
            }}
          />
        ))}
      </div>
    </div>
  )
}
