import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'
// api.ts reads window.location.origin at import time and useTheme reads the <html> class
// list on first render; the node test environment has neither.
vi.hoisted(() => {
  const g = globalThis as { window?: unknown; document?: unknown }
  g.window = { location: { origin: 'http://localhost' } }
  g.document = { documentElement: { classList: { contains: () => false, add() {}, remove() {} } } }
})
import ModeRail from './ModeRail'
import MigrationNotice from './MigrationNotice'
import { describeInvestigationError, OUTCOME_LABELS, pipelineIdsFromDetail } from './InvestigateWorkspace'
import { pipelineIdsFromConfig } from './GlobalContextBar'
import {
  applySelectionPatch,
  DashboardSelection,
  DEFAULT_SELECTION,
  parseDashboardQuery,
  serializeDashboardQuery,
} from '../context/dashboardQuery'
import { auditLink, buildHash, investigateLink, landingWorkspace, parseFocusedHash, RETIRED_MESSAGES } from '../utils/focusedRoutes'

const RUN = 'exp/2026:a b' // contains "/", ":" and a space
const RUN_ENC = encodeURIComponent(RUN) // exp%2F2026%3Aa%20b

describe('parseFocusedHash: workspaces', () => {
  test('each feature route resolves to its workspace with the scope it carries', () => {
    const investigate = parseFocusedHash('#/investigate?db=main&run=r1&pipeline=hybrid&view=documents&entity=docs%3Ad1&stage=rerank&outcome=relevant_excluded')
    expect(investigate.workspace).toBe('investigate')
    expect(investigate.redirectTo).toBeUndefined()
    expect(investigate.selection).toMatchObject({
      db: 'main',
      run: 'r1',
      pipeline: 'hybrid',
      view: 'documents',
      entity: 'docs:d1',
      stage: 'rerank',
      outcome: 'relevant_excluded',
    })

    const connect = parseFocusedHash('#/connect?db=main&integration=int-1')
    expect(connect.workspace).toBe('connect')
    expect(connect.selection).toMatchObject({ db: 'main', integration: 'int-1' })

    const audit = parseFocusedHash('#/audit?db=main&baseline=b1&candidate=c1&policy=sha256%3Aabc')
    expect(audit.workspace).toBe('audit')
    expect(audit.selection).toMatchObject({ db: 'main', baseline: 'b1', candidate: 'c1', policy: 'sha256:abc' })

    expect(parseFocusedHash('#/help').workspace).toBe('help')
  })

  test('the empty hash and "#/" are the landing decision, never a workspace guess', () => {
    expect(parseFocusedHash('').workspace).toBe('landing')
    expect(parseFocusedHash('#').workspace).toBe('landing')
    expect(parseFocusedHash('#/').workspace).toBe('landing')
    expect(parseFocusedHash('#/?db=main').selection.db).toBe('main')
  })

  test('an unknown hash renders a generic migration notice', () => {
    const route = parseFocusedHash('#/whatever/else')
    expect(route.workspace).toBe('migration')
    expect(route.retired).toEqual({ destination: '#/whatever/else', replacement: 'investigate', message: RETIRED_MESSAGES.unknown })
    expect(parseFocusedHash('#/investigate/extra').workspace).toBe('migration')
  })
})

describe('parseFocusedHash: legacy redirects (lossless only)', () => {
  const cases: Array<[string, string]> = [
    [`#/runs/${RUN_ENC}`, `#/investigate?run=${RUN_ENC}`],
    [`#/runs/${RUN_ENC}/queries`, `#/investigate?run=${RUN_ENC}&view=queries`],
    [`#/runs/${RUN_ENC}/queries/q%3A1`, `#/investigate?run=${RUN_ENC}&view=queries&query=q%3A1`],
    [`#/runs/${RUN_ENC}/queries/q%3A1/candidates/doc%2F7`, `#/investigate?run=${RUN_ENC}&view=queries&query=q%3A1&entity=doc%2F7`],
    [`#/runs/${RUN_ENC}/documents`, `#/investigate?run=${RUN_ENC}&view=documents`],
    [`#/benchmarks/run/${RUN_ENC}/queries/q%3A1`, `#/investigate?run=${RUN_ENC}&view=queries&query=q%3A1`],
    ['#/runs', '#/investigate'],
    ['#/benchmarks', '#/investigate'],
    ['#/compare', '#/audit'],
    ['#/glossary', '#/help'],
  ]
  test.each(cases)('%s → %s', (from, to) => {
    const route = parseFocusedHash(from)
    expect(route.redirectTo).toBe(to)
    expect(route.workspace).toBe(parseFocusedHash(to).workspace)
    // The redirect target parses to the same ids the legacy path encoded.
    expect(route.selection).toEqual(parseFocusedHash(to).selection)
  })

  test('ids survive the redirect exactly', () => {
    const route = parseFocusedHash(`#/runs/${RUN_ENC}/queries/q%3A1/candidates/doc%2F7`)
    expect(route.selection).toMatchObject({ run: RUN, query: 'q:1', entity: 'doc/7', view: 'queries' })
  })

  test('an existing db parameter is preserved across the redirect, other legacy params are dropped', () => {
    expect(parseFocusedHash('#/runs/r1?db=main&window=7d').redirectTo).toBe('#/investigate?db=main&run=r1')
    expect(parseFocusedHash('#/runs/r1/queries/q1?db=main').redirectTo).toBe('#/investigate?db=main&run=r1&view=queries&query=q1')
    expect(parseFocusedHash('#/compare?db=main&cohort=hard').redirectTo).toBe('#/audit?db=main')
    expect(parseFocusedHash('#/glossary?db=main').redirectTo).toBe('#/help?db=main')
    expect(parseFocusedHash('#/runs?db=main').redirectTo).toBe('#/investigate?db=main')
  })
})

describe('parseFocusedHash: retired destinations', () => {
  const cases: Array<[string, 'investigate' | 'connect' | 'audit', string]> = [
    ['#/home', 'investigate', RETIRED_MESSAGES.home],
    ['#/queries', 'investigate', RETIRED_MESSAGES.queries],
    ['#/queries/q1', 'investigate', RETIRED_MESSAGES.queries],
    ['#/production', 'investigate', RETIRED_MESSAGES.production],
    ['#/production/traces/t1', 'investigate', RETIRED_MESSAGES.production],
    ['#/test-sets', 'connect', RETIRED_MESSAGES.testSets],
    ['#/test-sets/ds1', 'connect', RETIRED_MESSAGES.testSets],
    ['#/runs/r1/attribution', 'investigate', RETIRED_MESSAGES.attribution],
    ['#/runs/r1/quality', 'investigate', RETIRED_MESSAGES.quality],
    ['#/runs/r1/architecture', 'investigate', RETIRED_MESSAGES.architecture],
    ['#/runs/r1/analysis/gates', 'investigate', RETIRED_MESSAGES.analysis],
    ['#/runs/r1/tradeoffs', 'audit', RETIRED_MESSAGES.tradeoffs],
    ['#/runs/r1/queries/q1/diff', 'audit', RETIRED_MESSAGES.queryDiff],
  ]
  test.each(cases)('%s → migration notice pointing at %s', (hash, replacement, message) => {
    const route = parseFocusedHash(hash)
    expect(route.workspace).toBe('migration')
    expect(route.redirectTo).toBeUndefined()
    expect(route.retired).toEqual({ destination: hash, replacement, message })
  })

  test('a retired destination keeps the db it carried for the recovery link', () => {
    const route = parseFocusedHash('#/runs/r1/tradeoffs?db=main')
    expect(route.retired?.replacement).toBe('audit')
    expect(route.selection.db).toBe('main')
    expect(buildHash(route.retired!.replacement, { db: route.selection.db })).toBe('#/audit?db=main')
  })
})

describe('URL scope round-trips', () => {
  const full: DashboardSelection = {
    db: 'main',
    run: 'r/1',
    pipeline: 'hybrid:v2',
    view: 'documents',
    query: 'q 1',
    trace: 't#1',
    entity: 'docs:d/é',
    stage: 'rerank',
    outcome: 'relevant_excluded',
    compare: 'b0',
    baseline: 'b',
    candidate: 'c',
    policy: 'sha256:abc',
    integration: 'int-1',
  }

  test('every field survives serialize → parse, including ids with /, :, #, spaces and unicode', () => {
    expect(parseDashboardQuery(serializeDashboardQuery(full))).toEqual(full)
  })

  test('serialisation uses one fixed key order and omits defaults', () => {
    expect(serializeDashboardQuery(full)).toBe(
      'db=main&run=r%2F1&pipeline=hybrid%3Av2&view=documents&query=q%201&trace=t%231&entity=docs%3Ad%2F%C3%A9&stage=rerank&outcome=relevant_excluded&compare=b0&baseline=b&candidate=c&policy=sha256%3Aabc&integration=int-1',
    )
    expect(serializeDashboardQuery({ ...DEFAULT_SELECTION, db: 'main', run: 'r1' })).toBe('db=main&run=r1')
    expect(serializeDashboardQuery(DEFAULT_SELECTION)).toBe('')
  })

  test('parse tolerates "+" for spaces, empty values and a leading "?"', () => {
    expect(parseDashboardQuery('?query=q+1&run=').query).toBe('q 1')
    expect(parseDashboardQuery('?query=q+1&run=').run).toBeNull()
    expect(parseDashboardQuery('view=bogus').view).toBe('queries')
  })

  test('the server-style investigation link parses into the expected selection', () => {
    const route = parseFocusedHash('#/investigate?run=r1&pipeline=bm25&view=queries&query=q%3A1&trace=t1&entity=docs%3Ad1&compare=b0')
    expect(route.workspace).toBe('investigate')
    expect(route.selection).toEqual({
      ...DEFAULT_SELECTION,
      run: 'r1',
      pipeline: 'bm25',
      view: 'queries',
      query: 'q:1',
      trace: 't1',
      entity: 'docs:d1',
      compare: 'b0',
    })
  })

  test('investigateLink output re-parses to the same selection and matches the server shape', () => {
    const target = { db: 'main', run: RUN, pipeline: 'bm25', query: 'q:1', trace: 't 1', entity: 'docs:d/1', compare: 'b0' }
    const link = investigateLink(target)
    expect(link).toBe(`#/investigate?db=main&run=${RUN_ENC}&pipeline=bm25&view=queries&query=q%3A1&trace=t%201&entity=docs%3Ad%2F1&compare=b0`)
    expect(parseFocusedHash(link).selection).toEqual({ ...DEFAULT_SELECTION, ...target, view: 'queries' })
    expect(investigateLink({ run: 'r1', view: 'documents', entity: 'docs:d1' })).toBe('#/investigate?run=r1&view=documents&entity=docs%3Ad1')
  })

  test('auditLink names the baseline and candidate under the audit path', () => {
    expect(auditLink({ db: 'main', baseline: 'b', candidate: 'c' })).toBe('#/audit?db=main&baseline=b&candidate=c')
    expect(parseFocusedHash(auditLink({ db: 'main', baseline: 'b', candidate: 'c' })).selection).toMatchObject({ db: 'main', baseline: 'b', candidate: 'c' })
  })

  test('buildHash serialises a partial selection under the workspace path', () => {
    expect(buildHash('investigate', { db: 'main', run: 'r1', view: 'queries' })).toBe('#/investigate?db=main&run=r1')
    expect(buildHash('connect')).toBe('#/connect')
    expect(buildHash('audit', { db: 'main', baseline: 'b', candidate: 'c', policy: undefined })).toBe('#/audit?db=main&baseline=b&candidate=c')
    expect(buildHash('help', { db: 'main' })).toBe('#/help?db=main')
  })
})

describe('landingWorkspace', () => {
  test('no runs anywhere → connect; any database with runs → investigate', () => {
    expect(landingWorkspace([])).toBe('connect')
    expect(landingWorkspace([{ run_count: 0 }])).toBe('connect')
    expect(landingWorkspace([{ run_count: 0 }, { run_count: 2 }])).toBe('investigate')
  })
})

describe('applySelectionPatch', () => {
  const prev: DashboardSelection = {
    ...DEFAULT_SELECTION,
    db: 'main',
    run: 'r1',
    pipeline: 'p',
    view: 'documents',
    query: 'q',
    trace: 't',
    entity: 'e',
    stage: 's',
    outcome: 'unjudged',
    compare: 'b0',
    baseline: 'b',
    candidate: 'c',
    policy: 'pol',
    integration: 'int',
  }

  test('a different run clears pipeline, query, trace, entity, stage, outcome and compare only', () => {
    expect(applySelectionPatch(prev, { run: 'r2' })).toEqual({
      ...prev,
      run: 'r2',
      pipeline: null,
      query: null,
      trace: null,
      entity: null,
      stage: null,
      outcome: null,
      compare: null,
    })
  })

  test('the same run, or a patch without run/db, leaves the dependent fields alone', () => {
    expect(applySelectionPatch(prev, { run: 'r1' })).toEqual(prev)
    expect(applySelectionPatch(prev, { view: 'queries' })).toEqual({ ...prev, view: 'queries' })
    expect(applySelectionPatch(prev, { query: 'q2', trace: undefined })).toEqual({ ...prev, query: 'q2' })
  })

  test('a different db clears the run, everything under it, and baseline/candidate', () => {
    expect(applySelectionPatch(prev, { db: 'other' })).toEqual({
      ...prev,
      db: 'other',
      run: null,
      pipeline: null,
      query: null,
      trace: null,
      entity: null,
      stage: null,
      outcome: null,
      compare: null,
      baseline: null,
      candidate: null,
    })
    expect(applySelectionPatch(prev, { db: 'main' })).toEqual(prev)
  })

  test('fields the patch sets explicitly win over the reset', () => {
    expect(applySelectionPatch(prev, { run: 'r2', query: 'q9' })).toMatchObject({ run: 'r2', query: 'q9', entity: null })
  })
})

describe('ModeRail', () => {
  test('exactly three primary destinations, a Help link, and no retired entries', () => {
    const html = renderToStaticMarkup(<ModeRail mode="investigate" onSelect={() => {}} />)
    expect(html.match(/data-mode="/g)).toHaveLength(3)
    expect(html).toContain('data-mode="investigate"')
    expect(html).toContain('data-mode="connect"')
    expect(html).toContain('data-mode="audit"')
    expect(html).toContain('>Investigate<')
    expect(html).toContain('>Connect<')
    expect(html).toContain('>Audit<')
    expect(html.match(/aria-current="page"/g)).toHaveLength(1)
    expect(html).toContain('href="#/help"')
    for (const retired of ['Tour', 'Runs', 'Production', 'Test Sets', 'Compare', 'Home', 'Glossary']) {
      expect(html).not.toContain(retired)
    }
  })

  test('Help is current on the help route and the brand is not a link', () => {
    const html = renderToStaticMarkup(<ModeRail mode="help" onSelect={() => {}} helpHref="#/help?db=main" />)
    expect(html).toContain('href="#/help?db=main" data-utility="help" aria-current="page"')
    expect(html).not.toContain('href="#/home"')
    expect(html).toContain('title="Retrieval Observatory"')
  })
})

describe('MigrationNotice', () => {
  test('names the retired destination and links to the replacement workspace', () => {
    const html = renderToStaticMarkup(
      <MigrationNotice destination="#/home" replacement="investigate" message={RETIRED_MESSAGES.home} href="#/investigate?db=main" />,
    )
    expect(html).toContain('role="note"')
    expect(html).toContain('#/home')
    expect(html).toContain(RETIRED_MESSAGES.home)
    expect(html).toContain('href="#/investigate?db=main"')
    expect(html).toContain('Open Investigate')
    expect(html).toContain('href="https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/guides/migrating-to-focused-retobs.md"')
    expect(html).toContain('Learn more')
  })
})

describe('Investigate helpers', () => {
  test('recovers the service error code and pipeline ids from a 422 pipeline_required body', () => {
    const error = describeInvestigationError(
      new Error(
        'fetchInvestigationQueries: 422 Unprocessable Entity — {"detail":{"code":"pipeline_required","detail":"run \'r1\' has pipelines [\'bm25\', \'hybrid\']; pass pipeline_id"}}',
      ),
    )
    expect(error).toMatchObject({ status: 422, code: 'pipeline_required' })
    expect(pipelineIdsFromDetail(error.detail)).toEqual(['bm25', 'hybrid'])
    expect(pipelineIdsFromDetail('["a", "b"]')).toEqual(['a', 'b'])
    expect(pipelineIdsFromDetail(null)).toEqual([])
  })

  test('a 409 is read-only even when the body is truncated', () => {
    const truncated = describeInvestigationError(new Error('buildInvestigationProjection: 409 Conflict — {"detail":{"code":"read_only","det'))
    expect(truncated).toMatchObject({ status: 409, code: 'read_only' })
    const network = describeInvestigationError(new TypeError('Failed to fetch'))
    expect(network).toMatchObject({ status: null, code: null, message: 'Failed to fetch' })
  })

  test('pipeline ids come from the run config the service resolves against', () => {
    expect(pipelineIdsFromConfig('{"pipelines":[{"id":"bm25"},{"id":"hybrid"},{}]}')).toEqual(['bm25', 'hybrid'])
    expect(pipelineIdsFromConfig('{"experiment":{}}')).toEqual([])
    expect(pipelineIdsFromConfig('not json')).toEqual([])
    expect(pipelineIdsFromConfig(undefined)).toEqual([])
  })

  test('every outcome has a glyph and a text label (never colour alone)', () => {
    for (const outcome of [
      'relevant_delivered',
      'relevant_excluded',
      'retained_below_cutoff',
      'not_observed',
      'judged_nonrelevant',
      'unjudged',
      'insufficient_evidence',
    ] as const) {
      expect(OUTCOME_LABELS[outcome].glyph.length).toBeGreaterThan(0)
      expect(OUTCOME_LABELS[outcome].label.length).toBeGreaterThan(0)
    }
  })
})
