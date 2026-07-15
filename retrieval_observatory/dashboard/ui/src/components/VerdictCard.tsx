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
  ndcg10CiLow: number | null
  ndcg10CiHigh: number | null
  recall20: number | null
  recallBestK: number | null
  recallBestMean: number | null
  latencyP50: number | null
}

function ciClearsRunnerUp(leader: PipelineSummary, runner: PipelineSummary): boolean {
  if (leader.ndcg10 == null || runner.ndcg10 == null) return false
  if (leader.ndcg10CiLow == null || runner.ndcg10CiHigh == null) return leader.ndcg10 > runner.ndcg10
  return leader.ndcg10CiLow > runner.ndcg10CiHigh
}

function fmt(v: number | null): string {
  return v == null ? '—' : fmtQuality(v)
}

/** Pipelines that are not part of any __-prefix ablation pair. */
function getIndependentPipelineIds(pipelineIds: string[]): string[] {
  const idSet = new Set(pipelineIds)
  const inPair = new Set<string>()
  for (const pid of pipelineIds) {
    const parts = pid.split('__')
    if (parts.length > 1) {
      const prefix = parts.slice(0, -1).join('__')
      if (idSet.has(prefix)) {
        inPair.add(pid)
        inPair.add(prefix)
      }
    }
  }
  return pipelineIds.filter((id) => !inPair.has(id))
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
    if (delta.indeterminate) {
      return {
        color: 'slate',
        icon: '◌',
        text: `Insufficient data: fused-stage ${metricLabel} had no quality signal for this query set, so arm-vs-fused delta is indeterminate.`,
      }
    }
    const qualityMet = delta.absolute >= minQualityDelta && delta.significant
    const latencyOk =
      contribution.latency_delta_ms == null || contribution.latency_delta_ms <= latencyBudgetMs

    const lowPower = delta.n_pairs != null && delta.n_pairs < 20
    if (!delta.significant) {
      const nNote = lowPower ? ` Low statistical power: only ${delta.n_pairs} shared queries.` : ''
      return {
        color: 'amber',
        icon: '⚠',
        text: `Quality gain not statistically significant${delta.q_value != null ? ` (q=${delta.q_value.toFixed(3)})` : ''}.${nNote}`,
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
    emerald: 'border-status-positive/30 bg-status-positive/10 text-status-positive',
    amber: 'border-status-warning/30 bg-status-warning/10 text-status-warning',
    gray: 'border-hairline bg-surface-muted text-ink-muted',
    slate: 'border-status-neutral/30 bg-status-neutral/10 text-status-neutral',
  }

  return (
    <div className="border border-hairline rounded-lg p-4 bg-surface">
      <div className="text-[10px] font-bold uppercase tracking-wide text-accent mb-1">
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
            <span className="text-ink-muted">{label}</span>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-ink">{fmtQuality(d.before)} → {fmtQuality(d.after)}</span>
              <span className={`font-mono text-xs font-semibold ${d.absolute > 0 ? 'text-status-positive' : 'text-status-negative'}`}>
                {d.absolute >= 0 ? '+' : ''}{fmtQuality(d.absolute)}
              </span>
              {d.indeterminate && (
                <span className="text-[10px] px-1 rounded text-status-neutral bg-status-neutral/10">
                  insufficient data
                </span>
              )}
              {d.q_value != null && (
                <span className={`text-[10px] px-1 rounded ${d.significant ? 'text-status-positive bg-status-positive/10' : 'text-ink-faint bg-surface-muted'}`}>
                  q={d.q_value.toFixed(3)}{d.significant ? ' ✓' : ''}
                </span>
              )}
              {d.n_pairs != null && d.n_pairs < 20 && (
                <span className="text-[10px] px-1 rounded text-status-warning bg-status-warning/10" title="Low statistical power: fewer than 20 shared queries">
                  n={d.n_pairs}
                </span>
              )}
            </div>
          </div>
        ))}
        {contribution.latency_delta_ms != null && (
          <div className="flex justify-between items-center gap-2 pt-1 mt-1 border-t border-hairline">
            <span className="text-ink-muted">Latency P50</span>
            <span className={`font-mono text-xs font-semibold ${contribution.latency_delta_ms > latencyBudgetMs ? 'text-status-negative' : 'text-status-positive'}`}>
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
    const pid = entry.pipeline_id
    if (entry.stage_index < 0) {
      if (entry.metric_name === 'latency_p50') {
        if (!summaryMap.has(pid)) {
          summaryMap.set(pid, {
            pipelineId: pid,
            finalStage: 0,
            ndcg10: null,
            ndcg10CiLow: null,
            ndcg10CiHigh: null,
            recall20: null,
            recallBestK: null,
            recallBestMean: null,
            latencyP50: null,
          })
        }
        summaryMap.get(pid)!.latencyP50 = entry.mean
      }
      continue
    }
    if (!summaryMap.has(pid)) {
      summaryMap.set(pid, {
        pipelineId: pid,
        finalStage: 0,
        ndcg10: null,
        ndcg10CiLow: null,
        ndcg10CiHigh: null,
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

    if (entry.metric_name === 'ndcg' && entry.k === 10) {
      s.ndcg10 = entry.mean
      s.ndcg10CiLow = entry.ci_low
      s.ndcg10CiHigh = entry.ci_high
    }
    if (entry.metric_name === 'recall' && entry.k === 20) s.recall20 = entry.mean
    if (entry.metric_name === 'recall') {
      if (s.recallBestK == null || entry.k > s.recallBestK) {
        s.recallBestK = entry.k
        s.recallBestMean = entry.mean
      }
    }
    if (entry.metric_name === 'latency_p50' && s.latencyP50 == null) s.latencyP50 = entry.mean
  }

  // Rank pipelines: best NDCG@10 first, tie-break on best recall
  const ranked = [...summaryMap.values()].sort(
    (a, b) => (b.ndcg10 ?? -1) - (a.ndcg10 ?? -1) || (b.recallBestMean ?? -1) - (a.recallBestMean ?? -1)
  )

  if (ranked.length === 0) return null

  const toLabel = (pid: string) =>
    pid.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

  const rankLabel = (i: number) => {
    if (i === 0 && ranked.length > 1) {
      const runner = ranked[1]
      const leader = ranked[0]
      if (ciClearsRunnerUp(leader, runner)) return 'Best (significant)'
      return 'Best (within CI of 2nd)'
    }
    return (['Best', '2nd', '3rd'][i] ?? `${i + 1}th`)
  }

  const rankColors = [
    { border: 'border-status-positive/60', bg: 'bg-status-positive/10', badge: 'text-status-warning bg-status-warning/10 border-status-warning/30', label: 'text-status-positive' },
    { border: 'border-status-neutral/60', bg: 'bg-status-neutral/10', badge: 'text-status-neutral bg-status-neutral/10 border-status-neutral/30', label: 'text-status-neutral' },
    { border: 'border-status-warning/60', bg: 'bg-status-warning/10', badge: 'text-status-warning bg-status-warning/20 border-status-warning/30', label: 'text-status-warning' },
  ]
  const defaultColor = { border: 'border-hairline', bg: 'bg-surface-muted', badge: 'text-ink-muted bg-surface-muted border-hairline', label: 'text-ink-faint' }

  const hasContributions = stageContributions && stageContributions.length > 0
  const crossPrefix = (stageContributions ?? []).filter((c) => c.comparison_tier === 'cross_pipeline_prefix')
  const withinPipeline = (stageContributions ?? []).filter((c) => c.comparison_tier === 'within_pipeline_stage')
  const armAblations = (stageContributions ?? []).filter((c) => c.comparison_tier === 'within_stage_arm')
  const pipelineIds = ranked.map((s) => s.pipelineId)
  const independentIds = getIndependentPipelineIds(pipelineIds)
  const hasIndependentPipelines = independentIds.length > 0 && pipelineIds.length > independentIds.length + (hasContributions ? 1 : 0)

  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-base font-semibold text-ink">Pipeline Verdict</h2>
        <MetricTooltip text="Pipelines ranked by NDCG@10 (final stage). Latency is end-to-end P50 (stage_index=-1). Medals use CI overlap, not raw means alone." />
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
                <span className="text-[10px] text-ink-faint uppercase tracking-wide">
                  {s.finalStage > 0 ? `${s.finalStage + 1}-stage` : '1-stage'}
                </span>
              </div>
              <div className="text-sm font-semibold text-ink mb-3 truncate" title={toLabel(s.pipelineId)}>
                {toLabel(s.pipelineId)}
              </div>
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between gap-2">
                  <span className="text-ink-muted">NDCG@10</span>
                  <span className={`font-mono font-semibold text-right ${color.label}`}>
                    {fmt(s.ndcg10)}
                    {s.ndcg10CiLow != null && s.ndcg10CiHigh != null && (
                      <span className="block text-[9px] text-ink-faint font-normal">
                        [{fmt(s.ndcg10CiLow)}, {fmt(s.ndcg10CiHigh)}]
                      </span>
                    )}
                  </span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-ink-muted">Recall@{s.recallBestK ?? 20}</span>
                  <span className={`font-mono font-semibold ${color.label}`}>{fmt(s.recallBestMean)}</span>
                </div>
                <div className="flex justify-between gap-2">
                  <span className="text-ink-muted">E2E P50 Latency</span>
                  <span className="font-mono font-semibold text-ink">
                    {s.latencyP50 != null ? `${fmtLatencyMs(s.latencyP50)} ms` : '—'}
                  </span>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {hasContributions ? (
        <div>
          <div className="text-sm font-semibold text-ink-muted mb-2">Stage Ablation Attribution</div>
          <p className="text-xs text-ink-muted bg-surface-muted border border-hairline rounded px-3 py-2 mb-3">
            Decision rule: a stage <strong>pays for itself</strong> when the quality gain is statistically significant and at least {minQualityDelta.toFixed(2)}, while staying within the latency budget ({fmtLatencyMs(latencyBudgetMs)}ms P50).
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3 text-xs">
            <div className="rounded border border-status-positive/30 bg-status-positive/10 px-2 py-1 text-status-positive">✓ Significant gain and within latency budget.</div>
            <div className="rounded border border-status-warning/30 bg-status-warning/10 px-2 py-1 text-status-warning">⚠ Gain exists but is not significant.</div>
            <div className="rounded border border-status-warning/30 bg-status-warning/10 px-2 py-1 text-status-warning">⚠ Significant gain but over latency budget.</div>
            <div className="rounded border border-hairline bg-surface-muted px-2 py-1 text-ink-muted">○ Significant/insignificant gain below quality threshold.</div>
            <div className="rounded border border-status-neutral/30 bg-status-neutral/10 px-2 py-1 text-status-neutral sm:col-span-2">◌ Neutral: insufficient fused-stage signal for arm-vs-fused comparison.</div>
          </div>
          {hasIndependentPipelines && crossPrefix.length > 0 && (
            <p className="text-xs text-accent bg-accent/10 border border-accent/30 rounded px-3 py-2 mb-3">
              Cross-pipeline prefix comparisons are shown separately from in-pipeline stage adds and hybrid arm contributions.
              {independentIds.length > 0 && (
                <> Independent pipelines ({independentIds.join(', ')}) are compared in Pipeline Verdict above.</>
              )}
            </p>
          )}
          {crossPrefix.length > 0 && (
            <>
              <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Does each added stage earn its cost? (prefix pipelines)</div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 mb-3">
                {crossPrefix.map((c) => (
                  <StageContributionCard
                    key={`${c.from_pipeline}→${c.to_pipeline}`}
                    contribution={c}
                    latencyBudgetMs={latencyBudgetMs}
                    minQualityDelta={minQualityDelta}
                  />
                ))}
              </div>
            </>
          )}
          {withinPipeline.length > 0 && (
            <>
              <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Does each added stage earn its cost? (within one pipeline)</div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 mb-3">
                {withinPipeline.map((c) => (
                  <StageContributionCard
                    key={`${c.from_pipeline}→${c.to_pipeline}`}
                    contribution={c}
                    latencyBudgetMs={latencyBudgetMs}
                    minQualityDelta={minQualityDelta}
                  />
                ))}
              </div>
            </>
          )}
          {armAblations.length > 0 && (
            <>
              <div className="text-xs font-semibold text-ink-muted uppercase tracking-wide mb-2">Which retriever arm is carrying the hybrid?</div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {armAblations.map((c) => (
                  <StageContributionCard
                    key={`${c.from_pipeline}→${c.to_pipeline}`}
                    contribution={c}
                    latencyBudgetMs={latencyBudgetMs}
                    minQualityDelta={minQualityDelta}
                  />
                ))}
              </div>
            </>
          )}
          {crossPrefix.length === 0 && withinPipeline.length === 0 && armAblations.length === 0 && (
            <p className="text-xs text-ink-muted bg-surface-muted border border-hairline rounded px-3 py-2">
              No ablation deltas were available for this run.
            </p>
          )}
        </div>
      ) : ranked.length >= 2 ? (
        <p className="text-xs text-ink-muted bg-surface-muted border border-hairline rounded px-3 py-2">
          Stage ablation attribution is not available for this run — pipelines are independent variants
          (not prefix chains like bm25 → bm25__rerank). Compare quality and latency in the cards above.
        </p>
      ) : null}
    </div>
  )
}
