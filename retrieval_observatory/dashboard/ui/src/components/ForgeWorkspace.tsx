import { useEffect, useState } from 'react'
import { fetchForgeDatasets, ForgeDataset } from '../api'
import DatasetList from './forge/DatasetList'
import DatasetDetail from './forge/DatasetDetail'

interface Props {
  route: string // dataset id, if any
}

export default function ForgeWorkspace({ route }: Props) {
  const [datasets, setDatasets] = useState<ForgeDataset[]>([])
  const [error, setError] = useState<string | null>(null)
  const activeId = route || (datasets[0]?.dataset_id ?? null)

  useEffect(() => {
    fetchForgeDatasets().then(setDatasets).catch((e) => setError(e.message))
  }, [])

  const select = (id: string) => {
    window.location.hash = `#/forge/${id}`
  }

  return (
    <div className="flex flex-1 min-w-0">
      <aside className="shrink-0 w-72 bg-white border-r border-gray-200 flex flex-col overflow-hidden">
        <div className="px-4 py-4 border-b border-gray-200">
          <h1 className="text-lg font-bold text-gray-900">Forge</h1>
          <p className="text-xs text-gray-500 mt-0.5">Corpus-specific stress datasets</p>
        </div>
        {error && (
          <div className="m-3 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">{error}</div>
        )}
        <DatasetList datasets={datasets} activeId={activeId} onSelect={select} />
      </aside>

      <main className="flex-1 overflow-auto min-w-0">
        {activeId ? (
          <DatasetDetail datasetId={activeId} />
        ) : (
          <div className="flex items-center justify-center h-full">
            <div className="text-center max-w-md px-6">
              <div className="text-4xl mb-4 select-none">🜂</div>
              <p className="text-lg font-semibold text-gray-700">No Forge datasets yet</p>
              <p className="text-sm text-gray-500 mt-2 leading-relaxed">
                Forge scans your corpus for failure patterns (temporal confusion, alias mismatches) and
                generates hard, targeted evaluation queries.
              </p>
              <p className="text-sm text-gray-400 mt-3 leading-relaxed">
                Fastest path:{' '}
                <code className="text-amber-700 bg-amber-50 px-1 rounded">retobs demo</code>
                {' '}— or generate with{' '}
                <code className="text-amber-700 bg-amber-50 px-1 rounded">retobs forge run --corpus corpus.jsonl --output ./forge_out</code>
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
