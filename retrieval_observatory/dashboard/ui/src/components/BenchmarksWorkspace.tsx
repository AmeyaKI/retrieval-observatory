import { useEffect, useMemo, useState } from 'react'
import WorkspaceGlossaryLink from './WorkspaceGlossaryLink'
import {
  DbSource,
  DemoContext,
  fetchDbs,
  fetchRuns,
  Run,
  RunSelection,
  selectionKey,
} from '../api'
import DbTabs from './DbTabs'
import RunsSidebar from './RunsSidebar'
import RunDetail from './RunDetail'
import ComparePanel from './ComparePanel'

export default function BenchmarksWorkspace({
  demoContext,
  route = '',
}: {
  demoContext?: DemoContext | null
  route?: string
}) {
  const [sources, setSources] = useState<DbSource[]>([])
  const [activeDbId, setActiveDbId] = useState<string | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [selected, setSelected] = useState<RunSelection[]>([])
  const [resolvedRun, setResolvedRun] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)

  const deepLink = useMemo(() => {
    const parts = route.split('/').filter(Boolean)
    if (parts[0] !== 'run' || !parts[1]) return null
    return { runId: decodeURIComponent(parts[1]), section: parts[2] ? decodeURIComponent(parts[2]) : undefined }
  }, [route])

  useEffect(() => {
    if (!deepLink || !activeDbId) return
    setSelected([{ dbId: activeDbId, runId: deepLink.runId }])
  }, [deepLink?.runId, activeDbId])

  useEffect(() => {
    fetchDbs()
      .then((dbs) => {
        setSources(dbs)
        if (dbs.length > 0) {
          setActiveDbId(dbs[0].db_id)
        }
      })
      .catch((e) => setError(e.message))
  }, [])

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
    if (!demoContext?.baseline_run_id || !demoContext.candidate_run_id || !activeDbId) return
    setSelected([
      { dbId: activeDbId, runId: demoContext.baseline_run_id },
      { dbId: activeDbId, runId: demoContext.candidate_run_id },
    ])
  }, [demoContext, activeDbId])

  useEffect(() => {
    if (selected.length !== 1) {
      setResolvedRun(null)
      return
    }
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
        className={`shrink-0 bg-white dark:bg-slate-900 border-r border-gray-200 dark:border-slate-700 flex flex-col transition-all duration-200 overflow-hidden ${
          sidebarOpen ? 'w-72' : 'w-0 border-r-0'
        }`}
      >
        <div className="px-4 py-4 border-b border-gray-200 dark:border-slate-700 min-w-[18rem]">
          <div className="flex items-center justify-between gap-2">
            <h1 className="text-lg font-bold text-gray-900 dark:text-slate-100">Benchmarks</h1>
            <WorkspaceGlossaryLink className="text-[11px] text-indigo-700 underline decoration-indigo-300" />
          </div>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5">Evaluate retrieval pipelines offline</p>
        </div>
        {error && (
          <div className="m-3 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700 min-w-[18rem]">
            {error}
          </div>
        )}
        <DbTabs sources={sources} activeDbId={activeDbId} onSelect={setActiveDbId} />
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
          {demoContext?.baseline_run_id && (
            <span className="ml-auto text-xs text-indigo-700 bg-indigo-50 border border-indigo-200 rounded px-2 py-1">
              Demo runs loaded — baseline vs degraded selected for comparison
            </span>
          )}
        </div>

        {selected.length === 0 && (
          <div className="flex items-center justify-center h-[calc(100%-3rem)]">
            <div className="text-center max-w-sm">
              <div className="text-4xl mb-4 select-none" role="img" aria-label="Benchmarks module icon" title="Benchmarks module icon">📊</div>
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
          <RunDetail
            run={resolvedRun}
            dbId={selected[0].dbId}
            wide={!sidebarOpen}
            initialSection={deepLink?.section}
          />
        )}
        {selected.length === 1 && !resolvedRun && (
          <div className="p-6 text-sm text-gray-400 dark:text-slate-500">Loading run…</div>
        )}
        {selected.length >= 2 && <ComparePanel selections={selected} />}
      </main>
    </div>
  )
}
