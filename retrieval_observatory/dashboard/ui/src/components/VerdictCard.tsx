import { MetricsMap } from '../api'
import { MetricTooltip } from './MetricTooltip'

interface Props {
  metrics: MetricsMap
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

function fmt(v: number | null, decimals = 4): string {
  return v == null ? '—' : v.toFixed(decimals)
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
      {sign}{d.toFixed(4)}
    </span>
  )
}

export default function VerdictCard({ metrics }: Props) {
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

    // Track highest stage seen
    if (entry.stage_index > s.finalStage) s.finalStage = entry.stage_index

    // Only populate metrics from the highest stage (final output)
    // We'll do a second pass after collecting all entries
  }

  // Second pass — populate metrics only from the final stage of each pipeline
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

  // Identify baseline: prefer pipeline with "baseline" in the name, else first pipeline alphabetically
  const baseline = summaries.find((s) => s.isBaseline) ?? summaries.sort((a, b) => a.pipelineId.localeCompare(b.pipelineId))[0]
  const comparisons = summaries.filter((s) => s.pipelineId !== baseline.pipelineId)

  const toLabel = (pid: string) =>
    pid.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-base font-semibold text-gray-800">Pipeline Verdict</h2>
        <MetricTooltip text="Headline metrics for each pipeline's final stage. Δ values compare against the baseline pipeline. Green = improvement, Red = regression." />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
                {baseline.latencyP50 != null ? `${baseline.latencyP50.toFixed(1)} ms` : '—'}
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
                      {s.latencyP50 != null ? `${s.latencyP50.toFixed(1)} ms` : '—'}
                    </span>
                    <DeltaBadge d={dLatency != null ? dLatency : null} higherIsBetter={false} />
                  </div>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
