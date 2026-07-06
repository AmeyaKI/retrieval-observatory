import { describe, expect, it } from 'vitest'
import {
  isDuplicateAblationStageFromManifest,
  stageLabelFromManifest,
  type PipelineDisplayMeta,
} from './stageLabels'

const META: PipelineDisplayMeta = {
  stage_labels: {
    bm25: ['bm25'],
    'bm25__rerank': ['bm25', 'cross_rerank'],
  },
  duplicate_ablation_stages: [
    { pipeline_id: 'bm25__rerank', stage_index: 0, equivalent_pipeline_id: 'bm25' },
  ],
}

describe('stageLabelFromManifest', () => {
  it('returns config-derived labels, not parsed pipeline ids', () => {
    expect(stageLabelFromManifest(META, 'bm25__rerank', 1)).toBe('cross_rerank')
    expect(stageLabelFromManifest(null, 'my_prod_pipeline', 0)).toBe('Stage 0')
  })
})

describe('isDuplicateAblationStageFromManifest', () => {
  it('flags explicit manifest duplicates only', () => {
    expect(isDuplicateAblationStageFromManifest(META, 'bm25__rerank', 0)).toBe(true)
    expect(isDuplicateAblationStageFromManifest(META, 'bm25__rerank', 1)).toBe(false)
    expect(isDuplicateAblationStageFromManifest(null, 'bm25__rerank', 0)).toBe(false)
  })
})
