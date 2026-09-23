// URL scope for the focused dashboard (master plan 2.3). The hash query string is the
// single source of truth: every field round-trips through parse/serialize, keys are
// written in one fixed order, and changing a parent scope (db, run) clears the fields
// that only mean something inside it (applySelectionPatch). `compare` names the baseline
// run Investigate diffs the selected (candidate) run against; it is run-scoped.

export type InvestigateView = 'queries' | 'documents'
export type TimeWindow = '24h' | '7d' | '30d' | 'all' | 'custom'

export interface DashboardSelection {
  db: string | null
  run: string | null
  pipeline: string | null
  view: InvestigateView
  query: string | null
  trace: string | null
  entity: string | null
  stage: string | null
  outcome: string | null
  compare: string | null
  baseline: string | null
  candidate: string | null
  policy: string | null
  integration: string | null
  // Retained legacy fields: production/analysis components still read them.
  service: string | null
  window: TimeWindow
  since: string | null
  until: string | null
  cohort: string | null
  filters: string[]
}

export const DEFAULT_SELECTION: DashboardSelection = {
  db: null,
  run: null,
  pipeline: null,
  view: 'queries',
  query: null,
  trace: null,
  entity: null,
  stage: null,
  outcome: null,
  compare: null,
  baseline: null,
  candidate: null,
  policy: null,
  integration: null,
  service: null,
  window: '7d',
  since: null,
  until: null,
  cohort: null,
  filters: [],
}

const VIEWS: readonly InvestigateView[] = ['queries', 'documents']
const WINDOWS: readonly TimeWindow[] = ['24h', '7d', '30d', 'all', 'custom']

/** Fixed serialisation order; the repeatable `filter` key always comes last. */
export const SELECTION_KEY_ORDER = [
  'db',
  'run',
  'pipeline',
  'view',
  'query',
  'trace',
  'entity',
  'stage',
  'outcome',
  'compare',
  'baseline',
  'candidate',
  'policy',
  'integration',
  'service',
  'window',
  'since',
  'until',
  'cohort',
] as const

/** Fields that only mean something inside one run. */
export const RUN_SCOPED_KEYS = ['pipeline', 'query', 'trace', 'entity', 'stage', 'outcome', 'compare'] as const
/** Fields that only mean something inside one database. */
export const DB_SCOPED_KEYS = ['run', ...RUN_SCOPED_KEYS, 'baseline', 'candidate', 'service', 'cohort'] as const

function text(q: URLSearchParams, key: string, fallback: string | null): string | null {
  const value = q.get(key)
  if (value === null) return fallback
  return value === '' ? null : value
}

/** Parse a hash query string (with or without a leading "?"). Values are percent-decoded
 * by URLSearchParams, which accepts both `%20` (encodeURIComponent, Python `quote`) and `+`. */
export function parseDashboardQuery(raw: string, base: DashboardSelection = DEFAULT_SELECTION): DashboardSelection {
  const q = new URLSearchParams(raw.startsWith('?') ? raw.slice(1) : raw)
  const view = q.get('view')
  const window = q.get('window')
  const filters = q.getAll('filter')
  return {
    ...base,
    db: text(q, 'db', base.db),
    run: text(q, 'run', base.run),
    pipeline: text(q, 'pipeline', base.pipeline),
    view: VIEWS.includes(view as InvestigateView) ? (view as InvestigateView) : base.view,
    query: text(q, 'query', base.query),
    trace: text(q, 'trace', base.trace),
    entity: text(q, 'entity', base.entity),
    stage: text(q, 'stage', base.stage),
    outcome: text(q, 'outcome', base.outcome),
    compare: text(q, 'compare', base.compare),
    baseline: text(q, 'baseline', base.baseline),
    candidate: text(q, 'candidate', base.candidate),
    policy: text(q, 'policy', base.policy),
    integration: text(q, 'integration', base.integration),
    service: text(q, 'service', base.service),
    window: WINDOWS.includes(window as TimeWindow) ? (window as TimeWindow) : base.window,
    since: text(q, 'since', base.since),
    until: text(q, 'until', base.until),
    cohort: text(q, 'cohort', base.cohort),
    filters: filters.length ? filters : base.filters,
  }
}

/** Serialise in SELECTION_KEY_ORDER, omitting empty values and defaults (`view=queries`,
 * `window=7d`). Values use encodeURIComponent so `/`, `:`, `#`, spaces and unicode are safe. */
export function serializeDashboardQuery(s: DashboardSelection): string {
  const pairs: string[] = []
  for (const key of SELECTION_KEY_ORDER) {
    const value = s[key]
    if (!value || value === DEFAULT_SELECTION[key]) continue
    pairs.push(`${key}=${encodeURIComponent(value)}`)
  }
  for (const value of [...s.filters].sort()) pairs.push(`filter=${encodeURIComponent(value)}`)
  return pairs.join('&')
}

/** Apply a partial update with the scope reset rules: a different `db` clears the run and
 * everything under it plus baseline/candidate; a different `run` clears the run-scoped
 * fields. Keys the patch sets explicitly always win over the reset. `undefined` values in
 * the patch are ignored. */
export function applySelectionPatch(prev: DashboardSelection, patch: Partial<DashboardSelection>): DashboardSelection {
  const clean: Partial<DashboardSelection> = {}
  for (const [key, value] of Object.entries(patch)) {
    if (value !== undefined) (clean as Record<string, unknown>)[key] = value
  }
  const reset: Partial<DashboardSelection> = {}
  if ('db' in clean && clean.db !== prev.db) {
    for (const key of DB_SCOPED_KEYS) reset[key] = null
  } else if ('run' in clean && clean.run !== prev.run) {
    for (const key of RUN_SCOPED_KEYS) reset[key] = null
  }
  return { ...prev, ...reset, ...clean }
}
