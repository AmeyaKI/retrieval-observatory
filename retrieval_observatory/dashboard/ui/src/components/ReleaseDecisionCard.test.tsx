import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'
import ReleaseDecisionCard from './ReleaseDecisionCard'
import { ReleaseDecision } from '../api'

const decision: ReleaseDecision = {
  schema_version: 1,
  status: 'PASS',
  reasons: ['Every declared guard passed.'],
  readiness: {
    promotion: { scope: 'promotion', status: 'READY', findings: [] },
    lineage_diagnosis: {
      scope: 'lineage_diagnosis',
      status: 'BLOCK',
      findings: [{
        code: 'stage_io_unavailable',
        scope: 'lineage_diagnosis',
        status: 'BLOCK',
        observed: null,
        required: 'recorded stage inputs and outputs',
        detail: 'Stage transitions were not captured.',
        next_action: 'Capture stage inputs and outputs.',
      }],
    },
  },
  aggregate_guards: [],
  slices: [],
  next_action: 'Proceed through normal deployment approval.',
  policy: { configured: true, id: 'release-v2', schema_version: 1, digest: 'sha256:abc' },
  investigation: {
    affected_query_ids: ['q-1'],
    query_route_template: '#/runs/candidate/queries/{query_id}',
    diff_route_template: '#/runs/candidate/queries/{query_id}/diff?against=baseline',
  },
}

describe('ReleaseDecisionCard', () => {
  test('keeps claim readiness separate from a passing promotion decision', () => {
    const html = renderToStaticMarkup(
      <ReleaseDecisionCard decision={decision} onQueryMetricSelect={vi.fn()} />,
    )

    expect(html).toContain('PASS')
    expect(html).toMatch(/Lineage diagnosis[\s\S]*BLOCK/i)
    expect(html).toContain('release-v2')
    expect(html).toContain('sha256:abc')
  })
})
