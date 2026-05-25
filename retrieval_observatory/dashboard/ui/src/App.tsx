import { useEffect, useState } from 'react'
import { fetchRuns, Run } from './api'
import RunsSidebar from './components/RunsSidebar'
import RunDetail from './components/RunDetail'
import ComparePanel from './components/ComparePanel'

export default function App() {
  const [runs, setRuns] = useState<Run[]>([])
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchRuns()
      .then(setRuns)
      .catch((e) => setError(e.message))
  }, [])

  const toggleSelect = (runId: string) => {
    setSelectedIds((prev) =>
      prev.includes(runId) ? prev.filter((id) => id !== runId) : [...prev, runId]
    )
  }

  return (
    <div className="flex h-screen bg-gray-50 font-sans">
      {/* Sidebar */}
      <aside className="w-72 shrink-0 bg-white border-r border-gray-200 flex flex-col">
        <div className="px-4 py-4 border-b border-gray-200">
          <h1 className="text-lg font-bold text-gray-900">Retrieval Observatory</h1>
          <p className="text-xs text-gray-500 mt-0.5">RAG retrieval benchmarking</p>
        </div>
        {error && (
          <div className="m-3 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">
            {error}
          </div>
        )}
        <RunsSidebar runs={runs} selectedIds={selectedIds} onToggle={toggleSelect} />
      </aside>

      {/* Main panel */}
      <main className="flex-1 overflow-auto">
        {selectedIds.length === 0 && (
          <div className="flex items-center justify-center h-full text-gray-400">
            <div className="text-center">
              <p className="text-lg">Select a run from the sidebar</p>
              <p className="text-sm mt-1">Check multiple runs to compare them</p>
            </div>
          </div>
        )}
        {selectedIds.length === 1 && <RunDetail runId={selectedIds[0]} />}
        {selectedIds.length >= 2 && <ComparePanel runIds={selectedIds} />}
      </main>
    </div>
  )
}
