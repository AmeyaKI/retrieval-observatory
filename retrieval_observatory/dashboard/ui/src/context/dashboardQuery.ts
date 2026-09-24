// URL scope for the focused dashboard (master plan 2.3). The hash query string is the
// single source of truth: every field round-trips through parse/serialize, keys are
// written in one fixed order, and changing a parent scope (db, run) clears the fields
// that only mean something inside it (applySelectionPatch). `compare` names the baseline
// run Investigate diffs the selected (candidate) run against; it is run-scoped.

export type InvestigateView = 'queries' | 'documents'

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
}

const VIEWS: readonly InvestigateView[] = ['queries', 'documents']

/** Fixed serialisation order. */
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
] as const

/** Fields that only mean something inside one run. */
export const RUN_SCOPED_KEYS = ['pipeline', 'query', 'trace', 'entity', 'stage', 'outcome', 'compare'] as const
/** Fields that only mean something inside one database. */
export const DB_SCOPED_KEYS = ['run', ...RUN_SCOPED_KEYS, 'baseline', 'candidate'] as const

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
  }
}

/** Serialise in SELECTION_KEY_ORDER, omitting empty values and defaults (`view=queries`). Values use encodeURIComponent so `/`, `:`, `#`, spaces and unicode are safe. */
export function serializeDashboardQuery(s: DashboardSelection): string {
  const pairs: string[] = []
  for (const key of SELECTION_KEY_ORDER) {
    const value = s[key]
    if (!value || value === DEFAULT_SELECTION[key]) continue
    pairs.push(`${key}=${encodeURIComponent(value)}`)
  }
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
