import { MetricEntry, MetricsMap } from '../api'
import { formatSeriesKey, toPipelineLabel } from './formatMetricKey'

const METRIC_EPS = 1e-9

export function buildPipelineMaxStage(metrics: MetricsMap): Record<string, number> {
  const maxStage: Record<string, number> = {}
  for (const entry of Object.values(metrics)) {
    if (entry.stage_index < 0) continue
    maxStage[entry.pipeline_id] = Math.max(maxStage[entry.pipeline_id] ?? 0, entry.stage_index)
  }
  return maxStage
}

export function collectPipelineIdSet(metrics: MetricsMap): Set<string> {
  return new Set(collectPipelineIdsFromMetrics(metrics))
}

function collectPipelineIdsFromMetrics(metrics: MetricsMap): string[] {
  const ids = new Set<string>()
  for (const entry of Object.values(metrics)) {
    if (entry.stage_index >= 0) ids.add(entry.pipeline_id)
  }
  return [...ids]
}

export function getFinalStageIndex(pipelineId: string, maxStage: Record<string, number>): number {
  return maxStage[pipelineId] ?? 0
}

export function isMultiStagePipeline(pipelineId: string, maxStage: Record<string, number>): boolean {
  return getFinalStageIndex(pipelineId, maxStage) > 0
}

/** Pipeline id for the ablation prefix through stageIndex (e.g. bm25__rerank @ stage 0 → bm25). */
export function ablationPrefixAtStage(pipelineId: string, stageIndex: number): string {
  const parts = pipelineId.split('__')
  return parts.slice(0, stageIndex + 1).join('__')
}

export function getRecallValuesByK(
  metrics: MetricsMap,
  pipelineId: string,
  stageIndex: number,
): Map<number, number> {
  const byK = new Map<number, number>()
  for (const entry of Object.values(metrics)) {
    if (entry.pipeline_id !== pipelineId) continue
    if (entry.stage_index !== stageIndex) continue
    if (entry.metric_name !== 'recall' || entry.k <= 0) continue
    byK.set(entry.k, entry.mean)
  }
  return byK
}

function recallProfilesMatch(
  metrics: MetricsMap,
  aPipeline: string,
  aStage: number,
  bPipeline: string,
  bStage: number,
): boolean {
  const a = getRecallValuesByK(metrics, aPipeline, aStage)
  const b = getRecallValuesByK(metrics, bPipeline, bStage)
  if (a.size === 0 || b.size === 0 || a.size !== b.size) return false
  for (const [k, av] of a) {
    const bv = b.get(k)
    if (bv === undefined || Math.abs(av - bv) > METRIC_EPS) return false
  }
  return true
}

/**
 * True when this stage's recall curve matches a shorter standalone ablation pipeline
 * (e.g. bm25__rerank stage 0 vs bm25 final).
 */
export function isDuplicateAblationStage(
  metrics: MetricsMap,
  pipelineIds: Set<string>,
  maxStage: Record<string, number>,
  pipelineId: string,
  stageIndex: number,
): boolean {
  const prefixId = ablationPrefixAtStage(pipelineId, stageIndex)
  if (prefixId === pipelineId) return false
  if (!pipelineIds.has(prefixId)) return false
  const prefixFinal = getFinalStageIndex(prefixId, maxStage)
  return recallProfilesMatch(metrics, pipelineId, stageIndex, prefixId, prefixFinal)
}

export interface RecallSeriesPoint {
  seriesKey: string
  pipelineId: string
  stageIndex: number
  k: number
  mean: number
  ci_low: number | null
  ci_high: number | null
}

/** Build recall@K series for charts; final-stage only unless showIntermediateStages. */
export function buildRecallSeries(
  metrics: MetricsMap,
  options: { showIntermediateStages?: boolean } = {},
): RecallSeriesPoint[] {
  const showIntermediateStages = options.showIntermediateStages ?? false
  const maxStage = buildPipelineMaxStage(metrics)
  const pipelineIds = collectPipelineIdSet(metrics)
  const points: RecallSeriesPoint[] = []

  for (const entry of Object.values(metrics)) {
    if (entry.metric_name !== 'recall' || entry.k <= 0 || entry.stage_index < 0) continue

    const finalStage = getFinalStageIndex(entry.pipeline_id, maxStage)
    if (!showIntermediateStages && entry.stage_index !== finalStage) continue

    if (
      isDuplicateAblationStage(
        metrics,
        pipelineIds,
        maxStage,
        entry.pipeline_id,
        entry.stage_index,
      )
    ) {
      continue
    }

    const multi = isMultiStagePipeline(entry.pipeline_id, maxStage)
    const seriesKey = showIntermediateStages && multi
      ? formatSeriesKey(entry.pipeline_id, entry.stage_index, true)
      : toPipelineLabel(entry.pipeline_id)

    points.push({
      seriesKey,
      pipelineId: entry.pipeline_id,
      stageIndex: entry.stage_index,
      k: entry.k,
      mean: entry.mean,
      ci_low: entry.ci_low,
      ci_high: entry.ci_high,
    })
  }

  return points
}

/** Stage series keys to omit from the funnel when they duplicate an ablation prefix pipeline. */
export function duplicateAblationSeriesKeys(metrics: MetricsMap): Set<string> {
  const maxStage = buildPipelineMaxStage(metrics)
  const pipelineIds = collectPipelineIdSet(metrics)
  const omitted = new Set<string>()

  for (const pipelineId of pipelineIds) {
    const finalStage = getFinalStageIndex(pipelineId, maxStage)
    for (let stageIndex = 0; stageIndex <= finalStage; stageIndex += 1) {
      if (!isDuplicateAblationStage(metrics, pipelineIds, maxStage, pipelineId, stageIndex)) continue
      const multi = isMultiStagePipeline(pipelineId, maxStage)
      omitted.add(formatSeriesKey(pipelineId, stageIndex, multi))
    }
  }

  return omitted
}

export function isRecallMetricEntry(entry: MetricEntry): boolean {
  return entry.metric_name === 'recall' && entry.k > 0 && entry.stage_index >= 0
}

/** Human-readable stage component name from pipeline id (e.g. fast_rerank → Fast Reranker). */
export function stageComponentLabel(pipelineId: string, stageIndex: number): string {
  const part = pipelineId.split('__')[stageIndex] ?? ''
  const known: Record<string, string> = {
    bm25: 'BM25',
    dense_only: 'Dense Bi-Encoder',
    rrf_hybrid: 'RRF Fusion',
    cohere_rerank: 'Cohere Rerank',
  }
  if (known[part]) return known[part]
  return part
    .replace(/_rerank$/, ' Reranker')
    .replace(/_retriever$/, ' Retriever')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Collect sorted recall@K values present in metrics. */
export function collectRecallKValues(metrics: MetricsMap): number[] {
  const ks = new Set<number>()
  for (const entry of Object.values(metrics)) {
    if (entry.metric_name === 'recall' && entry.k > 0 && entry.stage_index >= 0) {
      ks.add(entry.k)
    }
  }
  return [...ks].sort((a, b) => a - b)
}

export interface StageRecallCell {
  pipelineId: string
  stageIndex: number
  k: number
  mean: number
}

/** Per-stage recall for each pipeline that has that stage index. */
export function buildStageRecallGrid(metrics: MetricsMap, k: number): {
  maxStageIndex: number
  pipelineIds: string[]
  values: Map<string, number>
} {
  const maxStage = buildPipelineMaxStage(metrics)
  const pipelineIds = [...collectPipelineIdSet(metrics)].sort()
  const values = new Map<string, number>()

  for (const entry of Object.values(metrics)) {
    if (entry.metric_name !== 'recall' || entry.k !== k || entry.stage_index < 0) continue
    const key = `${entry.pipeline_id}|${entry.stage_index}`
    values.set(key, entry.mean)
  }

  const maxStageIndex = Math.max(0, ...Object.values(maxStage))
  return { maxStageIndex, pipelineIds, values }
}
