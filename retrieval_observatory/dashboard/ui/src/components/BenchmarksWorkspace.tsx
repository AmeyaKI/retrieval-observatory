import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import WorkspaceGlossaryLink from './WorkspaceGlossaryLink'
import {
  DemoContext,
  fetchRuns,
  Run,
  RunSelection,
  selectionKey,
} from '../api'
import { buildRoutes } from '../routing'
import DbTabs from './DbTabs'
import RunsSidebar from './RunsSidebar'
import RunPageLayout from './RunPageLayout'
import { useDashboardContext } from '../context/DashboardContext'

const RunOverviewPage = lazy(() => import('./RunOverviewPage'))
const RunArchitecturePage = lazy(() => import('./RunArchitecturePage'))
const RunAttributionPage = lazy(() => import('./RunAttributionPage'))
const RunQualityPage = lazy(() => import('./RunQualityPage'))
const RunTradeoffsPage = lazy(() => import('./RunTradeoffsPage'))
const RunQueriesPage = lazy(() => import('./RunQueriesPage'))
const RunQueryDetailPage = lazy(() => import('./RunQueryDetailPage'))
const RunCandidateFlowPage = lazy(() => import('./RunCandidateFlowPage'))
const QueryDiffPage = lazy(() => import('./QueryDiffPage'))
const RunDocumentsPage = lazy(() => import('./RunDocumentsPage'))
const ComparePanel = lazy(() => import('./ComparePanel'))
const AnalysisPage = lazy(() => import('../analysis/AnalysisPage'))

const RUN_ROUTES = buildRoutes([
  ':runId',
  ':runId/architecture',
  ':runId/attribution',
  ':runId/quality',
  ':runId/tradeoffs',
  ':runId/queries',
  ':runId/queries/:queryId',
  ':runId/queries/:queryId/diff',
  ':runId/queries/:queryId/candidates/:docId',
  ':runId/documents',
  ':runId/analysis/:analysisId',
])

function pageIdForRoute(routeId: string): string {
  const parts = routeId.split('/')
  return parts.length >= 2 ? parts[1] : ''
}

export default function BenchmarksWorkspace({
  demoContext,
  route = '',
  view = 'runs',
}: {
  demoContext?: DemoContext | null
  route?: string
  view?: 'runs' | 'compare' | 'queries'
}) {
  const { selection, databases: sources, updateSelection } = useDashboardContext()
  const activeDbId = selection.db
  const [runs, setRuns] = useState<Run[]>([])
  const [selected, setSelected] = useState<RunSelection[]>([])
  const [resolvedRun, setResolvedRun] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768)

  const deepLink = useMemo(() => {
    const match = RUN_ROUTES.match(route)
    if (!match || !match.params.runId) return null
    return {
      runId: match.params.runId,
      page: pageIdForRoute(match.routeId),
      queryId: match.params.queryId,
      docId: match.params.docId,
      isDiff: match.routeId.endsWith('/diff'),
      against: match.query.against,
      analysisId: match.params.analysisId,
    }
  }, [route])

  useEffect(() => {
    if (!deepLink || !activeDbId) return
    setSelected([{ dbId: activeDbId, runId: deepLink.runId }])
  }, [deepLink?.runId, activeDbId])

  useEffect(() => {
    if (!activeDbId) {
      setRuns([])
      return
    }
    fetchRuns(activeDbId)
      .then(setRuns)
      .catch((e) => setError(e.message))
  }, [activeDbId])

  useEffect(() => {
    if (!activeDbId || deepLink) return
    if (view === 'compare' && demoContext?.baseline_run_id && demoContext.candidate_run_id) {
      setSelected([
        { dbId: activeDbId, runId: demoContext.baseline_run_id },
        { dbId: activeDbId, runId: demoContext.candidate_run_id },
      ])
    } else if (view === 'queries' && runs[0]) {
      setSelected([{ dbId: activeDbId, runId: runs[0].run_id }])
    }
  }, [demoContext, activeDbId, view, runs, deepLink])

  useEffect(() => {
    if (selected.length !== 1) {
      setResolvedRun(null)
      return
    }
    if (selection.run !== selected[0].runId) updateSelection({ run: selected[0].runId }, 'replace')
    const sel = selected[0]
    const local = runs.find(
      (r) => r.run_id === sel.runId && (r.db_id ?? activeDbId) === sel.dbId,
    )
    if (local) {
      setResolvedRun(local)
      return
    }
    fetchRuns(sel.dbId)
      .then((all) => setResolvedRun(all.find((r) => r.run_id === sel.runId) ?? null))
      .catch((e) => setError(e.message))
  }, [selected, runs, activeDbId])

  const toggleSelect = (dbId: string, runId: string) => {
    const key = selectionKey({ dbId, runId })
    setSelected((prev) => {
      const exists = prev.some((s) => selectionKey(s) === key)
      if (exists) {
        return prev.filter((s) => selectionKey(s) !== key)
      }
      return [...prev, { dbId, runId }]
    })
  }

  const selectedKeys = new Set(selected.map(selectionKey))

  return (
    <div className="flex flex-1 min-w-0">
      <aside
        className={`fixed sm:static inset-y-0 left-0 z-30 shrink-0 bg-white dark:bg-slate-900 border-r border-gray-200 dark:border-slate-700 flex flex-col transition-all duration-200 overflow-hidden ${
          sidebarOpen ? 'w-72' : 'w-0 border-r-0'
        }`}
      >
        <div className="px-4 py-4 border-b border-gray-200 dark:border-slate-700 min-w-[18rem]">
          <div className="flex items-center justify-between gap-2">
            <h1 className="text-lg font-bold text-gray-900 dark:text-slate-100">{view === 'compare' ? 'Compare' : view === 'queries' ? 'Queries' : 'Runs'}</h1>
            <WorkspaceGlossaryLink className="text-[11px] text-indigo-700 underline decoration-indigo-300" />
          </div>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5">{view === 'compare' ? 'Select baseline first, then candidate' : view === 'queries' ? 'Inspect query-level evidence' : 'Review retrieval evaluations'}</p>
        </div>
        {error && (
          <div className="m-3 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700 min-w-[18rem]">
            {error}
          </div>
        )}
        <DbTabs sources={sources} activeDbId={activeDbId} onSelect={(db) => updateSelection({ db, run: null, service: null, cohort: null })} />
        <RunsSidebar
          runs={runs}
          selectedKeys={selectedKeys}
          onToggle={toggleSelect}
          activeDbId={activeDbId}
        />
      </aside>

      <main className="flex-1 overflow-auto min-w-0">
        <div className="sticky top-0 z-10 bg-gray-50/95 backdrop-blur border-b border-gray-200 dark:border-slate-700 px-3 py-2 flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => setSidebarOpen((v) => !v)}
            className="p-1.5 rounded-md border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-600 dark:text-slate-300 hover:text-gray-900 hover:border-gray-300"
            title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <path d="M9 3v18" />
              {sidebarOpen ? (
                <path d="M13 8l-3 4 3 4" strokeLinecap="round" strokeLinejoin="round" />
              ) : (
                <path d="M11 8l3 4-3 4" strokeLinecap="round" strokeLinejoin="round" />
              )}
            </svg>
          </button>
          <span className="text-xs text-gray-500 dark:text-slate-400">Toggle run list</span>
          {view === 'compare' && demoContext?.baseline_run_id && (
            <span className="ml-auto text-xs text-indigo-700 bg-indigo-50 border border-indigo-200 rounded px-2 py-1">
              Demo runs loaded — baseline vs degraded selected for comparison
            </span>
          )}
        </div>

        <Suspense fallback={<div className="p-6 text-sm text-ink-muted" role="status">Loading evidence…</div>}>
        {selected.length === 0 && (
          <div className="flex items-center justify-center h-[calc(100%-3rem)]">
            <div className="text-center max-w-sm">
              <div className="text-4xl mb-4 select-none" role="img" aria-label="Runs icon" title="Runs icon">▥</div>
              <p className="text-lg font-semibold text-gray-700 dark:text-slate-200">Select a run to explore</p>
              <p className="text-sm text-gray-500 dark:text-slate-400 mt-2 leading-relaxed">
                Click any run in the sidebar to view its metrics, charts, and query-level diagnostics.
              </p>
              <p className="text-sm text-gray-400 dark:text-slate-500 mt-3 leading-relaxed">
                Check two or more runs to compare them side-by-side with significance tests.
              </p>
            </div>
          </div>
        )}
        {selected.length === 1 && resolvedRun && (
          <RunPageLayout run={resolvedRun} activePage={deepLink?.page ?? (view === 'queries' ? 'queries' : '')} wide={!sidebarOpen}>
            {(deepLink?.page ?? (view === 'queries' ? 'queries' : '')) === '' && <RunOverviewPage run={resolvedRun} dbId={selected[0].dbId} />}
            {deepLink?.page === 'architecture' && <RunArchitecturePage dbId={selected[0].dbId} runId={resolvedRun.run_id} />}
            {deepLink?.page === 'attribution' && <RunAttributionPage dbId={selected[0].dbId} runId={resolvedRun.run_id} />}
            {deepLink?.page === 'quality' && <RunQualityPage run={resolvedRun} dbId={selected[0].dbId} />}
            {deepLink?.page === 'tradeoffs' && <RunTradeoffsPage run={resolvedRun} dbId={selected[0].dbId} />}
            {(deepLink?.page === 'queries' || (!deepLink && view === 'queries')) && !deepLink?.queryId && (
              <RunQueriesPage dbId={selected[0].dbId} runId={resolvedRun.run_id} />
            )}
            {deepLink?.page === 'queries' && deepLink.queryId && deepLink.isDiff && deepLink.against && (
              <QueryDiffPage
                dbId={selected[0].dbId}
                runId={resolvedRun.run_id}
                againstRunId={deepLink.against}
                queryId={deepLink.queryId}
              />
            )}
            {deepLink?.page === 'queries' && deepLink.queryId && !deepLink.docId && !deepLink.isDiff && (
              <RunQueryDetailPage dbId={selected[0].dbId} runId={resolvedRun.run_id} queryId={deepLink.queryId} />
            )}
            {deepLink?.page === 'queries' && deepLink.queryId && deepLink.docId && (
              <RunCandidateFlowPage
                dbId={selected[0].dbId}
                runId={resolvedRun.run_id}
                queryId={deepLink.queryId}
                docId={deepLink.docId}
              />
            )}
            {deepLink?.page === 'documents' && <RunDocumentsPage dbId={selected[0].dbId} runId={resolvedRun.run_id} />}
            {deepLink?.page === 'analysis' && deepLink.analysisId && <AnalysisPage dbId={selected[0].dbId} runId={resolvedRun.run_id} analysisId={deepLink.analysisId} />}
          </RunPageLayout>
        )}
        {selected.length === 1 && !resolvedRun && (
          <div className="p-6 text-sm text-gray-400 dark:text-slate-500">Loading run…</div>
        )}
        {selected.length >= 2 && <ComparePanel selections={selected} />}
        </Suspense>
      </main>
    </div>
  )
}
