import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'
// api.ts reads window.location.origin at import time; the node test environment has no window.
vi.hoisted(() => {
  ;(globalThis as { window?: unknown }).window = { location: { origin: 'http://localhost' } }
})
import type { CapabilityReport, IntegrationRecord, IntegrationSummary } from '../api'
import { CAPABILITY_NAMES } from '../api'
import { buildHash, investigateLink } from '../utils/focusedRoutes'
import { AGENT_REQUEST, capabilityLabel, IntegrationList, IntegrationPanel } from './ConnectWorkspace'

// Fixture: a verified integration whose reranker captured ids only (partial), with one run recorded.

function ready(scope: string): CapabilityReport {
  return { status: 'ready', evidence: {}, scope, failures: [] }
}

const RECORD: IntegrationRecord = {
  schema_version: 1,
  integration_id: 'shop-search:hybrid',
  service_id: 'shop-search',
  pipeline_id: 'hybrid',
  plan_id: 'plan-7f3a',
  project_root: '/srv/shop-search',
  db_path: '/srv/shop-search/retobs/retobs.db',
  verified_at: '2026-09-22T10:15:00+00:00',
  version: 2,
  created_at: '2026-09-22T10:15:00+00:00',
  status: 'partial',
  depth: 'internal',
  capabilities: {
    topology_observed: ready('2 operators, 1 edge'),
    actual_input_output_capture: {
      status: 'partial',
      evidence: {},
      scope: 'rerank captured ids only',
      failures: [{ code: 'ids_only', detail: 'rerank recorded candidate ids without content', fix: 'Set capture to content on the rerank hook.', op_id: 'rerank' }],
    },
    candidate_identity: ready('doc_id on every candidate'),
    query_identity: ready('hash of query_text'),
    final_output_capture: ready('search return value'),
    judgment_mapping: ready('bench/qrels.tsv'),
    declared_route_coverage: { status: 'unavailable', evidence: {}, scope: 'no routes declared', failures: [] },
    cross_run_entity_alignment: ready('one run'),
  },
  errors: [],
  observed_operator_ids: ['retrieve', 'rerank'],
  operators: [
    { op_id: 'retrieve', op_type: 'SOURCE', symbol: 'retrieve', relative_path: 'app/search.py', parent_ids: [], confidence: 0.9, input_mapping: 'query_text', output_mapping: 'return', capture: null, invocation: 'sync' },
    { op_id: 'rerank', op_type: 'RERANK', symbol: 'Reranker.rerank', relative_path: 'app/rerank.py', parent_ids: ['retrieve'], confidence: 0.8, input_mapping: 'candidates', output_mapping: 'return', capture: 'ids_only', invocation: 'async' },
  ],
  scenarios: [{ scenario_id: 'smoke', query_text: 'refund policy', expected_operator_ids: ['retrieve', 'rerank'], expected_edges: [['retrieve', 'rerank']], command: 'python -m app.search --query refund-policy', route: null }],
  boundary: { kind: 'entrypoint_return', symbol: 'search', relative_path: 'app/main.py', op_id: null },
  identity: { candidate_id_field: 'doc_id', unit: 'document', namespace: 'catalog', corpus_revision: null, query_id: 'hash:query_text', query_text_parameter: 'query' },
  judgments: { queries: 'bench/queries.jsonl', qrels: 'bench/qrels.tsv', corpus: 'bench/corpus.jsonl', status: 'resolved', notes: [] },
  expected_capabilities: {
    topology_observed: 'ready',
    actual_input_output_capture: 'ready',
    candidate_identity: 'ready',
    query_identity: 'ready',
    final_output_capture: 'ready',
    judgment_mapping: 'ready',
    declared_route_coverage: 'unavailable',
    cross_run_entity_alignment: 'ready',
  },
  actions: [
    { kind: 'install', description: 'Install retobs', command: 'pip install retrieval-observatory', performed_by: 'user' },
    { kind: 'source_edit', description: 'Wrap retrieve and rerank', command: null, performed_by: 'apply' },
    { kind: 'scenario_execution', description: 'Run the smoke query', command: 'python -m app.search --query refund-policy', performed_by: 'user' },
    { kind: 'scenario_execution', description: 'Send one request to POST /search', command: null, performed_by: 'user' },
    { kind: 'benchmark_setup', description: 'Evaluate the benchmark', command: 'retobs evaluate app.search:search --queries bench/queries.jsonl --qrels bench/qrels.tsv', performed_by: 'user' },
  ],
  open_questions: ['app/rerank.py: actual inputs cannot be read statically'],
  unresolved: ['corpus revision'],
  telemetry_health: {},
  release_readiness: {},
  investigation: { run_id: 'run-2026-09-22', pipeline_id: 'hybrid' },
}

const SUMMARIES: IntegrationSummary[] = [
  { integration_id: 'shop-search:hybrid', service_id: 'shop-search', pipeline_id: 'hybrid', plan_id: 'plan-7f3a', status: 'ready', depth: 'internal', verified_at: '2026-09-22T10:15:00+00:00', version: 2 },
  { integration_id: 'shop-search:legacy', service_id: 'shop-search', pipeline_id: 'legacy', plan_id: 'plan-11c0', status: 'failed', depth: 'final_only', verified_at: '2026-09-20T08:00:00+00:00', version: 1 },
]

const panel = (record: IntegrationRecord) => renderToStaticMarkup(<IntegrationPanel db="demo" record={record} />)

describe('IntegrationPanel', () => {
  test('renders the exact setup commands for the selected integration', () => {
    const html = panel(RECORD)
    expect(html).toContain('pip install retrieval-observatory')
    expect(html).toContain('retobs integrate /srv/shop-search --phase plan --output retobs/integration-plan.json')
    expect(html).toContain('retobs integrate /srv/shop-search --phase apply --plan retobs/integration-plan.json')
    expect(html).toContain('retobs integrate /srv/shop-search --phase verify --db /srv/shop-search/retobs/retobs.db')
    expect(html).toContain('python -m app.search --query refund-policy')
    expect(html).toContain('Send one request to POST /search')
    expect(html).toContain('retobs evaluate app.search:search --queries bench/queries.jsonl --qrels bench/qrels.tsv')
  })

  test('renders the plan summary with operators, boundary, identity, judgments and depth', () => {
    const html = panel(RECORD)
    expect(html).toContain('Final output: what <code class="font-mono text-ink">search</code> returns in <code class="font-mono text-ink">app/main.py</code>')
    expect(html).toContain('Candidates identified by <code class="font-mono text-ink">doc_id</code> (document); query id from <code class="font-mono text-ink">hash:query_text</code>')
    expect(html).toContain('bench/queries.jsonl')
    expect(html).toContain('bench/qrels.tsv')
    expect(html).toContain('bench/corpus.jsonl')
    expect(html).toContain('Internal transitions are observed')
    expect(html).not.toContain('Final output only')
    for (const cell of ['Reranker.rerank', 'app/rerank.py', 'candidates', 'query_text', 'return', 'ids_only', '>async<', 'RERANK']) expect(html).toContain(cell)
    expect(html).toContain('>retrieve</td>')

    const finalOnly = panel({
      ...RECORD,
      depth: 'final_only',
      boundary: { kind: 'operator_output', symbol: 'rerank', relative_path: 'app/rerank.py', op_id: 'rerank' },
      judgments: { status: 'unresolved', notes: ['no qrels file found under bench/'] },
    })
    expect(finalOnly).toContain('Final output only: per-stage loss attribution is unavailable until internal operators are instrumented')
    expect(finalOnly).not.toContain('Internal transitions are observed')
    expect(finalOnly).toContain('Final output: the output of operator <code class="font-mono text-ink">rerank</code>')
    expect(finalOnly).toContain('Judgments unresolved')
    expect(finalOnly).toContain('no qrels file found under bench/')
    expect(panel({ ...RECORD, boundary: { kind: 'unresolved', symbol: null, relative_path: null, op_id: null } })).toContain('Final boundary unresolved')
  })

  test('renders eight capability rows with glyph and text and expected-vs-verified differences', () => {
    const html = panel(RECORD)
    expect(html).toContain('aria-label="Verified capabilities of shop-search:hybrid"')
    expect(CAPABILITY_NAMES).toHaveLength(8)
    expect(capabilityLabel('topology_observed')).toBe('Topology observed')
    const positions = CAPABILITY_NAMES.map((name) => html.indexOf(`>${capabilityLabel(name)}<`))
    expect(positions.every((index, i) => index > 0 && (i === 0 || index > positions[i - 1]))).toBe(true)
    expect(html.match(/<th scope="col"/g)?.length).toBeGreaterThanOrEqual(3)
    expect(html).toContain('◐</span> partial')
    expect(html).toContain('●</span> ready')
    expect(html).toContain('○</span> unavailable')
    expect(html).toContain('ids_only</code>')
    expect(html).toContain('rerank recorded candidate ids without content')
    expect(html).toContain('Set capture to content on the rerank hook.')
    expect(html.match(/expected ready/g)).toHaveLength(1)
    expect(html).not.toContain('expected unavailable')
  })

  test('lists unresolved mappings and open questions or None', () => {
    const html = panel(RECORD)
    expect(html).toContain('corpus revision')
    expect(html).toContain('app/rerank.py: actual inputs cannot be read statically')
    expect(html).not.toContain('>None<')
    const empty = panel({ ...RECORD, unresolved: [], open_questions: [] })
    expect(empty.match(/>None</g)).toHaveLength(2)
  })

  test('links the first investigation when a run exists, else shows the evaluate command', () => {
    const html = panel(RECORD)
    const href = investigateLink({ db: 'demo', run: 'run-2026-09-22', pipeline: 'hybrid' }).replace(/&/g, '&amp;')
    expect(html).toContain(`href="${href}"`)
    expect(html).toContain('Open the first investigation')
    expect(html).not.toContain('No run for this pipeline yet.')

    const noRun = panel({ ...RECORD, investigation: null })
    expect(noRun).not.toContain('Open the first investigation')
    expect(noRun).toContain('No run for this pipeline yet.')
    expect(noRun).toContain('retobs evaluate app.search:search --queries bench/queries.jsonl --qrels bench/qrels.tsv')
    expect(noRun).toContain('then verify again')
  })

  test('lists verification errors when present', () => {
    expect(panel(RECORD)).not.toContain('Errors')
    expect(panel({ ...RECORD, errors: ['scenario smoke: rerank was not observed'] })).toContain('scenario smoke: rerank was not observed')
  })
})

describe('IntegrationList', () => {
  test('integration list links each record into Connect with the db and integration in the hash', () => {
    const html = renderToStaticMarkup(<IntegrationList db="demo" integrations={SUMMARIES} />)
    for (const item of SUMMARIES) {
      const href = buildHash('connect', { db: 'demo', integration: item.integration_id })
      expect(href).toContain('#/connect?')
      expect(href).toContain('db=demo')
      expect(href).toContain(`integration=${encodeURIComponent(item.integration_id)}`)
      expect(html).toContain(`href="${href.replace(/&/g, '&amp;')}"`)
    }
    expect(html).toContain('shop-search · hybrid')
    expect(html).toContain('shop-search · legacy')
    expect(html).toContain('●</span> ready')
    expect(html).toContain('○</span> failed')
    expect(html).toContain('internal transitions')
    expect(html).toContain('final output only')
    expect(html).toContain('<time dateTime="2026-09-22T10:15:00+00:00">')
  })

  test('says so when the database holds no verified integration', () => {
    const html = renderToStaticMarkup(<IntegrationList db="demo" integrations={[]} />)
    expect(html).toContain('No verified integration in this database yet.')
    expect(html).toContain('retobs integrate . --phase verify')
  })
})

test('AGENT_REQUEST is unchanged', () => {
  expect(AGENT_REQUEST).toBe(
    'Ask your coding agent to connect retobs to this existing retrieval pipeline, run your benchmark, and open a document-flow investigation.',
  )
})
