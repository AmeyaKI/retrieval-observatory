import { KeyboardEvent, useEffect, useRef, useState } from 'react'
import { DemoContext, fetchDemoContext, fetchRuns, Run } from '../api'
import { useDashboardContext } from '../context/DashboardContext'
import { InvestigateView } from '../context/dashboardQuery'
import { RouteTarget } from '../utils/focusedRoutes'
import type { PipelineHint } from './InvestigateWorkspace'

// Compact scope bar (master plan 2.2): database, run, and — inside Investigate — pipeline
// and the Queries | Documents view. Every control writes the URL through updateSelection.

export const VIEW_TABS: Array<{ id: InvestigateView; label: string }> = [
  { id: 'queries', label: 'Queries' },
  { id: 'documents', label: 'Documents' },
]

/** Pipeline ids declared by a run's config (`config_json.pipelines[].id`); the same list the service resolves against. */
export function pipelineIdsFromConfig(configJson: string | undefined | null): string[] {
  if (!configJson) return []
  try {
    const parsed = JSON.parse(configJson) as { pipelines?: unknown }
    if (!Array.isArray(parsed.pipelines)) return []
    return parsed.pipelines
      .map((p) => (p && typeof p === 'object' && 'id' in p ? String((p as { id?: unknown }).id ?? '') : ''))
      .filter(Boolean)
  } catch {
    return []
  }
}

export function runLabel(run: Run): string {
  return `${run.experiment_name} · ${run.run_id}`
}

const selectClass =
  'rounded-md border border-hairline bg-surface px-2 py-1 text-xs text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 disabled:opacity-60 max-w-[18rem]'

function ViewTabs({ view, onChange }: { view: InvestigateView; onChange: (view: InvestigateView) => void }) {
  const refs = useRef<Array<HTMLButtonElement | null>>([])
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next: number | null = null
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % VIEW_TABS.length
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + VIEW_TABS.length) % VIEW_TABS.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = VIEW_TABS.length - 1
    if (next === null) return
    event.preventDefault()
    refs.current[next]?.focus()
    onChange(VIEW_TABS[next].id)
  }
  return (
    <div role="tablist" aria-label="Investigate view" className="inline-flex rounded-md app-inset p-0.5">
      {VIEW_TABS.map((tab, index) => {
        const selected = tab.id === view
        return (
          <button
            key={tab.id}
            ref={(el) => {
              refs.current[index] = el
            }}
            type="button"
            role="tab"
            id={`view-tab-${tab.id}`}
            aria-selected={selected}
            aria-controls="investigate-view"
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={`rounded px-2.5 py-1 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 ${
              selected ? 'bg-surface text-ink font-semibold shadow-card' : 'text-ink-muted hover:text-ink'
            }`}
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}

interface Props {
  workspace: RouteTarget
  /** Pipelines Investigate learned from the service for the current run (scope or `pipeline_required`). */
  pipelineHint?: PipelineHint | null
}

export default function GlobalContextBar({ workspace, pipelineHint }: Props) {
  const { selection, databases, updateSelection } = useDashboardContext()
  const [runs, setRuns] = useState<Run[] | null>(null)
  const [runsError, setRunsError] = useState<string | null>(null)
  const [demo, setDemo] = useState<DemoContext | null>(null)
  const db = selection.db

  useEffect(() => {
    let cancelled = false
    setRuns(null)
    setRunsError(null)
    if (!db) return
    fetchRuns(db)
      .then((list) => {
        if (!cancelled) setRuns(list)
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setRuns([])
        setRunsError(error instanceof Error ? error.message : 'Could not load runs')
      })
    return () => {
      cancelled = true
    }
  }, [db])

  useEffect(() => {
    let cancelled = false
    fetchDemoContext()
      .then((context) => {
        if (!cancelled) setDemo(context)
      })
      .catch(() => {
        if (!cancelled) setDemo(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const dbKnown = !db || databases.some((d) => d.db_id === db)
  const selectedDb = databases.find((d) => d.db_id === db)
  const isDemoDb = Boolean(
    demo && db && ((demo.db_id && demo.db_id === db) || (demo.db_path && selectedDb?.path === demo.db_path)),
  )
  const run = selection.run
  const selectedRun = runs?.find((r) => r.run_id === run)
  const runKnown = !run || runs === null || Boolean(selectedRun)

  const hinted = pipelineHint && pipelineHint.runId === run ? pipelineHint.ids : []
  const pipelines = Array.from(new Set([...pipelineIdsFromConfig(selectedRun?.config_json), ...hinted]))
  const pipeline = selection.pipeline
  const showInvestigate = workspace === 'investigate'

  return (
    <div role="group" aria-label="Scope" className="flex flex-wrap items-center gap-x-4 gap-y-2 hairline-b bg-surface px-4 py-2">
      <label className="flex items-center gap-1.5 text-xs text-ink-muted">
        Database
        <select
          aria-label="Database"
          className={selectClass}
          value={db ?? ''}
          onChange={(event) => updateSelection({ db: event.target.value || null })}
        >
          {databases.length === 0 && <option value="">No databases</option>}
          {!dbKnown && (
            <option value={db ?? ''} disabled>
              {db} (not found)
            </option>
          )}
          {databases.map((d) => (
            <option key={d.db_id} value={d.db_id}>
              {d.label}
            </option>
          ))}
        </select>
      </label>
      {isDemoDb && (
        <span className="rounded-full app-inset px-2 py-0.5 text-[10px] font-medium text-ink-muted" title="Seeded by retobs demo; not your pipeline">
          Deterministic demo data
        </span>
      )}
      <label className="flex items-center gap-1.5 text-xs text-ink-muted">
        Run
        <select
          aria-label="Run"
          className={selectClass}
          value={run ?? ''}
          disabled={!db || (runs !== null && runs.length === 0)}
          onChange={(event) => updateSelection({ run: event.target.value || null })}
        >
          {runs === null && <option value={run ?? ''}>{db ? (run ? `${run} (loading…)` : 'Loading runs…') : 'Choose a database'}</option>}
          {runs !== null && runs.length === 0 && <option value="">{runsError ? 'Runs unavailable' : 'No runs'}</option>}
          {runs !== null && runs.length > 0 && <option value="">Choose a run</option>}
          {!runKnown && (
            <option value={run ?? ''} disabled>
              {run} (not found)
            </option>
          )}
          {runs?.map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {runLabel(r)}
            </option>
          ))}
        </select>
      </label>
      {runsError && (
        <span role="alert" className="text-xs text-status-negative">
          {runsError}
        </span>
      )}
      {showInvestigate && run && pipelines.length > 1 && (
        <label className="flex items-center gap-1.5 text-xs text-ink-muted">
          Pipeline
          <select
            aria-label="Pipeline"
            className={selectClass}
            value={pipeline ?? ''}
            onChange={(event) => updateSelection({ pipeline: event.target.value || null })}
          >
            <option value="">Choose a pipeline</option>
            {pipeline && !pipelines.includes(pipeline) && (
              <option value={pipeline} disabled>
                {pipeline} (not found)
              </option>
            )}
            {pipelines.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
      )}
      {showInvestigate && run && pipelines.length <= 1 && (pipeline || pipelines[0]) && (
        <span className="text-xs text-ink-muted">
          Pipeline <span className="font-mono text-ink">{pipeline ?? pipelines[0]}</span>
        </span>
      )}
      {showInvestigate && (
        <div className="ml-auto">
          <ViewTabs view={selection.view} onChange={(view) => updateSelection({ view })} />
        </div>
      )}
    </div>
  )
}
