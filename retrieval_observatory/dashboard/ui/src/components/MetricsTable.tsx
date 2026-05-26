import { MetricEntry, MetricsMap } from '../api'
import { formatMetricKey } from '../utils/formatMetricKey'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY, lookupGlossary } from '../utils/metricGlossary'

interface Props {
  metrics: MetricsMap
  pValues?: Record<string, number>
  /** Published baselines keyed by "metric@k" e.g. {"ndcg@10": 0.326} */
  baselines?: Record<string, number>
}

function fmt(v: number): string {
  return v.toFixed(4)
}

function ciLabel(entry: MetricEntry): string {
  return `[${fmt(entry.ci_low)}, ${fmt(entry.ci_high)}]`
}

const METRIC_ORDER = ['ndcg', 'recall', 'mrr', 'map', 'latency']
function metricSortKey(metricName: string): number {
  const idx = METRIC_ORDER.findIndex((m) => metricName.toLowerCase().includes(m))
  return idx === -1 ? 99 : idx
}

export default function MetricsTable({ metrics, pValues, baselines = {} }: Props) {
  const hasBaselines = Object.keys(baselines).length > 0

  // Group entries by pipeline_id, then stage_index
  const byPipeline: Record<string, Record<number, Array<[string, MetricEntry]>>> = {}
  const pipelineOrder: string[] = []

  for (const [key, entry] of Object.entries(metrics)) {
    if (entry.stage_index < 0) continue // skip E2E total rows (latency only, shown in chart)
    if (!byPipeline[entry.pipeline_id]) {
      byPipeline[entry.pipeline_id] = {}
      pipelineOrder.push(entry.pipeline_id)
    }
    if (!byPipeline[entry.pipeline_id][entry.stage_index]) {
      byPipeline[entry.pipeline_id][entry.stage_index] = []
    }
    byPipeline[entry.pipeline_id][entry.stage_index].push([key, entry])
  }

  // Sort entries within each stage: NDCG → Recall → MRR → MAP → Latency
  for (const pid of pipelineOrder) {
    for (const stage of Object.keys(byPipeline[pid])) {
      byPipeline[pid][Number(stage)].sort(([, a], [, b]) =>
        metricSortKey(a.metric_name) - metricSortKey(b.metric_name) ||
        (a.k - b.k)
      )
    }
  }

  // Detect multi-stage pipelines for stage role labels
  const pipelineStages: Record<string, Set<number>> = {}
  for (const [, e] of Object.entries(metrics)) {
    if (e.stage_index < 0) continue
    if (!pipelineStages[e.pipeline_id]) pipelineStages[e.pipeline_id] = new Set()
    pipelineStages[e.pipeline_id].add(e.stage_index)
  }
  const multiStagePipelines = new Set(
    Object.entries(pipelineStages)
      .filter(([, stages]) => stages.size > 1)
      .map(([pid]) => pid)
  )

  if (pipelineOrder.length === 0) {
    return <p className="text-sm text-gray-400">No metrics available.</p>
  }

  const toPipelineLabel = (pid: string) =>
    pid.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

  const toStageLabel = (pid: string, stage: number): string => {
    if (!multiStagePipelines.has(pid)) return ''
    return stage === 0 ? 'Stage 0 · Retrieval' : `Stage ${stage} · Reranking`
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="bg-gray-100 text-left">
            <th className="px-3 py-2 font-semibold text-gray-700">
              Metric
              <MetricTooltip text={METRIC_GLOSSARY.stage} />
            </th>
            <th className="px-3 py-2 font-semibold text-gray-700 text-right">Mean</th>
            <th className="px-3 py-2 font-semibold text-gray-700 text-right">Std</th>
            <th className="px-3 py-2 font-semibold text-gray-700 text-right">
              95% CI
              <MetricTooltip text={METRIC_GLOSSARY.ci} alignLeft />
            </th>
            <th className="px-3 py-2 font-semibold text-gray-700 text-right">N</th>
            <th className="px-3 py-2 font-semibold text-gray-700 text-right">
              Zero%
              <MetricTooltip text={METRIC_GLOSSARY.zero_pct} alignLeft />
            </th>
            {hasBaselines && (
              <th className="px-3 py-2 font-semibold text-gray-500 text-right text-xs">
                Ref (BM25)
                <MetricTooltip text={METRIC_GLOSSARY.ref_bm25} alignLeft />
              </th>
            )}
            {pValues && (
              <th className="px-3 py-2 font-semibold text-gray-700 text-right">
                p-value
                <MetricTooltip text={METRIC_GLOSSARY.p_value} alignLeft />
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {pipelineOrder.map((pid, pidIdx) => {
            const stages = Object.keys(byPipeline[pid]).map(Number).sort((a, b) => a - b)
            return (
              <>
                {/* Pipeline group header */}
                <tr key={`header-${pid}`} className={pidIdx > 0 ? 'border-t-2 border-gray-300' : ''}>
                  <td
                    colSpan={hasBaselines ? (pValues ? 8 : 7) : (pValues ? 7 : 6)}
                    className="px-3 py-2 bg-gray-50 text-xs font-bold text-gray-600 uppercase tracking-wide"
                  >
                    {toPipelineLabel(pid)}
                  </td>
                </tr>

                {stages.map((stage) => {
                  const stageLabel = toStageLabel(pid, stage)
                  const rows = byPipeline[pid][stage]
                  return (
                    <>
                      {/* Stage sub-header (only for multi-stage pipelines) */}
                      {stageLabel && (
                        <tr key={`stage-${pid}-${stage}`}>
                          <td
                            colSpan={hasBaselines ? (pValues ? 8 : 7) : (pValues ? 7 : 6)}
                            className="px-3 py-1 bg-gray-50 text-[11px] font-semibold text-indigo-600 border-t border-gray-100"
                          >
                            {stageLabel}
                          </td>
                        </tr>
                      )}

                      {/* Metric rows */}
                      {rows.map(([key, entry]) => {
                        const pv = pValues?.[key]
                        const significant = pv !== undefined && pv < 0.05
                        const isLatency = entry.metric_name.startsWith('latency')
                        const baselineKey = entry.k > 0 ? `${entry.metric_name}@${entry.k}` : null
                        const baselineVal = baselineKey ? baselines[baselineKey] : undefined
                        const zeroPctHigh = !isLatency && entry.zero_pct > 40
                        const zeroPctMed = !isLatency && entry.zero_pct > 20 && !zeroPctHigh
                        return (
                          <tr key={key} className="hover:bg-gray-50 border-t border-gray-100">
                            <td className="px-3 pl-6 py-2 text-gray-700">
                              {formatMetricKey(key, multiStagePipelines, true)}
                              {lookupGlossary(entry.metric_name) && (
                                <MetricTooltip text={lookupGlossary(entry.metric_name)!} />
                              )}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums font-medium">{fmt(entry.mean)}</td>
                            <td className="px-3 py-2 text-right tabular-nums text-gray-500">{fmt(entry.std)}</td>
                            <td className="px-3 py-2 text-right tabular-nums text-gray-600 text-xs">{ciLabel(entry)}</td>
                            <td className="px-3 py-2 text-right text-gray-500">{entry.n}</td>
                            <td className={`px-3 py-2 text-right text-xs tabular-nums font-medium ${
                              zeroPctHigh ? 'text-red-600 bg-red-50' :
                              zeroPctMed ? 'text-amber-600 bg-amber-50' :
                              'text-gray-400'
                            }`}>
                              {isLatency ? '—' : `${entry.zero_pct}%`}
                            </td>
                            {hasBaselines && (
                              <td className="px-3 py-2 text-right text-gray-400 text-xs tabular-nums">
                                {baselineVal !== undefined ? fmt(baselineVal) : '—'}
                              </td>
                            )}
                            {pValues && (
                              <td className={`px-3 py-2 text-right tabular-nums ${significant ? 'font-bold text-indigo-700' : 'text-gray-500'}`}>
                                {pv !== undefined ? `${pv.toFixed(3)}${significant ? ' *' : ''}` : '—'}
                              </td>
                            )}
                          </tr>
                        )
                      })}
                    </>
                  )
                })}
              </>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
