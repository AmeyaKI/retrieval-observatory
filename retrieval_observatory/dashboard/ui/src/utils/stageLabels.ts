/** Stage display labels from run manifest (config-derived), not pipeline-id parsing. */

export interface PipelineDisplayMeta {
  stage_labels?: Record<string, string[]>
  duplicate_ablation_stages?: Array<{
    pipeline_id: string
    stage_index: number
    equivalent_pipeline_id: string
  }>
}

export function stageLabelFromManifest(
  meta: PipelineDisplayMeta | null | undefined,
  pipelineId: string,
  stageIndex: number,
): string {
  const labels = meta?.stage_labels?.[pipelineId]
  if (labels && labels[stageIndex]) return labels[stageIndex]
  return `Stage ${stageIndex}`
}

export function isDuplicateAblationStageFromManifest(
  meta: PipelineDisplayMeta | null | undefined,
  pipelineId: string,
  stageIndex: number,
): boolean {
  const list = meta?.duplicate_ablation_stages ?? []
  return list.some(
    (d) => d.pipeline_id === pipelineId && d.stage_index === stageIndex,
  )
}
