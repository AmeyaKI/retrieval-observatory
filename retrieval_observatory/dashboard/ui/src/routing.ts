// Zero-dependency hash router (RETOBS_FINER_PLAN_PHASE2.md, Item B). AppShell.tsx already
// hand-rolls a one-segment hash parser (mode + rest); this generalizes that into a real
// multi-segment path-and-query matcher instead of adding react-router-dom -- no routing
// dependency exists in package.json today (only react/react-dom/recharts), and this
// achieves the same deep-linkability/refresh-survival the vision requires without a
// dependency + rewrite-everything migration for marginal gain.

export interface RouteMatch {
  routeId: string
  params: Record<string, string>
  query: Record<string, string>
}

/** Translate legacy product-module hashes to the unified task navigation. */
export function migrateLegacyPath(path: string): string {
  const normalized = path.replace(/^#\/?/, '').replace(/^\//, '')
  if (normalized === 'benchmarks') return 'runs'
  if (normalized.startsWith('benchmarks/run/')) return `runs/${normalized.slice('benchmarks/run/'.length)}`
  if (normalized === 'forge') return 'test-sets'
  if (normalized.startsWith('forge/')) return `test-sets/${normalized.slice('forge/'.length)}`
  if (normalized === 'tracelens') return 'production'
  if (normalized.startsWith('tracelens/')) return `production/${normalized.slice('tracelens/'.length)}`
  if (normalized === 'advisor' || normalized.startsWith('advisor/')) return 'runs'
  if (normalized.startsWith('query/')) return `queries/${normalized.slice('query/'.length)}`
  return normalized
}

interface RouteDef {
  routeId: string
  segments: string[] // literal segments, or ":param" for a captured segment
}

function compile(pattern: string): RouteDef {
  const [path] = pattern.split('?')
  return { routeId: pattern, segments: path.split('/').filter(Boolean) }
}

/** Parse a query string ("a=1&b=2", with or without a leading "?") into a plain object. */
export function parseQuery(queryString: string): Record<string, string> {
  const q = queryString.startsWith('?') ? queryString.slice(1) : queryString
  if (!q) return {}
  const out: Record<string, string> = {}
  for (const pair of q.split('&')) {
    if (!pair) continue
    const [rawKey, rawVal] = pair.split('=')
    if (!rawKey) continue
    out[decodeURIComponent(rawKey)] = rawVal !== undefined ? decodeURIComponent(rawVal) : ''
  }
  return out
}

/** Match a list of path segments (already split, no query string) against one route's
 * pattern segments. Returns captured params on success, null on no match. */
export function matchPath(pathSegments: string[], routeSegments: string[]): Record<string, string> | null {
  if (pathSegments.length !== routeSegments.length) return null
  const params: Record<string, string> = {}
  for (let i = 0; i < routeSegments.length; i++) {
    const routeSeg = routeSegments[i]
    const pathSeg = pathSegments[i]
    if (routeSeg.startsWith(':')) {
      if (!pathSeg) return null
      params[routeSeg.slice(1)] = decodeURIComponent(pathSeg)
    } else if (routeSeg !== pathSeg) {
      return null
    }
  }
  return params
}

/** Build a route table once (e.g. module-level `const ROUTES = buildRoutes([...])`), then
 * call `.match(path)` per navigation instead of recompiling patterns on every hash change. */
export function buildRoutes(patterns: string[]) {
  const compiled = patterns.map(compile)
  return {
    match(pathAndQuery: string): RouteMatch | null {
      const [pathPart, ...queryParts] = pathAndQuery.split('?')
      const query = parseQuery(queryParts.join('?'))
      const pathSegments = pathPart.split('/').filter(Boolean)
      for (const route of compiled) {
        const params = matchPath(pathSegments, route.segments)
        if (params) return { routeId: route.routeId, params, query }
      }
      return null
    },
  }
}
