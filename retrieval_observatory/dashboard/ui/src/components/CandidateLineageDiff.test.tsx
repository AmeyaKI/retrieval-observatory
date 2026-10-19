import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test } from 'vitest'
import CandidateLineageDiff, { CompareHeadline } from './CandidateLineageDiff'
import { ComparisonEnvelope, JourneyDiffRow, JourneySide, StageAlignment } from '../api'

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

const notCorrect = side({ outcome: 'judged_nonrelevant', judgment: 'nonrelevant', final_membership: 'excluded', in_final_output: false, final_rank: null, loss_boundary: 'select' })

/** A judged-nonrelevant row whose path changed between the runs. */
const otherRow: JourneyDiffRow = {
  ...rows[2],
  query_id: 'q-billing',
  entity_id: 'doc-legal',
  change: 'path_changed',
  detail: 'excluded (select) → excluded (fuse)',
  baseline: notCorrect,
  candidate: { ...notCorrect, loss_boundary: 'fuse' },
  capture_limited: false,
  priority: 4,
}

function envelope(
  overrides: { corpus_changed?: boolean; query_id?: string; rows?: JourneyDiffRow[]; stage_alignment?: StageAlignment | null } = {},
): ComparisonEnvelope {
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
    rows: overrides.rows ?? rows,
    total: (overrides.rows ?? rows).length,
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
      stage_alignment:
        overrides.stage_alignment !== undefined
          ? overrides.stage_alignment
          : {
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

const names: Record<string, string> = { select: 'Select' }

function renderDiff(env: ComparisonEnvelope): string {
  return decode(renderToStaticMarkup(<CandidateLineageDiff envelope={env} rows={env.rows} stepNameOf={(opId) => names[opId] ?? opId} onSelectEntity={() => {}} />))
}

function renderHeadline(env: ComparisonEnvelope): string {
  return decode(renderToStaticMarkup(<CompareHeadline envelope={env} rows={env.rows} auditHref="#/audit?baseline=base&candidate=cand" />))
}

/** The text of the `<tr>` rows inside the table whose caption starts with `caption`. */
function tableRows(html: string, caption: string): string[] {
  const start = html.indexOf(`>${caption}`)
  if (start < 0) return []
  const table = html.slice(start, html.indexOf('</table>', start))
  return [...table.matchAll(/<tr class[^>]*>([\s\S]*?)<\/tr>/g)].map((match) => match[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim())
}

describe('CompareHeadline', () => {
  test('counts correct documents gained and lost, names both runs and links back to the audit', () => {
    const html = renderHeadline(envelope())

    expect(html).toContain('<h2 class="text-[22px] font-semibold leading-tight text-ink">Against baseline base: 1 correct document gained, 1 lost.</h2>')
    expect(html.replace(/<[^>]+>/g, '')).toContain('Candidate cand · baseline base · 3 documents compared · Back to audit')
    expect(html).toContain('<span class="font-mono">cand</span>')
    expect(html).toContain('href="#/audit?baseline=base&candidate=cand"')
    expect(html).toContain('1 row was only partly recorded, so its reasons are not asserted.')
    expect(html).not.toContain('Technical details')
  })

  test('a corpus change is a calm blocking notice; compatibility findings sit in Technical details with their codes', () => {
    const env = envelope({ corpus_changed: true })
    env.comparison.compatibility.findings = [{ code: 'corpus_hash_changed', detail: 'corpus hash differs' } as ComparisonEnvelope['comparison']['compatibility']['findings'][number]]
    const html = renderHeadline(env)

    expect(html).toContain('role="status"')
    expect(html).toContain("The corpus changed between the runs, so documents are not paired; each run's evidence is shown as recorded.")
    expect(html).toMatch(/<summary[^>]*>Technical details<\/summary>[\s\S]*corpus_hash_changed/)
  })

  test('different question inputs get their own notice; no notice when nothing was partly recorded', () => {
    const env = envelope({ rows: [rows[0], rows[1]] })
    env.comparison.compatibility.query_inputs_identical = false
    const html = renderHeadline(env)

    expect(html).toContain("The question inputs differ between the runs; questions whose input changed can't be compared.")
    expect(html).not.toContain('partly recorded')
  })
})

describe('CandidateLineageDiff', () => {
  test('correct documents that changed lead, lost before gained, each side in words and the change as a pill', () => {
    const html = renderDiff(envelope())

    expect(html).toContain('Correct documents that changed (2)</caption>')
    expect(tableRows(html, 'Correct documents that changed')).toEqual([
      'q-refund doc-guide Delivered at #3 Dropped by Select Lost',
      'q-refund doc-faq Never found Delivered at #1 Gained',
    ])
    expect(html).toContain('bg-status-negative/10 text-status-negative">Lost</span>')
    expect(html).toContain('bg-status-positive/10 text-status-positive">Gained</span>')
    expect(html).toContain('title="included at rank 3 → excluded (select)"')
    expect(html).not.toContain('Other changes')
    expect(html).toMatch(/<details[^>]*><summary[^>]*>Unchanged \(1\)<\/summary>/)
    expect(tableRows(html, 'Unchanged (1)')).toEqual(['q-billing doc-terms Delivered at #2 · Partly recorded Delivered at #2 Unchanged'])
    expect(html.replace(/<[^>]+>/g, '')).not.toMatch(/[✕✓◐↕⇢∅↔]/)
    expect(html).not.toMatch(/caused|cause of/i)
  })

  test('stage alignment lists only the differences', () => {
    const html = renderDiff(envelope())

    expect(html).toContain('Steps that differ between the runs')
    expect(html).toContain('<code class="font-mono text-xs text-ink">rerank@dense</code> in the baseline matches <code class="font-mono text-xs text-ink">rerank@fast</code> in the')
    expect(html).toMatch(/Only in the baseline: [\s\S]*expand/)
    expect(html).toMatch(/Only in the candidate: [\s\S]*boost/)
    expect(html).toContain('The other step matches.')
  })

  test('stage alignment collapses to one line when every step matches, and is absent on the list scope', () => {
    const matched: StageAlignment = { matched: [['dense', 'dense'], ['fuse', 'fuse'], ['select', 'select']], baseline_only: [], candidate_only: [] }
    const html = renderDiff(envelope({ stage_alignment: matched }))

    expect(html).toContain('All 3 steps match between the runs.')
    expect(html).not.toContain('Steps that differ')
    expect(renderDiff(envelope({ stage_alignment: null }))).not.toContain('match between the runs')
  })

  test('other changes stay collapsed and neutral under correct documents, and open when no correct document changed', () => {
    const lostOther: JourneyDiffRow = { ...otherRow, entity_id: 'doc-ad', change: 'lost', priority: 0 }
    const withCorrect = renderDiff(envelope({ rows: [...rows, otherRow, lostOther] }))
    expect(withCorrect).toMatch(/<details[^>]*><summary[^>]*>Other changes \(2\)<\/summary>/)
    expect(withCorrect).toContain('<caption class="sr-only">Other changes (2)</caption>')
    expect(tableRows(withCorrect, 'Other changes (2)')).toEqual([
      'q-billing doc-ad Not in the top 10 Not in the top 10 Lost',
      'q-billing doc-legal Not in the top 10 Not in the top 10 Different path',
    ])
    expect(withCorrect).toContain('border-hairline bg-surface-muted text-ink-muted">Lost</span>')

    const without = renderDiff(envelope({ rows: [otherRow, rows[2]] }))
    expect(without).toContain('No correct document changed between the runs.')
    expect(without).not.toMatch(/<summary[^>]*>Other changes/)
    expect(without).toMatch(/<caption class="border-b[^"]*">Other changes \(1\)<\/caption>/)
  })

  test('the Question column appears only on the list scope; one namespace drops the prefix', () => {
    const list = renderDiff(envelope())
    const single = renderDiff(envelope({ query_id: 'q-refund' }))

    expect(list).toContain('>Question</th>')
    expect(single).not.toContain('>Question</th>')
    expect(list).toContain('>doc-guide</button>')
    const mixed = renderDiff(envelope({ rows: [rows[0], { ...rows[1], namespace: 'tickets' }] }))
    expect(mixed).toContain('>kb:doc-guide</button>')
    expect(mixed).toContain('>tickets:doc-faq</button>')
  })
})
