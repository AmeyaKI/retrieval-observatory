import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test } from 'vitest'
import CandidateLineageDiff from './CandidateLineageDiff'
import { ComparisonEnvelope, JourneyDiffRow, JourneySide } from '../api'

/** Static markup escapes quotes and ampersands; compare against the text a reader sees. */
function decode(html: string): string {
  return html.replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, '&')
}

function side(overrides: Partial<JourneySide> = {}): JourneySide {
  return {
    trace_id: 't1',
    outcome: 'relevant_delivered',
    final_membership: 'included',
    in_final_output: true,
    final_rank: 3,
    loss_boundary: null,
    capture_state: 'complete',
    judgment: 'relevant',
    grade: 1,
    events_summary: ['dense:introduced', 'select:retained'],
    investigation_link: '#/investigate?run=cand&view=queries&query=q-refund',
    ...overrides,
  }
}

const rows: JourneyDiffRow[] = [
  {
    query_id: 'q-refund',
    namespace: 'kb',
    entity_id: 'doc-guide',
    unit: 'document',
    alignment: 'aligned',
    change: 'lost',
    detail: 'included at rank 3 → excluded (select)',
    baseline: side(),
    candidate: side({ outcome: 'relevant_excluded', final_membership: 'excluded', in_final_output: false, final_rank: null, loss_boundary: 'select', events_summary: ['dense:introduced', 'select:removed'] }),
    capture_limited: false,
    priority: 0,
  },
  {
    query_id: 'q-refund',
    namespace: 'kb',
    entity_id: 'doc-faq',
    unit: 'document',
    alignment: 'aligned',
    change: 'gained',
    detail: 'excluded (not_observed) → included at rank 1',
    baseline: side({ outcome: 'not_observed', final_membership: 'excluded', in_final_output: false, final_rank: null, loss_boundary: 'not_observed', events_summary: [] }),
    candidate: side({ final_rank: 1 }),
    capture_limited: false,
    priority: 1,
  },
  {
    query_id: 'q-billing',
    namespace: 'kb',
    entity_id: 'doc-terms',
    unit: 'document',
    alignment: 'aligned',
    change: 'unchanged',
    detail: 'included at rank 2 in both runs',
    baseline: side({ final_rank: 2, capture_state: 'partial' }),
    candidate: side({ final_rank: 2 }),
    capture_limited: true,
    priority: 6,
  },
]

function envelope(overrides: { corpus_changed?: boolean; query_id?: string } = {}): ComparisonEnvelope {
  return {
    schema_version: 1,
    scope: {
      run_id: 'cand',
      pipeline_id: 'hybrid',
      boundary: 'final',
      unit: 'document',
      k: 10,
      relevance_threshold: 1,
      evaluation_digest: 'e',
      judgment_digest: 'j',
      ...(overrides.query_id ? { query_id: overrides.query_id } : {}),
    },
    capabilities: { projection: 'ready', judgments: 'ready', capture: { complete_rows: 2, partial_rows: 1 } },
    coverage: { queries_attempted: 2, queries_with_traces: 2, queries_projected: 2, pairs: 3, events: 6 },
    rows,
    total: 3,
    next_cursor: null,
    summary: null,
    stages: null,
    findings: [],
    comparison: {
      baseline_run_id: 'base',
      candidate_run_id: 'cand',
      compatibility: {
        provenance: { invariants: [], interventions: [], consistency: [], unknown_fields: [] },
        findings: [],
        corpus_changed: overrides.corpus_changed ?? false,
        query_inputs_identical: true,
      },
      stage_alignment: {
        matched: [
          ['rerank@dense', 'rerank@fast'],
          ['select', 'select'],
        ],
        baseline_only: ['expand'],
        candidate_only: ['boost'],
      },
      summary: { pairs: 3, by_change: { lost: 1, gained: 1, unchanged: 1 }, by_alignment: { aligned: 3 }, capture_limited: 1 },
    },
  }
}

describe('CandidateLineageDiff', () => {
  test('names both runs and renders every pair with a glyph, a label and the observed detail', () => {
    const html = decode(renderToStaticMarkup(<CandidateLineageDiff envelope={envelope()} onSelectEntity={() => {}} />))

    expect(html).toContain('<span class="font-mono">cand</span>')
    expect(html).toContain('<span class="font-mono">base</span>')
    expect(html).toContain('<span aria-hidden="true">✕</span> Lost')
    expect(html).toContain('<span aria-hidden="true">✓</span> Gained')
    expect(html).toContain('<span aria-hidden="true">=</span> Unchanged')
    expect(html).toContain('included at rank 3 → excluded (select)')
    expect(html).toContain('excluded (not_observed) → included at rank 1')
    expect(html).toContain('included at rank 2 in both runs')
    expect(html).toContain('included #3 · relevant')
    expect(html).toContain('excluded at select · relevant')
    expect(html.match(/capture partial/g)).toHaveLength(1)
    expect(html).toContain('3 pairs · 1 lost · 1 gained · 0 rank changed · 0 path changed · 1 evidence-limited')

    expect(html).toContain('Stage alignment')
    expect(html).toContain('<code class="font-mono">rerank@dense</code> ↔ <code class="font-mono">rerank@fast</code>')
    expect(html).toMatch(/Baseline only[\s\S]*expand/)
    expect(html).toMatch(/Candidate only[\s\S]*boost/)
    expect(html).not.toMatch(/caused|cause of/i)
  })

  test('a corpus change blocks the matched comparison with a status notice', () => {
    const html = decode(renderToStaticMarkup(<CandidateLineageDiff envelope={envelope({ corpus_changed: true })} onSelectEntity={() => {}} />))

    expect(html).toContain('role="status"')
    expect(html).toContain("matched comparison blocked: corpus changed; showing each run's evidence")
  })

  test('the Query column appears only on the list scope', () => {
    const list = renderToStaticMarkup(<CandidateLineageDiff envelope={envelope()} onSelectEntity={() => {}} />)
    const single = renderToStaticMarkup(<CandidateLineageDiff envelope={envelope({ query_id: 'q-refund' })} onSelectEntity={() => {}} />)

    expect(list).toContain('>Query</th>')
    expect(single).not.toContain('>Query</th>')
  })
})
