import { describe, expect, it } from 'vitest'
import { applySelectionPatch, DEFAULT_SELECTION, parseDashboardQuery, serializeDashboardQuery } from './dashboardQuery'

describe('dashboard URL context', () => {
  it('drops retired scope keys (service, window, cohort, filter) instead of carrying them', () => {
    const selection = parseDashboardQuery('db=main&service=api&run=r1&window=custom&since=a&until=b&cohort=hard&filter=z')
    expect(selection).toEqual({ ...DEFAULT_SELECTION, db: 'main', run: 'r1' })
    expect(serializeDashboardQuery(selection)).toBe('db=main&run=r1')
  })

  it('round-trips the investigation, audit and connect scope keys', () => {
    const selection = parseDashboardQuery(
      'db=main&run=r%2F1&pipeline=hybrid&view=documents&query=q%201&trace=t1&entity=docs%3Ad%C3%A9&stage=rerank&outcome=not_observed&compare=b0&baseline=b&candidate=c&policy=pol&integration=int',
    )
    expect(selection).toEqual({
      ...DEFAULT_SELECTION,
      db: 'main',
      run: 'r/1',
      pipeline: 'hybrid',
      view: 'documents',
      query: 'q 1',
      trace: 't1',
      entity: 'docs:dé',
      stage: 'rerank',
      outcome: 'not_observed',
      compare: 'b0',
      baseline: 'b',
      candidate: 'c',
      policy: 'pol',
      integration: 'int',
    })
    expect(parseDashboardQuery(serializeDashboardQuery(selection))).toEqual(selection)
  })

  it('defaults view to queries and omits it from the URL', () => {
    expect(parseDashboardQuery('db=main').view).toBe('queries')
    expect(serializeDashboardQuery({ ...DEFAULT_SELECTION, db: 'main', view: 'queries' })).toBe('db=main')
    expect(serializeDashboardQuery({ ...DEFAULT_SELECTION, db: 'main', view: 'documents' })).toBe('db=main&view=documents')
  })

  it('keeps unrelated fields from the base selection when the query omits them', () => {
    const base = { ...DEFAULT_SELECTION, db: 'main', run: 'r1', policy: 'pol' }
    expect(parseDashboardQuery('view=documents', base)).toEqual({ ...base, view: 'documents' })
  })

  it('applySelectionPatch clears run-scoped fields, including compare, when the run changes', () => {
    const prev = { ...DEFAULT_SELECTION, db: 'main', run: 'r1', pipeline: 'p', query: 'q', compare: 'b0', baseline: 'b' }
    expect(applySelectionPatch(prev, { run: 'r2' })).toEqual({ ...prev, run: 'r2', pipeline: null, query: null, compare: null })
    expect(applySelectionPatch(prev, { db: 'other' })).toMatchObject({ db: 'other', run: null, pipeline: null, query: null, compare: null, baseline: null })
  })
})
