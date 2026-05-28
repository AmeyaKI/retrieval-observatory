import { useMemo, useState } from 'react'
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
  isBaseline: boolean
}

function fmt(v: number | null): string {
  return v == null ? '—' : fmtQuality(v)
}

function delta(current: number | null, baseline: number | null): number | null {
  if (current == null || baseline == null) return null
  return current - baseline
}

function DeltaBadge({ d, higherIsBetter = true }: { d: number | null; higherIsBetter?: boolean }) {
  if (d == null) return <span className="text-gray-400 text-xs">—</span>
  const improved = higherIsBetter ? d > 0.0005 : d < -0.0005
  const regressed = higherIsBetter ? d < -0.0005 : d > 0.0005
  const color = improved ? 'text-emerald-600 bg-emerald-50' : regressed ? 'text-red-600 bg-red-50' : 'text-gray-500 bg-gray-100'
  const sign = d > 0 ? '+' : ''
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-mono font-semibold ${color}`}>
      {sign}{fmtQuality(d)}
    </span>
  )
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
        isBaseline: pid.includes('baseline'),
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

  const summaries = [...summaryMap.values()]
  if (summaries.length === 0) return null

  const baseline = summaries.find((s) => s.isBaseline) ?? summaries.sort((a, b) => a.pipelineId.localeCompare(b.pipelineId))[0]
  const comparisons = summaries.filter((s) => s.pipelineId !== baseline.pipelineId)

  const toLabel = (pid: string) =>
    pid.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

  const hasContributions = stageContributions && stageContributions.length > 0

  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-base font-semibold text-gray-800">Pipeline Verdict</h2>
        <MetricTooltip text="Headline metrics for each pipeline's final stage. Δ values compare against the baseline pipeline. Green = improvement, Red = regression." />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 mb-4">
        {/* Baseline card */}
        <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
          <div className="text-[10px] font-bold uppercase tracking-wide text-gray-400 mb-1">Baseline</div>
          <div className="text-sm font-semibold text-gray-800 mb-3 truncate" title={toLabel(baseline.pipelineId)}>
            {toLabel(baseline.pipelineId)}
          </div>
          <div className="space-y-1.5 text-xs">
            <div className="flex justify-between gap-2">
              <span className="text-gray-500">NDCG@10</span>
              <span className="font-mono font-semibold text-gray-800">{fmt(baseline.ndcg10)}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-gray-500">Recall@{baseline.recallBestK ?? 20}</span>
              <span className="font-mono font-semibold text-gray-800">{fmt(baseline.recallBestMean)}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-gray-500">P50 Latency</span>
              <span className="font-mono font-semibold text-gray-800">
                {baseline.latencyP50 != null ? `${fmtLatencyMs(baseline.latencyP50)} ms` : '—'}
              </span>
            </div>
          </div>
        </div>

        {/* Comparison cards */}
        {comparisons.map((s) => {
          const dNdcg = delta(s.ndcg10, baseline.ndcg10)
          const dRecall = delta(s.recallBestMean, baseline.recallBestMean)
          const dLatency = delta(s.latencyP50, baseline.latencyP50)
          return (
            <div key={s.pipelineId} className="border border-indigo-200 rounded-lg p-4 bg-indigo-50">
              <div className="text-[10px] font-bold uppercase tracking-wide text-indigo-400 mb-1">
                vs Baseline · Stage {s.finalStage > 0 ? s.finalStage : 0} final
              </div>
              <div className="text-sm font-semibold text-gray-800 mb-3 truncate" title={toLabel(s.pipelineId)}>
                {toLabel(s.pipelineId)}
              </div>
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between items-center gap-2">
                  <span className="text-gray-500">NDCG@10</span>
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-gray-700">{fmt(s.ndcg10)}</span>
                    <DeltaBadge d={dNdcg} higherIsBetter={true} />
                  </div>
                </div>
                <div className="flex justify-between items-center gap-2">
                  <span className="text-gray-500">Recall@{s.recallBestK ?? 20}</span>
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-gray-700">{fmt(s.recallBestMean)}</span>
                    <DeltaBadge d={dRecall} higherIsBetter={true} />
                  </div>
                </div>
                <div className="flex justify-between items-center gap-2">
                  <span className="text-gray-500">P50 Latency</span>
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-gray-700">
                      {s.latencyP50 != null ? `${fmtLatencyMs(s.latencyP50)} ms` : '—'}
                    </span>
                    <DeltaBadge d={dLatency != null ? dLatency : null} higherIsBetter={false} />
                  </div>
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
