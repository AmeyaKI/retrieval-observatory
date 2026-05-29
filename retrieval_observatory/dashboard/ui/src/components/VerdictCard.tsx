import { useMemo } from 'react'
import { MetricsMap, StageContribution } from '../api'
import { MetricTooltip } from './MetricTooltip'
import { fmtQuality, fmtLatencyMs } from '../utils/format'

interface Props {
  metrics: MetricsMap
  stageContributions?: StageContribution[]
  latencyBudgetMs: number
  minQualityDelta: number
}

interface PipelineSummary {
  pipelineId: string
  finalStage: number
  ndcg10: number | null
  recall20: number | null
  recallBestK: number | null
  recallBestMean: number | null
  latencyP50: number | null
}

function fmt(v: number | null): string {
  return v == null ? '—' : fmtQuality(v)
}


function StageContributionCard({
  contribution,
  latencyBudgetMs,
  minQualityDelta,
}: {
  contribution: StageContribution
  latencyBudgetMs: number
  minQualityDelta: number
}) {
  const verdict = useMemo(() => {
    const entries = Object.entries(contribution.deltas)
    const qualityEntry = entries.find(([k]) => k.startsWith('recall') || k.startsWith('ndcg'))
    if (!qualityEntry) return null
    const [metricLabel, delta] = qualityEntry
    const qualityMet = delta.absolute >= minQualityDelta && delta.significant
    const latencyOk =
      contribution.latency_delta_ms == null || contribution.latency_delta_ms <= latencyBudgetMs

    if (!delta.significant) {
      return {
        color: 'amber',
        icon: '⚠',
        text: `Quality gain not statistically significant${delta.q_value != null ? ` (q=${delta.q_value.toFixed(3)})` : ''}.`,
      }
    }
    if (qualityMet && latencyOk) {
      return {
        color: 'emerald',
        icon: '✓',
        text: `Stage pays for itself: ${metricLabel} +${fmtQuality(delta.absolute)} (+${delta.pct.toFixed(1)}%) within ${fmtLatencyMs(latencyBudgetMs)}ms budget.`,
      }
    }
    if (qualityMet && !latencyOk) {
      const over = contribution.latency_delta_ms! - latencyBudgetMs
      return {
        color: 'amber',
        icon: '⚠',
        text: `Significant gain (+${fmtQuality(delta.absolute)} ${metricLabel}), but exceeds latency budget by ${fmtLatencyMs(over)}ms. Consider GPU or smaller model.`,
      }
    }
    return {
      color: 'gray',
      icon: '○',
      text: `${metricLabel} delta (${fmtQuality(delta.absolute)}) below minimum threshold of ${minQualityDelta.toFixed(2)}.`,
    }
  }, [contribution, latencyBudgetMs, minQualityDelta])

  const colorMap: Record<string, string> = {
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    gray: 'border-gray-200 bg-gray-50 text-gray-600',
  }

  return (
    <div className="border border-gray-200 rounded-lg p-4 bg-white">
      <div className="text-[10px] font-bold uppercase tracking-wide text-indigo-400 mb-1">
        {contribution.from_pipeline} → {contribution.to_pipeline}
      </div>
      {verdict && (
        <div className={`text-xs rounded px-2 py-1.5 mb-3 border ${colorMap[verdict.color]}`}>
          <span className="font-bold mr-1">{verdict.icon}</span>
          {verdict.text}
        </div>
      )}
      <div className="space-y-1 text-xs">
        {Object.entries(contribution.deltas).map(([label, d]) => (
          <div key={label} className="flex justify-between items-center gap-2">
            <span className="text-gray-500">{label}</span>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-gray-700">{fmtQuality(d.before)} → {fmtQuality(d.after)}</span>
              <span className={`font-mono text-xs font-semibold ${d.absolute > 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                {d.absolute >= 0 ? '+' : ''}{fmtQuality(d.absolute)}
              </span>
              {d.q_value != null && (
                <span className={`text-[10px] px-1 rounded ${d.significant ? 'text-emerald-700 bg-emerald-50' : 'text-gray-400 bg-gray-100'}`}>
                  q={d.q_value.toFixed(3)}{d.significant ? ' ✓' : ''}
                </span>
              )}
            </div>
          </div>
        ))}
        {contribution.latency_delta_ms != null && (
          <div className="flex justify-between items-center gap-2 pt-1 mt-1 border-t border-gray-100">
            <span className="text-gray-500">Latency P50</span>
            <span className={`font-mono text-xs font-semibold ${contribution.latency_delta_ms > latencyBudgetMs ? 'text-red-600' : 'text-emerald-600'}`}>
              {contribution.latency_delta_ms >= 0 ? '+' : ''}{fmtLatencyMs(contribution.latency_delta_ms)}ms
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

export default function VerdictCard({ metrics, stageContributions, latencyBudgetMs, minQualityDelta }: Props) {
  // Build per-pipeline summary from the last stage (highest stage_index)
  const summaryMap = new Map<string, PipelineSummary>()

  for (const [, entry] of Object.entries(metrics)) {
    if (entry.stage_index < 0) continue
    const pid = entry.pipeline_id
    if (!summaryMap.has(pid)) {
      summaryMap.set(pid, {
        pipelineId: pid,
        finalStage: 0,
        ndcg10: null,
        recall20: null,
        recallBestK: null,
        recallBestMean: null,
        latencyP50: null,
      })
    }
    const s = summaryMap.get(pid)!
    if (entry.stage_index > s.finalStage) s.finalStage = entry.stage_index
  }

  for (const [, entry] of Object.entries(metrics)) {
    if (entry.stage_index < 0) continue
    const s = summaryMap.get(entry.pipeline_id)
    if (!s || entry.stage_index !== s.finalStage) continue

    if (entry.metric_name === 'ndcg' && entry.k === 10) s.ndcg10 = entry.mean
    if (entry.metric_name === 'recall' && entry.k === 20) s.recall20 = entry.mean
    if (entry.metric_name === 'recall') {
      if (s.recallBestK == null || entry.k > s.recallBestK) {
        s.recallBestK = entry.k
        s.recallBestMean = entry.mean
      }
    }
    if (entry.metric_name === 'latency_p50') s.latencyP50 = entry.mean
  }

  // Rank pipelines: best NDCG@10 first, tie-break on best recall
  const ranked = [...summaryMap.values()].sort(
    (a, b) => (b.ndcg10 ?? -1) - (a.ndcg10 ?? -1) || (b.recallBestMean ?? -1) - (a.recallBestMean ?? -1)
  )

  if (ranked.length === 0) return null

  const toLabel = (pid: string) =>
    pid.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

  const rankLabel = (i: number) => (['Best', '2nd', '3rd'][i] ?? `${i + 1}th`)

  const rankColors = [
    { border: 'border-emerald-400', bg: 'bg-emerald-50', badge: 'text-amber-600 bg-amber-50 border-amber-200', label: 'text-emerald-600' },
    { border: 'border-slate-400', bg: 'bg-slate-50', badge: 'text-slate-500 bg-slate-100 border-slate-200', label: 'text-slate-500' },
    { border: 'border-amber-400', bg: 'bg-amber-50', badge: 'text-amber-700 bg-amber-100 border-amber-200', label: 'text-amber-600' },
  ]
  const defaultColor = { border: 'border-gray-200', bg: 'bg-gray-50', badge: 'text-gray-500 bg-gray-100 border-gray-200', label: 'text-gray-400' }

  const hasContributions = stageContributions && stageContributions.length > 0

  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-base font-semibold text-gray-800">Pipeline Verdict</h2>
        <MetricTooltip text="Pipelines ranked left-to-right by NDCG@10 (best at far left). Metrics shown are from each pipeline's final stage." />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 mb-4">
        {ranked.map((s, i) => {
          const color = rankColors[i] ?? defaultColor
          return (
            <div key={s.pipelineId} className={`border-2 ${color.border} ${color.bg} rounded-lg p-4`}>
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded border ${color.badge}`}>
                  {rankLabel(i)}
                </span>
                <span className="text-[10px] text-gray-400 uppercase tracking-wide">
                  {s.finalStage > 0 ? `${s.finalStage + 1}-stage` : '1-stage'}
                </span>
              </div>
              <div className="text-sm font-semibold text-gray-800 mb-3 truncate" title={toLabel(s.pipelineId)}>
                {toLabel(s.pipelineId)}
              </div>
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between gap-2">
                  <span className="text-gray-500">NDCG@10</span>
                  <span className={`font-mono font-semibold ${color.label}`}>{fmt(s.ndcg10)}</span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-gray-500">Recall@{s.recallBestK ?? 20}</span>
                  <span className={`font-mono font-semibold ${color.label}`}>{fmt(s.recallBestMean)}</span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-gray-500">P50 Latency</span>
                  <span className="font-mono font-semibold text-gray-700">
                    {s.latencyP50 != null ? `${fmtLatencyMs(s.latencyP50)} ms` : '—'}
                  </span>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {hasContributions && (
        <div>
          <div className="text-sm font-semibold text-gray-700 mb-2">Stage Attribution</div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {stageContributions!.map((c) => (
              <StageContributionCard
                key={`${c.from_pipeline}→${c.to_pipeline}`}
                contribution={c}
                latencyBudgetMs={latencyBudgetMs}
                minQualityDelta={minQualityDelta}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
