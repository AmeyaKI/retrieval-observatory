/// <reference types="vite/client" />
import { describe, expect, test } from 'vitest'
import appShell from './components/AppShell.tsx?raw'
import api from './api.ts?raw'

// Retired workspaces and API clients must not come back through the shell or the client module.
const RETIRED_IDENTIFIERS = [
  'ForgeWorkspace',
  'AdvisorWorkspace',
  'TraceLensWorkspace',
  'BenchmarksWorkspace',
  'RunTradeoffsPage',
  'RunAttributionPage',
  'fetchParetoFrontier',
  'fetchOperatorAttribution',
  'fetchMissAttribution',
  'fetchCandidateFlow',
  'fetchAdvisorRecommendations',
  'fetchAdvisorRegressions',
  'fetchAdvisorReliability',
  'fetchForgeDatasets',
  'fetchForgeDataset',
  'fetchClassifierCalibration',
  'fetchQueryLabels',
  'fetchTraceDrift',
  'fetchTraceHotspots',
  'fetchTraceClusters',
  'fetchTraceSummary',
  'fetchTraceDistribution',
]

// Retired HTTP routes: the server answers these with 410, so no client may call them.
const RETIRED_ROUTE_FRAGMENTS = [
  '/forge/',
  '/advisor/',
  '/pareto-frontier',
  '/operator-attribution',
  '/miss-attribution',
  '/classifier-calibration',
  '/query-labels',
  '/production/drift',
  '/production/hotspots',
  '/production/clusters',
  '/production/summary',
  '/production/distribution',
]

describe('retired surface', () => {
  test.each([
    ['AppShell.tsx', appShell],
    ['api.ts', api],
  ])('%s names no retired workspace or client', (_name, source) => {
    for (const identifier of RETIRED_IDENTIFIERS) {
      expect(source, identifier).not.toMatch(new RegExp(`\\b${identifier}\\b`))
    }
  })

  test('api.ts calls no retired route', () => {
    for (const fragment of RETIRED_ROUTE_FRAGMENTS) expect(api, fragment).not.toContain(fragment)
  })
})
