// Pure hash routing for the focused dashboard (master plan 2.2–2.3): three feature
// workspaces (Investigate, Connect, Audit), two utilities (Help, migration notices),
// one-release-cycle redirects for legacy links whose meaning maps losslessly, and a
// migration notice for everything that was retired. No window access: the shell owns
// the side effects (replaceState, hashchange).

import {
  DashboardSelection,
  DEFAULT_SELECTION,
  InvestigateView,
  parseDashboardQuery,
  serializeDashboardQuery,
} from '../context/dashboardQuery'

export type Workspace = 'investigate' | 'connect' | 'audit' | 'help' | 'migration'
/** What a hash resolves to: a workspace, or the landing decision that waits for the database list. */
export type RouteTarget = Workspace | 'landing'

export interface RetiredDestination {
  /** The hash the user arrived on, e.g. `#/home`. */
  destination: string
  replacement: Workspace
  message: string
}

export interface FocusedRoute {
  workspace: RouteTarget
  /** The hash's query string without the leading "?" (of the redirect target when one applies). */
  query: string
  /** The scope the hash carries (of the redirect target when one applies). */
  selection: DashboardSelection
  /** A lossless legacy mapping; the shell replaces the URL with this before rendering. */
  redirectTo?: string
  /** A retired destination, rendered as a migration notice. */
  retired?: RetiredDestination
}

export const WORKSPACE_LABELS: Record<Workspace, string> = {
  investigate: 'Investigate',
  connect: 'Connect',
  audit: 'Audit',
  help: 'Help',
  migration: 'Migration notice',
}

export function workspaceLabel(workspace: Workspace): string {
  return WORKSPACE_LABELS[workspace]
}

/** Relative to the dashboard origin; the guide arrives with the migration docs task. */
export const MIGRATION_GUIDE_HREF = 'https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/guides/migrating-to-focused-retobs.md'

export const RETIRED_MESSAGES = {
  home: 'The Home page was retired. Investigate opens directly on the selected run; Connect covers setup when no runs exist.',
  queries:
    'Query pages outside a run were retired. Queries are investigated inside one run: choose the run in Investigate, then open the query.',
  production: 'The Production workspace was retired. Investigate reads the same captured traces for the selected run.',
  testSets: 'Test Sets were retired. Connect covers benchmark setup for an existing retrieval pipeline.',
  attribution:
    'Operator attribution pages were retired. Investigate shows each candidate’s recorded transitions and loss boundary per query.',
  quality: 'The Quality page was retired. Investigate reports judgments and outcomes per query together with capture completeness.',
  architecture: 'The Architecture page was retired. Investigate shows the executed pipeline for the selected run.',
  analysis: 'Analysis products were retired. Investigate holds the retained evidence for this run.',
  tradeoffs: 'Tradeoff pages were retired. Audit compares a baseline and a candidate run against declared tolerances.',
  queryDiff: 'Per-query diff pages were retired. Audit compares a baseline and a candidate run and links each failed check to Investigate.',
  unknown: 'This address is not a retobs destination. The dashboard has three workflows: Investigate, Connect, and Audit.',
} as const

export function landingWorkspace(dbs: ReadonlyArray<{ run_count: number }>): 'investigate' | 'connect' {
  return dbs.some((db) => db.run_count > 0) ? 'investigate' : 'connect'
}

function stripUndefined<T extends object>(value: T): Partial<T> {
  const out: Partial<T> = {}
  for (const [key, item] of Object.entries(value)) {
    if (item !== undefined) (out as Record<string, unknown>)[key] = item
  }
  return out
}

/** `#/<workspace>?<scope>`; the scope is serialised in the fixed key order. */
export function buildHash(workspace: Workspace, selection: Partial<DashboardSelection> = {}): string {
  if (workspace === 'migration') return '#/'
  const query = serializeDashboardQuery({ ...DEFAULT_SELECTION, ...stripUndefined(selection) })
  return query ? `#/${workspace}?${query}` : `#/${workspace}`
}

type Pair = [string, string | null | undefined]

function encodePairs(pairs: Pair[]): string {
  return pairs
    .filter((pair): pair is [string, string] => typeof pair[1] === 'string' && pair[1] !== '')
    .map(([key, value]) => `${key}=${encodeURIComponent(value)}`)
    .join('&')
}

export interface InvestigateTarget {
  db?: string | null
  run: string | null
  pipeline?: string | null
  view?: InvestigateView | null
  query?: string | null
  trace?: string | null
  entity?: string | null
  /** Baseline run to diff `run` (the candidate) against. */
  compare?: string | null
}

/** The one link shape into Investigate, identical to the server's `JourneyRow.investigation_link`
 * (`#/investigate?run=…&pipeline=…&view=queries&query=…&trace=…&entity=…`, plus `db` first when known
 * and `compare=…` last when the queries view should diff the run against a baseline). */
export function investigateLink(target: InvestigateTarget): string {
  return `#/investigate?${encodePairs([
    ['db', target.db],
    ['run', target.run],
    ['pipeline', target.pipeline],
    ['view', target.view ?? 'queries'],
    ['query', target.query],
    ['trace', target.trace],
    ['entity', target.entity],
    ['compare', target.compare],
  ])}`
}

/** The one link shape into Audit: `#/audit?db=…&baseline=…&candidate=…`. */
export function auditLink({ db, baseline, candidate }: { db?: string | null; baseline: string | null; candidate: string | null }): string {
  return buildHash('audit', { db, baseline, candidate })
}

function splitHash(hash: string): { path: string; query: string } {
  const raw = hash.startsWith('#') ? hash.slice(1) : hash
  const at = raw.indexOf('?')
  const query = at >= 0 ? raw.slice(at + 1) : ''
  const path = (at >= 0 ? raw.slice(0, at) : raw).replace(/^\/+/, '').replace(/\/+$/, '')
  return { path, query }
}

function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment)
  } catch {
    return segment
  }
}

export function parseFocusedHash(hash: string): FocusedRoute {
  const { path, query } = splitHash(hash)
  const selection = parseDashboardQuery(query)
  const base = { query, selection }
  const destination = `#/${path}`

  const redirect = (workspace: Workspace, to: string): FocusedRoute => {
    const target = splitHash(to)
    return { workspace, query: target.query, selection: parseDashboardQuery(target.query), redirectTo: to }
  }
  const retired = (replacement: Workspace, message: string): FocusedRoute => ({
    ...base,
    workspace: 'migration',
    retired: { destination, replacement, message },
  })

  // Segments are split before decoding so an encoded "/" inside an id never splits.
  let segments = path.split('/').filter(Boolean).map(safeDecode)
  if (segments[0] === 'benchmarks' && (segments.length === 1 || segments[1] === 'run')) {
    segments = ['runs', ...segments.slice(2)]
  }
  const [head, ...rest] = segments
  const carried = { db: selection.db }

  if (!head) return { ...base, workspace: 'landing' }

  switch (head) {
    case 'investigate':
    case 'connect':
    case 'audit':
    case 'help':
      if (rest.length === 0) return { ...base, workspace: head }
      break
    case 'glossary':
      return redirect('help', buildHash('help', carried))
    case 'compare':
      return redirect('audit', buildHash('audit', carried))
    case 'runs': {
      const route = runsRoute(rest, selection.db, redirect, retired)
      if (route) return route
      break
    }
    case 'home':
      return retired('investigate', RETIRED_MESSAGES.home)
    case 'queries':
      return retired('investigate', RETIRED_MESSAGES.queries)
    case 'production':
      return retired('investigate', RETIRED_MESSAGES.production)
    case 'test-sets':
      return retired('connect', RETIRED_MESSAGES.testSets)
  }
  return retired('investigate', RETIRED_MESSAGES.unknown)
}

function runsRoute(
  rest: string[],
  db: string | null,
  redirect: (workspace: Workspace, to: string) => FocusedRoute,
  retired: (replacement: Workspace, message: string) => FocusedRoute,
): FocusedRoute | null {
  const [run, page, ...tail] = rest
  const link = (extra: Pair[]) => `#/investigate?${encodePairs([['db', db], ['run', run], ...extra])}`

  if (!run) return redirect('investigate', buildHash('investigate', { db }))
  if (!page) return redirect('investigate', link([]))
  if (page === 'queries') {
    const [queryId, sub, docId] = tail
    if (tail.length === 0) return redirect('investigate', link([['view', 'queries']]))
    if (tail.length === 1) return redirect('investigate', link([['view', 'queries'], ['query', queryId]]))
    if (tail.length === 3 && sub === 'candidates') {
      return redirect('investigate', link([['view', 'queries'], ['query', queryId], ['entity', docId]]))
    }
    if (tail.length === 2 && sub === 'diff') return retired('audit', RETIRED_MESSAGES.queryDiff)
    return null
  }
  if (page === 'documents' && tail.length === 0) return redirect('investigate', link([['view', 'documents']]))
  if (page === 'tradeoffs') return retired('audit', RETIRED_MESSAGES.tradeoffs)
  if (page === 'attribution' || page === 'quality' || page === 'architecture' || page === 'analysis') {
    return retired('investigate', RETIRED_MESSAGES[page])
  }
  return null
}
