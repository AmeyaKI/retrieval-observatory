import { MetricEntry, MetricsMap } from '../api'
import { formatSeriesKey, toPipelineLabel } from './formatMetricKey'
import { isDuplicateAblationStageFromManifest, PipelineDisplayMeta } from './stageLabels'

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

export function collectPipelineIds(metrics: MetricsMap): string[] {
  return collectPipelineIdsFromMetrics(metrics)
}

export function getFinalStageIndex(pipelineId: string, maxStage: Record<string, number>): number {
  return maxStage[pipelineId] ?? 0
}

export function isMultiStagePipeline(pipelineId: string, maxStage: Record<string, number>): boolean {
  return getFinalStageIndex(pipelineId, maxStage) > 0
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
  options: { showIntermediateStages?: boolean; displayMeta?: PipelineDisplayMeta | null } = {},
): RecallSeriesPoint[] {
  const showIntermediateStages = options.showIntermediateStages ?? false
  const displayMeta = options.displayMeta
  const maxStage = buildPipelineMaxStage(metrics)
  const points: RecallSeriesPoint[] = []

  for (const entry of Object.values(metrics)) {
    if (entry.metric_name !== 'recall' || entry.k <= 0 || entry.stage_index < 0) continue

    const finalStage = getFinalStageIndex(entry.pipeline_id, maxStage)
    if (!showIntermediateStages && entry.stage_index !== finalStage) continue

    if (
      displayMeta &&
      isDuplicateAblationStageFromManifest(displayMeta, entry.pipeline_id, entry.stage_index)
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

export function isRecallMetricEntry(entry: MetricEntry): boolean {
  return entry.metric_name === 'recall' && entry.k > 0 && entry.stage_index >= 0
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
  ci_low: number | null
  ci_high: number | null
}

function recallCellKey(pipelineId: string, stageIndex: number): string {
  return `${pipelineId}|${stageIndex}`
}

/** Per-stage recall for each pipeline that has that stage index. */
export function buildStageRecallGrid(
  metrics: MetricsMap,
  k: number,
  displayMeta?: PipelineDisplayMeta | null,
): {
  maxStageIndex: number
  pipelineIds: string[]
  values: Map<string, number>
  ci: Map<string, { ci_low: number | null; ci_high: number | null }>
} {
  const maxStage = buildPipelineMaxStage(metrics)
  const pipelineIds = [...collectPipelineIdSet(metrics)].sort()
  const values = new Map<string, number>()
  const ci = new Map<string, { ci_low: number | null; ci_high: number | null }>()

  for (const entry of Object.values(metrics)) {
    if (entry.metric_name !== 'recall' || entry.k !== k || entry.stage_index < 0) continue
    if (
      displayMeta &&
      isDuplicateAblationStageFromManifest(displayMeta, entry.pipeline_id, entry.stage_index)
    ) {
      continue
    }
    const key = recallCellKey(entry.pipeline_id, entry.stage_index)
    values.set(key, entry.mean)
    ci.set(key, { ci_low: entry.ci_low, ci_high: entry.ci_high })
  }

  const maxStageIndex = Math.max(0, ...Object.values(maxStage))
  return { maxStageIndex, pipelineIds, values, ci }
}

export { recallCellKey }
