import { MetricsMap } from '../api'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'

interface Props {
  metrics: MetricsMap
}

interface StageInfo {
  pipelineId: string
  stageIndex: number
  stageId: string      // from metric entry (e.g. "bm25", "cross-encoder/ms-marco...")
  role: 'Retrieval' | 'Reranking'
  ndcg10: number | null
  recallBest: { k: number; mean: number } | null
  latencyP50: number | null
  outputK: number | null  // highest k value in recall metrics = docs output
}

function toTitleCase(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

// Derive a short, human-readable adapter label from config context.
// Stage 0 is always the retriever; Stage 1+ are rerankers.
function stageAdapterLabel(role: 'Retrieval' | 'Reranking', stageIndex: number): string {
  return role === 'Retrieval' ? 'BM25 / Dense Retriever' : `Reranker (Stage ${stageIndex})`
}

function fmt2(v: number): string {
  return v.toFixed(3)
}

export default function StagePipelineFlow({ metrics }: Props) {
  // Group metric entries by (pipeline_id, stage_index)
  const stageMap = new Map<string, StageInfo>()

  for (const [, entry] of Object.entries(metrics)) {
    const key = `${entry.pipeline_id}|||${entry.stage_index}`
    if (!stageMap.has(key)) {
      stageMap.set(key, {
        pipelineId: entry.pipeline_id,
        stageIndex: entry.stage_index,
        stageId: entry.pipeline_id, // will be overridden from stage_id if available
        role: entry.stage_index === 0 ? 'Retrieval' : 'Reranking',
        ndcg10: null,
        recallBest: null,
        latencyP50: null,
        outputK: null,
      })
    }
    const info = stageMap.get(key)!

    if (entry.metric_name === 'ndcg' && entry.k === 10) {
      info.ndcg10 = entry.mean
    }
    if (entry.metric_name === 'recall') {
      if (info.recallBest === null || entry.k > info.recallBest.k) {
        info.recallBest = { k: entry.k, mean: entry.mean }
        info.outputK = entry.k
      }
    }
    if (entry.metric_name === 'latency_p50') {
      info.latencyP50 = entry.mean
    }
  }

  // Group by pipeline, filter to multi-stage pipelines only
  const byPipeline = new Map<string, StageInfo[]>()
  for (const info of stageMap.values()) {
    if (!byPipeline.has(info.pipelineId)) byPipeline.set(info.pipelineId, [])
    byPipeline.get(info.pipelineId)!.push(info)
  }

  // Only show pipelines with >1 stage
  const multiStagePipelines = [...byPipeline.entries()]
    .filter(([, stages]) => stages.length > 1)
    .map(([pipelineId, stages]) => ({
      pipelineId,
      stages: stages.sort((a, b) => a.stageIndex - b.stageIndex),
    }))

  if (multiStagePipelines.length === 0) return null

  return (
    <div className="space-y-6">
      <p className="text-xs text-gray-500">
        Multi-stage pipeline flow — each box is one stage evaluated against ground truth qrels.
        <MetricTooltip text={METRIC_GLOSSARY.stage} />
      </p>
      {multiStagePipelines.map(({ pipelineId, stages }) => (
        <div key={pipelineId}>
          <p className="text-xs font-semibold text-gray-600 mb-2">{toTitleCase(pipelineId)}</p>
          <div className="flex items-stretch gap-0 overflow-x-auto">
            {stages.map((stage, i) => (
              <div key={stage.stageIndex} className="flex items-center">
                {/* Stage box */}
                <div className={`border rounded-lg p-3 min-w-[160px] ${
                  stage.role === 'Retrieval'
                    ? 'border-indigo-200 bg-indigo-50'
                    : 'border-amber-200 bg-amber-50'
                }`}>
                  <div className={`text-[10px] font-bold uppercase tracking-wide mb-1 ${
                    stage.role === 'Retrieval' ? 'text-indigo-500' : 'text-amber-600'
                  }`}>
                    Stage {stage.stageIndex} · {stage.role}
                  </div>
                  <div className="text-xs text-gray-700 font-medium mb-2 truncate" title={toTitleCase(stage.pipelineId)}>
                    {stageAdapterLabel(stage.role, stage.stageIndex)}
                  </div>
                  <div className="space-y-0.5 text-xs text-gray-600">
                    {stage.ndcg10 !== null && (
                      <div className="flex justify-between gap-3">
                        <span className="text-gray-400">NDCG@10</span>
                        <span className="tabular-nums font-medium">{fmt2(stage.ndcg10)}</span>
                      </div>
                    )}
                    {stage.recallBest !== null && (
                      <div className="flex justify-between gap-3">
                        <span className="text-gray-400">Recall@{stage.recallBest.k}</span>
                        <span className="tabular-nums font-medium">{fmt2(stage.recallBest.mean)}</span>
                      </div>
                    )}
                    {stage.latencyP50 !== null && (
                      <div className="flex justify-between gap-3">
                        <span className="text-gray-400">Latency P50</span>
                        <span className="tabular-nums font-medium">{stage.latencyP50.toFixed(0)} ms</span>
                      </div>
                    )}
                    {stage.outputK !== null && (
                      <div className="flex justify-between gap-3 pt-1 border-t border-gray-200 mt-1">
                        <span className="text-gray-400">Outputs</span>
                        <span className="tabular-nums text-gray-500">{stage.outputK} docs</span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Arrow between stages */}
                {i < stages.length - 1 && (
                  <div className="flex flex-col items-center mx-2 text-gray-400 text-xs select-none">
                    <span className="text-lg leading-none">→</span>
                    <span className="text-[9px] text-gray-300 mt-0.5">feeds</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
