import { Run } from '../api'
import { useDashboardContext } from '../context/DashboardContext'
import { serializeDashboardQuery } from '../context/dashboardQuery'

// Shared page template (RETOBS_FINER_PLAN_PHASE2.md, Item B step 5): a plain wrapper
// component, not a router feature -- one level of shared layout doesn't need router
// outlets, so each routed page imports and renders inside this directly. Every page gets
// a consistent run-context header and a conclusion -> evidence -> detail slot structure.
export interface RunPage {
  id: string
  label: string
}

export const RUN_PAGES: RunPage[] = [
  { id: '', label: 'Overview' },
  { id: 'architecture', label: 'Architecture' },
  { id: 'attribution', label: 'Attribution' },
  { id: 'quality', label: 'Quality' },
  { id: 'tradeoffs', label: 'Tradeoffs' },
  { id: 'queries', label: 'Queries' },
  { id: 'documents', label: 'Documents' },
  { id: 'analysis/gates', label: 'Analysis' },
]

function RunNav({ runId, activePage }: { runId: string; activePage: string }) {
  const { selection } = useDashboardContext()
  const context = serializeDashboardQuery({ ...selection, run: runId })
  return (
    <nav
      className="sticky top-12 z-20 -mx-6 px-6 py-2 mb-4 bg-canvas/95 backdrop-blur border-b border-gray-200 dark:border-slate-700 overflow-x-auto"
      aria-label="Run pages"
    >
      <div className="flex gap-1 min-w-max">
        {RUN_PAGES.map((p) => {
          const href = `#/runs/${encodeURIComponent(runId)}${p.id ? `/${p.id}` : ''}?${context}`
          const active = p.id === activePage || p.id.startsWith(`${activePage}/`)
          return (
            <a
              key={p.id || 'overview'}
              href={href}
              className={`text-xs px-2.5 py-1 rounded-md whitespace-nowrap transition-colors ${
                active
                  ? 'bg-indigo-100 dark:bg-indigo-950 text-indigo-800 dark:text-indigo-200 font-semibold'
                  : 'text-ink-muted hover:text-ink hover:bg-surface-muted'
              }`}
            >
              {p.label}
            </a>
          )
        })}
      </div>
    </nav>
  )
}

export default function RunPageLayout({
  run,
  activePage,
  wide,
  children,
}: {
  run: Run
  activePage: string
  wide?: boolean
  children: React.ReactNode
}) {
  return (
    <div className={`p-6 ${wide ? 'max-w-full' : 'max-w-5xl'}`}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-ink">{run.experiment_name}</h1>
          <p className="text-sm text-ink-muted font-mono mt-0.5">{run.run_id}</p>
          {run.forge_dataset_id && (
            <p className="text-xs text-amber-800 mt-1">
              Originating Test Set:{' '}
              <a href={`#/test-sets/${encodeURIComponent(run.forge_dataset_id)}`} className="underline decoration-amber-400 hover:text-amber-700">
                {run.forge_dataset_id}
              </a>
            </p>
          )}
        </div>
      </div>
      <RunNav runId={run.run_id} activePage={activePage} />
      {children}
    </div>
  )
}
