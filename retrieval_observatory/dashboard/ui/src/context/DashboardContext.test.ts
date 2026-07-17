import { describe, expect, it } from 'vitest'
import { parseDashboardQuery, serializeDashboardQuery } from './dashboardQuery'

describe('dashboard URL context', () => {
  it('round-trips every global selector and repeated cohort filter', () => {
    const selection = parseDashboardQuery('db=main&service=api&run=r1&window=custom&since=a&until=b&cohort=hard&filter=z&filter=a')
    expect(parseDashboardQuery(serializeDashboardQuery(selection))).toEqual({ ...selection, filters: ['a', 'z'] })
  })
})
