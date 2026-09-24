import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'
// api.ts reads window.location.origin at import time; the node test environment has no window.
vi.hoisted(() => {
  ;(globalThis as { window?: unknown }).window = { location: { origin: 'http://localhost' } }
})
import type { AuditCheck, ReleaseAudit, ReleaseDecision } from '../api'
import { investigateLink } from '../utils/focusedRoutes'
import AuditReport, { AuditFallback } from './AuditReport'

// Fixture: a FAIL audit — ndcg passes, recall regresses on two queries, the "long" slice holds,
// operational accounting passes, one expected intervention and one unexpected provenance change.

function check(overrides: Partial<AuditCheck>): AuditCheck {
  return {
    id: 'aggregate:ndcg@10',
    metric: 'ndcg@10',
    target: 'aggregate',
    status: 'PASS',
    direction: 'higher_is_better',
    estimator: 'paired_mean_difference',
    effect: 0.012,
    ci_low: -0.004,
    ci_high: 0.028,
    tolerance: 0.01,
    boundary: -0.01,
    max_regression: 0.01,
    paired_n: 48,
    attempted_n: 50,
    min_paired_n: 30,
    pair_coverage: 0.96,
    confidence_level: 0.95,
    adjusted_confidence_level: 0.975,
    resamples: 2000,
    seed: 7,
    interval_method: 'percentile_bootstrap',
    sample_limitation: null,
    affected_query_ids: [],
    ...overrides,
  }
}

const AUDIT: ReleaseAudit = {
  schema_version: 'audit-1',
  generated_at: '2026-09-23T10:00:00+00:00',
  tool: { retrieval_observatory: '0.7.0', python: '3.12.4' },
  decision: {
    status: 'FAIL',
    reasons: ['recall@10 regressed beyond its tolerance.'],
    next_action: 'Inspect the regressed queries in Investigate.',
    exit_code: 1,
  },
  sources: {
    baseline: {
      db_id: 'shop', run_id: 'run-base', experiment_name: 'bm25', manifest_schema_version: 3,
      dataset: { name: 'shop-bench', query_hash: 'qh1', corpus_hash: 'ch1', qrel_hash: 'rh1' },
      judgment_digest: 'sha256:judg', release_identity: null, evaluation: null, counts: null,
    },
    candidate: {
      db_id: 'shop', run_id: 'run-cand', experiment_name: 'hybrid', manifest_schema_version: 3,
      dataset: { name: 'shop-bench', query_hash: 'qh1', corpus_hash: 'ch1', qrel_hash: 'rh1' },
      judgment_digest: 'sha256:judg', release_identity: null, evaluation: null, counts: null,
    },
  },
  policy: { configured: true, id: 'release-v3', schema_version: 2, digest: 'sha256:pol', source: 'retobs/release-policy.yaml', resolution: null, conversion: null },
  evaluation: { unit: 'document', boundary: 'final_output', k: 10, relevance_threshold: 1, comparison_scope: 'paired' },
  compatibility: {
    status: 'HOLD',
    findings: [{ code: 'unexpected_change', scope: 'provenance', status: 'HOLD', observed: 'b', required: 'a', detail: 'tokenizer changed without being declared', next_action: 'Declare the tokenizer as an intervention.' }],
    provenance: {
      invariants: [{ field: 'dataset.query_hash', baseline: 'qh1', candidate: 'qh1', equal: true, classification: 'invariant', finding_code: null }],
      interventions: [{ field: 'pipeline.retriever', baseline: 'bm25', candidate: 'hybrid', equal: false, classification: 'expected', finding_code: null }],
      consistency: [{ field: 'pipeline.tokenizer', baseline: 'a', candidate: 'b', equal: false, classification: 'unexpected', finding_code: 'unexpected_change' }],
      unknown_fields: ['env.CUDA_VERSION'],
    },
    validity: {},
  },
  readiness: {},
  coverage: { expected_query_count: 50, min_pair_coverage: 0.9, per_check: {} },
  checks: [
    check({}),
    check({
      id: 'aggregate:recall@10', metric: 'recall@10', status: 'FAIL', effect: -0.041, ci_low: -0.07, ci_high: -0.012,
      sample_limitation: 'two queries lack judgments', affected_query_ids: ['q-7', 'q-9'],
    }),
  ],
  slices: [{
    id: 'slice:length=long', field: 'length', value: 'long', status: 'HOLD', paired_n: 12, sample_limitation: 'paired n 12 below 30',
    guards: [check({ id: 'slice:length=long:ndcg@10', status: 'HOLD', paired_n: 12, attempted_n: 12, pair_coverage: 1, sample_limitation: 'paired n 12 below 30' })],
  }],
  operational: {
    status: 'PASS', code: null, max_failure_rate: 0.02,
    baseline: { run_id: 'run-base', attempted_n: 50, failed_n: 0, failure_rate: 0 },
    candidate: { run_id: 'run-cand', attempted_n: 50, failed_n: 1, failure_rate: 0.02 },
    detail: 'Candidate failure rate is within the cap.',
  },
  statistics: { confidence_level: 0.95, familywise_alpha: 0.05, resamples: 2000, seed: 7, interval_method: 'percentile_bootstrap', family_size: 3, adjusted_confidence_level: 0.983 },
  investigation: {
    scope: { db_id: 'shop', baseline_run_id: 'run-base', candidate_run_id: 'run-cand', pipeline_id: 'hybrid' },
    changed_queries: [
      { query_id: 'q-7', metric: 'recall@10', baseline: 0.8, candidate: 0.4, delta: -0.4, link: 'http://server/#/stale' },
      { query_id: 'q 9/x', metric: 'recall@10', baseline: 1, candidate: 0.5, delta: -0.5, link: 'http://server/#/stale' },
    ],
    dashboard_base_url: 'http://127.0.0.1:8000',
    requires_local_dashboard: true,
  },
  metrics: {
    'ndcg@10': { baseline_mean: 0.61, candidate_mean: 0.622, effect: 0.012, q_value: 0.21, paired_n: 48, decision: 'no_decision' },
    'recall@10': { baseline_mean: 0.72, candidate_mean: 0.679, effect: -0.041, q_value: 0.004, paired_n: 48, decision: 'candidate_worse' },
  },
}

const html = renderToStaticMarkup(<AuditReport audit={AUDIT} db="shop" />)

/** The markup of the section labelled by `id` (up to the next section). */
function section(id: string): string {
  const start = html.indexOf(`aria-labelledby="${id}"`)
  expect(start).toBeGreaterThanOrEqual(0)
  const end = html.indexOf('<section', start + 1)
  return html.slice(start, end < 0 ? undefined : end)
}

/** Text content, so a glyph in its own aria-hidden span still reads "● PASS". */
function plain(markup: string): string {
  return markup.replace(/<[^>]+>/g, '')
}

describe('AuditReport', () => {
  test('renders the decision with glyph, text, reasons, next action and exit code', () => {
    const decision = section('audit-decision')
    expect(plain(decision)).toContain('✕ FAIL')
    expect(decision).toContain('recall@10 regressed beyond its tolerance.')
    expect(decision).toContain('Inspect the regressed queries in Investigate.')
    expect(decision).toContain('exit code 1')
    expect(decision).toContain('release-v3')
    expect(decision).toContain('sha256:pol')
    expect(decision).toContain('retobs/release-policy.yaml')

    const unconfigured = renderToStaticMarkup(
      <AuditReport audit={{ ...AUDIT, decision: { ...AUDIT.decision, status: 'HOLD' }, policy: { ...AUDIT.policy, configured: false, id: null } }} db="shop" />,
    )
    expect(plain(unconfigured)).toContain('◐ HOLD')
    expect(unconfigured).toContain('no policy: a decision cannot PASS')
  })

  test('renders the compatibility table with classifications and findings', () => {
    const compat = section('audit-compatibility')
    expect(plain(compat)).toContain('◐ HOLD')
    expect(compat).toContain('<th scope="col"')
    expect(compat).toMatch(/pipeline\.retriever[\s\S]*bm25[\s\S]*hybrid[\s\S]*expected change/)
    expect(compat).toMatch(/pipeline\.tokenizer[\s\S]*unexpected/)
    expect(compat).toMatch(/dataset\.query_hash[\s\S]*invariant/)
    expect(compat).toContain('unexpected_change — tokenizer changed without being declared — Declare the tokenizer as an intervention.')
    expect(compat).toContain('env.CUDA_VERSION')
  })

  test('renders one row per check with effect, interval, tolerance, status and coverage', () => {
    const checks = section('audit-checks')
    expect(checks.match(/<tr/g)).toHaveLength(3) // header + two checks
    expect(plain(checks)).toMatch(/aggregate:ndcg@10[\s\S]*\+0\.0120[\s\S]*\[-0\.0040, \+0\.0280\][\s\S]*0\.01[\s\S]*● PASS[\s\S]*48 \/ 50[\s\S]*96%/)
    expect(plain(checks)).toMatch(/aggregate:recall@10[\s\S]*-0\.0410[\s\S]*✕ FAIL[\s\S]*two queries lack judgments/)
    expect(checks).toContain('href="#audit-changed-queries"')
    expect(checks).toContain('queries: 2')
  })

  test('renders slices and operational accounting', () => {
    const slices = section('audit-slices')
    expect(slices).toContain('length = long')
    expect(plain(slices)).toContain('◐ HOLD')
    expect(slices).toContain('slice:length=long:ndcg@10')
    expect(slices).toContain('paired n 12 below 30')

    const operational = section('audit-operational')
    expect(plain(operational)).toContain('● PASS')
    expect(operational).toMatch(/run-base[\s\S]*0 \/ 50[\s\S]*0\.0%/)
    expect(operational).toMatch(/run-cand[\s\S]*1 \/ 50[\s\S]*2\.0%/)
    expect(operational).toContain('cap 2.0%')
    expect(operational).toContain('Candidate failure rate is within the cap.')
  })

  test('links every changed query into Investigate with compare set to the baseline', () => {
    const changed = section('audit-changed-queries')
    for (const queryId of ['q-7', 'q 9/x']) {
      const href = investigateLink({ db: 'shop', run: 'run-cand', pipeline: 'hybrid', view: 'queries', query: queryId, compare: 'run-base' })
      expect(changed).toContain(`href="${href.replace(/&/g, '&amp;')}"`)
    }
    expect(changed).not.toContain('#/stale')
    expect(changed).toMatch(/q-7[\s\S]*recall@10[\s\S]*0\.8000 → 0\.4000[\s\S]*-0\.4000/)

    const empty = renderToStaticMarkup(
      <AuditReport audit={{ ...AUDIT, investigation: { ...AUDIT.investigation, changed_queries: [] } }} db="shop" />,
    )
    expect(empty).toContain('No paired query changed on the decision metric.')
  })

  test('exposes statistics and paired metrics in details blocks and a JSON download link', () => {
    expect(html).toMatch(/<details[\s\S]*<summary[^>]*>Statistics<\/summary>[\s\S]*0\.983[\s\S]*percentile_bootstrap/)
    expect(html).toMatch(/<details[\s\S]*<summary[^>]*>All paired metrics<\/summary>[\s\S]*recall@10[\s\S]*candidate_worse/)
    expect(html).toContain('download="release-audit.json"')
    const href = 'data:application/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(AUDIT, null, 2))
    expect(html).toContain(`href="${href.replace(/&/g, '&amp;')}"`)
    expect(html).toContain('sha256:judg')
    expect(html).toContain('qh1')
  })

  test('falls back to the decision card when audit is absent', () => {
    const decision: ReleaseDecision = {
      schema_version: 1,
      status: 'HOLD',
      reasons: ['Paired n below minimum.'],
      readiness: {},
      aggregate_guards: [],
      slices: [],
      next_action: 'Collect more paired queries.',
      policy: { configured: true, id: 'legacy-policy', schema_version: 1, digest: null },
      investigation: { affected_query_ids: [], query_route_template: '', diff_route_template: '' },
    }
    const fallback = renderToStaticMarkup(<AuditFallback decision={decision} db="shop" baseline="run-base" candidate="run-cand" />)
    expect(fallback).toContain('Release decision')
    expect(fallback).toContain('legacy-policy')
    const none = renderToStaticMarkup(<AuditFallback decision={null} db="shop" baseline="run-base" candidate="run-cand" />)
    expect(none).toContain('Release audit unavailable')
  })
})
