import { RunOverview } from '../api'

interface Props {
  overview: RunOverview | null
}

export default function RunManifestPanel({ overview }: Props) {
  const manifest = overview?.manifest as Record<string, unknown> | null | undefined
  if (!manifest) return null

  const dataset = manifest.dataset as Record<string, unknown> | undefined
  const nQueries = dataset?.n_queries
  const datasetName = dataset?.name ?? dataset?.fingerprint
  const qrelCount = dataset?.qrels
  const qrelSource = dataset?.qrels_path ?? (typeof dataset?.name === 'string' && String(dataset.name).startsWith('beir/') ? `${dataset.name} test split` : undefined)
  const configHash = manifest.config_hash as string | undefined
  const schemaVersion = manifest.schema_version as number | undefined

  return (
    <div className="app-inset px-3 py-2 mb-4 text-xs text-ink-muted grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
      {datasetName != null && (
        <div><span className="text-ink-faint">Dataset</span> <span className="font-mono text-ink">{String(datasetName)}</span></div>
      )}
      {nQueries != null && (
        <div><span className="text-ink-faint">Queries</span> <span className="font-mono text-ink">{String(nQueries)}</span></div>
      )}
      {qrelCount != null && (
        <div><span className="text-ink-faint">Qrel queries</span> <span className="font-mono text-ink">{String(qrelCount)}</span></div>
      )}
      {qrelSource != null && (
        <div><span className="text-ink-faint">Qrel source</span> <span className="font-mono text-ink truncate" title={String(qrelSource)}>{String(qrelSource)}</span></div>
      )}
      {configHash && (
        <div className="sm:col-span-2"><span className="text-ink-faint">Config hash</span> <span className="font-mono text-ink truncate" title={configHash}>{configHash.slice(0, 16)}…</span></div>
      )}
      {schemaVersion != null && (
        <div><span className="text-ink-faint">Manifest schema</span> <span className="font-mono">v{schemaVersion}</span></div>
      )}
    </div>
  )
}
