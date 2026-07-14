import { useEffect, useState } from 'react'
import WorkspaceGlossaryLink from './WorkspaceGlossaryLink'
import { fetchForgeDatasets, ForgeDataset } from '../api'
import DatasetList from './forge/DatasetList'
import DatasetDetail from './forge/DatasetDetail'

interface Props {
  route: string // dataset id, if any
  dbId: string
}

export default function ForgeWorkspace({ route, dbId }: Props) {
  const [datasets, setDatasets] = useState<ForgeDataset[]>([])
  const [error, setError] = useState<string | null>(null)
  const activeId = route || (datasets[0]?.dataset_id ?? null)

  useEffect(() => {
    fetchForgeDatasets(dbId).then(setDatasets).catch((e) => setError(e.message))
  }, [dbId])

  const select = (id: string) => {
    window.location.hash = `#/test-sets/${id}`
  }

  return (
    <div className="flex flex-1 min-w-0">
      <aside className="shrink-0 w-72 bg-white dark:bg-slate-900 border-r border-gray-200 dark:border-slate-700 flex flex-col overflow-hidden">
        <div className="px-4 py-4 border-b border-gray-200 dark:border-slate-700">
          <div className="flex items-center justify-between gap-2">
            <h1 className="text-lg font-bold text-gray-900 dark:text-slate-100">Test Sets</h1>
            <WorkspaceGlossaryLink className="text-[11px] text-amber-700 underline decoration-amber-300" />
          </div>
          <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5">Corpus-specific stress datasets</p>
          <p className="text-[11px] text-amber-800 mt-2">
            Corpus-specific stress tests with visible generation and validation provenance.
          </p>
        </div>
        {error && (
          <div className="m-3 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">{error}</div>
        )}
        <DatasetList datasets={datasets} activeId={activeId} onSelect={select} />
      </aside>

      <main className="flex-1 overflow-auto min-w-0">
        {activeId ? (
          <DatasetDetail dbId={dbId} datasetId={activeId} />
        ) : (
          <div className="flex items-center justify-center h-full">
            <div className="text-center max-w-md px-6">
              <div className="text-4xl mb-4 select-none" role="img" aria-label="Test Sets icon" title="Test Sets icon">◇</div>
              <p className="text-lg font-semibold text-gray-700 dark:text-slate-200">No Test Sets yet</p>
              <p className="text-sm text-gray-500 dark:text-slate-400 mt-2 leading-relaxed">
                Test Set generation scans your corpus for failure patterns (temporal confusion, alias mismatches) and
                generates hard, targeted evaluation queries.
              </p>
              <p className="text-sm text-gray-400 dark:text-slate-500 mt-3 leading-relaxed">
                Fastest path:{' '}
                <code className="text-amber-700 bg-amber-50 px-1 rounded">retobs demo</code>
                {' '}— or generate with{' '}
                <code className="text-amber-700 bg-amber-50 px-1 rounded">retobs testsets generate --corpus corpus.jsonl --output ./testset</code>
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
