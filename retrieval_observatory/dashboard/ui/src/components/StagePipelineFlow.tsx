import { MetricsMap, PipelineTopology, TopologyStage } from '../api'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'
import { fmtQuality } from '../utils/format'

interface Props {
  metrics: MetricsMap
  topology?: PipelineTopology
}

function titleCase(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function stageName(raw: string): string {
  return raw
    .replace(/_rerank$/, ' Reranker')
    .replace(/_retriever$/, ' Retriever')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function fallbackTopology(metrics: MetricsMap): PipelineTopology {
  const byStage = new Map<string, { pipelineId: string; stage: TopologyStage }>()
  for (const entry of Object.values(metrics)) {
    if (entry.stage_index < 0 || entry.branch_id) continue
    const key = `${entry.pipeline_id}|${entry.stage_index}`
    if (!byStage.has(key)) {
      byStage.set(key, {
        pipelineId: entry.pipeline_id,
        stage: {
          stage_index: entry.stage_index,
          stage_id: `stage_${entry.stage_index}`,
          kind: entry.stage_index === 0 ? 'single' : 'rerank',
          candidate_count: 0,
          metrics: {
            'ndcg@10': null,
            recall: { k: null, mean: null },
            latency_p50: null,
          },
          arms: [],
        },
      })
    }
    const current = byStage.get(key)!.stage
    if (entry.metric_name === 'ndcg' && entry.k === 10) current.metrics['ndcg@10'] = entry.mean
    if (entry.metric_name === 'recall') {
      if (current.metrics.recall.k == null || entry.k > current.metrics.recall.k) {
        current.metrics.recall = { k: entry.k, mean: entry.mean }
      }
    }
    if (entry.metric_name === 'latency_p50') current.metrics.latency_p50 = entry.mean
  }
  const topology: PipelineTopology = {}
  for (const { pipelineId, stage } of byStage.values()) {
    if (!topology[pipelineId]) topology[pipelineId] = []
    topology[pipelineId].push(stage)
  }
  for (const pid of Object.keys(topology)) {
    topology[pid].sort((a, b) => a.stage_index - b.stage_index)
  }
  return topology
}

function MetricBlock({
  ndcg10,
  recall,
  latencyP50,
  candidateCount,
}: {
  ndcg10: number | null
  recall: { k: number | null; mean: number | null }
  latencyP50: number | null
  candidateCount?: number
}) {
  return (
    <div className="space-y-0.5 text-xs text-gray-600">
      {ndcg10 !== null && (
        <div className="flex justify-between gap-3">
          <span className="text-gray-400">NDCG@10</span>
          <span className="tabular-nums font-medium">{fmtQuality(ndcg10)}</span>
        </div>
      )}
      {recall.k !== null && recall.mean !== null && (
        <div className="flex justify-between gap-3">
          <span className="text-gray-400">Recall@{recall.k}</span>
          <span className="tabular-nums font-medium">{fmtQuality(recall.mean)}</span>
        </div>
      )}
      {latencyP50 !== null && (
        <div className="flex justify-between gap-3">
          <span className="text-gray-400">Latency P50</span>
          <span className="tabular-nums font-medium">{latencyP50.toFixed(0)} ms</span>
        </div>
      )}
      {candidateCount != null && candidateCount > 0 && (
        <div className="flex justify-between gap-3 pt-1 border-t border-gray-200 mt-1">
          <span className="text-gray-400">Candidates</span>
          <span className="tabular-nums text-gray-500">{Math.round(candidateCount)}</span>
        </div>
      )}
    </div>
  )
}

export default function StagePipelineFlow({ metrics, topology }: Props) {
  const pipelineTopology = topology && Object.keys(topology).length > 0 ? topology : fallbackTopology(metrics)
  const pipelines = Object.entries(pipelineTopology)
    .map(([pipelineId, stages]) => ({ pipelineId, stages }))
    .sort((a, b) => a.pipelineId.localeCompare(b.pipelineId))

  if (pipelines.length === 0) return null

  return (
    <div className="space-y-6">
      <p className="text-xs text-gray-500">
        Each pipeline&apos;s stages are evaluated against ground-truth qrels. Hybrid retrieval stages expose arm-level metrics and a fused join.
        <MetricTooltip text={METRIC_GLOSSARY.stage} />
      </p>
      {pipelines.map(({ pipelineId, stages }) => (
        <div key={pipelineId}>
          <p className="text-xs font-semibold text-gray-600 mb-2">{titleCase(pipelineId)}</p>
          <div className="flex items-stretch gap-0 overflow-x-auto">
            {stages.map((stage, i) => {
              const role = stage.stage_index === 0 ? 'Retrieval' : 'Reranking'
              const fused = stage.kind === 'fused' && stage.arms.length > 0
              return (
                <div key={stage.stage_index} className="flex items-center">
                  <div className={`border rounded-lg p-3 min-w-[170px] ${stage.stage_index === 0 ? 'border-indigo-200 bg-indigo-50' : 'border-amber-200 bg-amber-50'}`}>
                    <div className={`text-[10px] font-bold uppercase tracking-wide mb-1 ${stage.stage_index === 0 ? 'text-indigo-500' : 'text-amber-600'}`}>
                      Stage {stage.stage_index} · {role}
                    </div>
                    <div className="text-xs text-gray-700 font-medium mb-2 truncate" title={stageName(stage.stage_id)}>
                      {stageName(stage.stage_id)}
                    </div>
                    <MetricBlock
                      ndcg10={stage.metrics['ndcg@10']}
                      recall={stage.metrics.recall}
                      latencyP50={stage.metrics.latency_p50}
                      candidateCount={stage.candidate_count}
                    />
                  </div>

                  {fused && (
                    <div className="mx-3">
                      <div className="text-[11px] text-gray-400 mb-1">↘ fan-out ↙</div>
                      <div className="space-y-2">
                        {stage.arms.map((arm) => (
                          <div key={arm.arm_id} className="border border-sky-200 bg-sky-50 rounded-lg p-2 min-w-[180px]">
                            <div className="text-[10px] font-bold uppercase tracking-wide text-sky-600 mb-1">
                              Arm · {stageName(arm.arm_id)}
                            </div>
                            <MetricBlock
                              ndcg10={arm.metrics['ndcg@10']}
                              recall={arm.metrics.recall}
                              latencyP50={arm.metrics.latency_p50}
                              candidateCount={arm.candidate_count}
                            />
                          </div>
                        ))}
                        <div className="text-center text-[10px] text-teal-700 border border-teal-200 bg-teal-50 rounded px-2 py-1">
                          RRF Fusion Join
                        </div>
                      </div>
                    </div>
                  )}

                  {i < stages.length - 1 && (
                    <div className="flex flex-col items-center mx-2 text-gray-400 text-xs select-none">
                      <span className="text-lg leading-none">→</span>
                      <span className="text-[9px] text-gray-300 mt-0.5">
                        {Math.round(stage.candidate_count || 0)} → {Math.round(stages[i + 1].candidate_count || 0)}
                      </span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
