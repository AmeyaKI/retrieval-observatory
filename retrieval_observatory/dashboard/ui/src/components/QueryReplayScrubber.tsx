import { useMemo, useState } from 'react'
import { TraceOperatorSpan } from '../api'
import { buildReplaySteps, diffStep, stepOutputs } from '../utils/traceSteps'
import { OP_ACCENT } from '../utils/opTypeColors'

const DIFF_STYLE: Record<string, string> = {
  appeared: 'text-emerald-700 dark:text-emerald-400',
  disappeared: 'text-red-600 dark:text-red-400 line-through',
  rank_changed: 'text-amber-700 dark:text-amber-400',
  unchanged: 'text-ink-faint',
}

const DIFF_ICON: Record<string, string> = {
  appeared: '+',
  disappeared: '−',
  rank_changed: '↕',
  unchanged: '·',
}

// Query Replay (C.3): step forward/back through a trace's operators grouped by dependency
// depth, so a fusion pipeline's parallel arms appear at the same step instead of being
// serialized by array order (buildReplaySteps handles the leveling).
export default function QueryReplayScrubber({ spans }: { spans: TraceOperatorSpan[] }) {
  const steps = useMemo(() => buildReplaySteps(spans), [spans])
  const [stepIdx, setStepIdx] = useState(0)

  if (steps.length === 0) return null

  const clamped = Math.min(stepIdx, steps.length - 1)
  const prevOutputs = clamped > 0 ? stepOutputs(steps[clamped - 1]) : new Map<string, number>()
  const currOutputs = stepOutputs(steps[clamped])
  const diff = diffStep(prevOutputs, currOutputs)

  return (
    <div className="border border-gray-100 dark:border-slate-800 rounded p-3">
      <div className="flex items-center gap-2 mb-2">
        <button
          type="button"
          onClick={() => setStepIdx((i) => Math.max(0, i - 1))}
          disabled={clamped === 0}
          className="px-2 py-0.5 text-xs rounded border border-gray-200 dark:border-slate-700 disabled:opacity-40"
        >
          ← Prev
        </button>
        <span className="text-xs text-ink-muted">
          Step {clamped + 1} / {steps.length}
        </span>
        <button
          type="button"
          onClick={() => setStepIdx((i) => Math.min(steps.length - 1, i + 1))}
          disabled={clamped === steps.length - 1}
          className="px-2 py-0.5 text-xs rounded border border-gray-200 dark:border-slate-700 disabled:opacity-40"
        >
          Next →
        </button>
        <div className="ml-2 flex flex-wrap gap-1">
          {steps[clamped].spans.map((s) => {
            const accent = OP_ACCENT[s.op_type] ?? OP_ACCENT.TRANSFORM
            return (
              <span
                key={s.op_id}
                className="text-[10px] px-1.5 py-0.5 rounded border font-mono"
                style={{ background: accent.fill, borderColor: accent.stroke, color: accent.text }}
                title={s.op_id}
              >
                {s.op_name}
              </span>
            )
          })}
        </div>
      </div>
      <table className="w-full text-[11px]">
        <thead>
          <tr className="text-ink-faint text-left">
            <th className="font-normal pr-2 w-4"></th>
            <th className="font-normal pr-2">Doc ID</th>
            <th className="font-normal pr-2">Rank</th>
            <th className="font-normal">Prev rank</th>
          </tr>
        </thead>
        <tbody>
          {diff.slice(0, 15).map((d) => (
            <tr key={d.doc_id} className={DIFF_STYLE[d.status]}>
              <td className="pr-2">{DIFF_ICON[d.status]}</td>
              <td className="pr-2 font-mono truncate max-w-[14rem]">{d.doc_id}</td>
              <td className="pr-2 font-mono">{d.rank ?? '—'}</td>
              <td className="font-mono">{d.prevRank ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {diff.length === 0 && <div className="text-xs text-ink-faint">No candidates at this step.</div>}
    </div>
  )
}
