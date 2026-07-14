import { useEffect, useState } from 'react'
import { fetchTraceHotspots, FailureHotspot } from '../../api'
import { difficultyChipClass } from '../../utils/difficulty'
import SuspectedFailureChip from './SuspectedFailureChip'
import TraceDetail from './TraceDetail'

export default function Hotspots({ dbId, service, since }: { dbId: string; service: string; since?: string }) {
  const [hotspots, setHotspots] = useState<FailureHotspot[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openTraceId, setOpenTraceId] = useState<string | null>(null)

  useEffect(() => {
    setHotspots(null)
    fetchTraceHotspots(dbId, service, since).then(setHotspots).catch((e) => setError(e.message))
  }, [dbId, service, since])

  if (error) return <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>
  if (!hotspots) return <div className="text-sm text-gray-400 dark:text-slate-500">Finding hotspots…</div>
  if (hotspots.length === 0) return <p className="text-sm text-gray-400 dark:text-slate-500">No suspected-failure segments in this window.</p>

  return (
    <div>
      <p className="text-xs text-gray-500 dark:text-slate-400 mb-3">
        Traffic segments accumulating <strong>suspected</strong> (label-free) failure signals, grouped by
        difficulty × signal × pipeline. Rate = segment count / total traces in that difficulty bucket
        for the selected window (share-of-difficulty traffic, not within-segment failure rate). These point at where
        to look, not a measured Recall.
      </p>
      <div className="space-y-2">
        {hotspots.map((h, i) => (
          <div key={i} className="rounded-lg border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 flex-wrap">
              <span className={`px-1.5 py-0.5 rounded border text-[10px] font-medium capitalize ${difficultyChipClass(h.difficulty)}`}>{h.difficulty}</span>
              <SuspectedFailureChip signal={h.label} />
              <span className="text-xs font-mono text-gray-600 dark:text-slate-300">{h.pipeline}</span>
              </div>
              <div className="text-right">
              <p className="text-sm font-bold text-gray-900 dark:text-slate-100 tabular-nums">{h.count}</p>
              <p className="text-[10px] text-gray-400 dark:text-slate-500">{(h.rate * 100).toFixed(1)}% share of {h.difficulty} traffic</p>
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-ink-faint">
              <span>evidence: {h.evidence_class}</span><span>method: {h.method}</span><span>sample n={h.sample_size}</span><span>denominator n={h.denominator}</span><span>baseline: {h.baseline}</span><span>threshold: none (ranked finding)</span>
              {h.supporting_trace_ids[0] && <button type="button" onClick={() => setOpenTraceId(h.supporting_trace_ids[0])} className="ml-auto rounded border px-2 py-1 text-indigo-700 dark:text-indigo-300">Open supporting trace →</button>}
            </div>
          </div>
        ))}
      </div>
      {/* Closed-loop CTA — prod failure → synthetic reproduction (see plan §1.5) */}
      <div className="mt-4 rounded-lg border border-dashed border-amber-300 bg-amber-50/60 p-3 text-xs text-amber-800">
        <span className="mr-1">🜂</span>
        Reproduce a hotspot as a stress dataset: run
        <code className="mx-1 px-1 rounded bg-white dark:bg-slate-900 border border-amber-200">retobs forge run --corpus your_corpus.jsonl --scenario-types temporal,alias</code>
        then evaluate — the per-scenario breakdown shows up in Runs.
      </div>
      {openTraceId && <TraceDetail dbId={dbId} traceId={openTraceId} onClose={() => setOpenTraceId(null)} />}
    </div>
  )
}
