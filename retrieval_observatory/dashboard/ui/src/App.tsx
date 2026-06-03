import { useEffect, useState } from 'react'
import {
  DbSource,
  fetchDbs,
  fetchRuns,
  Run,
  RunSelection,
  selectionKey,
} from './api'
import DbTabs from './components/DbTabs'
import RunsSidebar from './components/RunsSidebar'
import RunDetail from './components/RunDetail'
import ComparePanel from './components/ComparePanel'

export default function App() {
  const [sources, setSources] = useState<DbSource[]>([])
  const [activeDbId, setActiveDbId] = useState<string | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [selected, setSelected] = useState<RunSelection[]>([])
  const [resolvedRun, setResolvedRun] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)

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
    <div className="flex h-screen bg-gray-50 font-sans">
      <aside
        className={`shrink-0 bg-white border-r border-gray-200 flex flex-col transition-all duration-200 overflow-hidden ${
          sidebarOpen ? 'w-72' : 'w-0 border-r-0'
        }`}
      >
        <div className="px-4 py-4 border-b border-gray-200 min-w-[18rem]">
          <h1 className="text-lg font-bold text-gray-900">Retrieval Observatory</h1>
          <p className="text-xs text-gray-500 mt-0.5">RAG retrieval benchmarking</p>
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
        <div className="sticky top-0 z-10 bg-gray-50/95 backdrop-blur border-b border-gray-200 px-3 py-2 flex items-center gap-2">
          <button
            type="button"
            onClick={() => setSidebarOpen((v) => !v)}
            className="p-1.5 rounded-md border border-gray-200 bg-white text-gray-600 hover:text-gray-900 hover:border-gray-300"
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
          <span className="text-xs text-gray-500">Toggle run list</span>
        </div>

        {selected.length === 0 && (
          <div className="flex items-center justify-center h-[calc(100%-3rem)] text-gray-400">
            <div className="text-center">
              <p className="text-lg">Select a run from the sidebar</p>
              <p className="text-sm mt-1">Check multiple runs to compare them</p>
            </div>
          </div>
        )}
        {selected.length === 1 && resolvedRun && (
          <RunDetail run={resolvedRun} dbId={selected[0].dbId} wide={!sidebarOpen} />
        )}
        {selected.length === 1 && !resolvedRun && (
          <div className="p-6 text-sm text-gray-400">Loading run…</div>
        )}
        {selected.length >= 2 && <ComparePanel selections={selected} />}
      </main>
    </div>
  )
}
