import { describe, expect, it } from 'vitest'
import { buildRoutes, matchPath, parseQuery } from './routing'

describe('parseQuery', () => {
  it('parses a plain query string', () => {
    expect(parseQuery('a=1&b=2')).toEqual({ a: '1', b: '2' })
  })
  it('strips a leading ?', () => {
    expect(parseQuery('?a=1')).toEqual({ a: '1' })
  })
  it('returns {} for an empty string', () => {
    expect(parseQuery('')).toEqual({})
  })
  it('decodes URI-encoded values', () => {
    expect(parseQuery('q=hello%20world')).toEqual({ q: 'hello world' })
  })
  it('handles a valueless key as empty string', () => {
    expect(parseQuery('flag')).toEqual({ flag: '' })
  })
})

describe('matchPath', () => {
  it('matches literal segments exactly', () => {
    expect(matchPath(['run', 'x'], ['run', ':runId'])).toEqual({ runId: 'x' })
  })
  it('returns null on segment-count mismatch', () => {
    expect(matchPath(['run', 'x', 'extra'], ['run', ':runId'])).toBeNull()
  })
  it('returns null when a literal segment does not match', () => {
    expect(matchPath(['other', 'x'], ['run', ':runId'])).toBeNull()
  })
  it('captures multiple params', () => {
    expect(matchPath(['runs', 'r1', 'queries', 'q1'], ['runs', ':runId', 'queries', ':queryId'])).toEqual({
      runId: 'r1',
      queryId: 'q1',
    })
  })
})

describe('buildRoutes', () => {
  const routes = buildRoutes([
    'run/:runId',
    'run/:runId/architecture',
    'run/:runId/queries',
    'run/:runId/queries/:queryId',
    'run/:runId/queries/:queryId/candidates/:docId',
    'compare',
  ])

  it('matches the overview route and captures runId', () => {
    const m = routes.match('run/abc123')
    expect(m).toEqual({ routeId: 'run/:runId', params: { runId: 'abc123' }, query: {} })
  })

  it('matches a deeper route over a shallower one when segment counts differ', () => {
    const m = routes.match('run/abc123/architecture')
    expect(m?.routeId).toBe('run/:runId/architecture')
  })

  it('parses query strings alongside path params (the ?with=... case)', () => {
    const m = routes.match('run/abc123/queries/q1?highlight=true')
    expect(m?.params).toEqual({ runId: 'abc123', queryId: 'q1' })
    expect(m?.query).toEqual({ highlight: 'true' })
  })

  it('matches nested candidate-flow route', () => {
    const m = routes.match('run/abc123/queries/q1/candidates/doc9')
    expect(m?.routeId).toBe('run/:runId/queries/:queryId/candidates/:docId')
    expect(m?.params).toEqual({ runId: 'abc123', queryId: 'q1', docId: 'doc9' })
  })

  it('decodes encoded ids in params', () => {
    const m = routes.match('run/run%2F1')
    expect(m?.params.runId).toBe('run/1')
  })

  it('returns null for an unmatched path', () => {
    expect(routes.match('nope/at/all')).toBeNull()
  })

  it('matches a route with no params', () => {
    const m = routes.match('compare?with=abc')
    expect(m).toEqual({ routeId: 'compare', params: {}, query: { with: 'abc' } })
  })
})
