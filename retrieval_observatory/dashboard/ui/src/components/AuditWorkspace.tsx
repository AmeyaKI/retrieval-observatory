import { useEffect, useState } from 'react'
import { fetchRuns, Run } from '../api'
import { useDashboardContext } from '../context/DashboardContext'
import ComparePanel from './ComparePanel'
import { runLabel } from './GlobalContextBar'

// Audit: pick a baseline and a candidate run (URL: baseline/candidate) and compare them.
// The `policy` param is carried untouched for the release-policy task.

const selectClass =
  'rounded-md border border-hairline bg-surface px-2 py-1 text-xs text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 disabled:opacity-60 max-w-[20rem]'

export default function AuditWorkspace() {
  const { selection, updateSelection } = useDashboardContext()
  const { db, baseline, candidate } = selection
  const [runs, setRuns] = useState<Run[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setRuns(null)
    setError(null)
    if (!db) return
    fetchRuns(db)
      .then((list) => {
        if (!cancelled) setRuns(list)
      })
      .catch((raw: unknown) => {
        if (cancelled) return
        setRuns([])
        setError(raw instanceof Error ? raw.message : 'Could not load runs')
      })
    return () => {
      cancelled = true
    }
  }, [db])

  const renderSelect = (label: string, key: 'baseline' | 'candidate', value: string | null) => {
    const known = !value || runs === null || runs.some((r) => r.run_id === value)
    return (
      <label className="flex items-center gap-1.5 text-xs text-ink-muted">
        {label}
        <select
          aria-label={label}
          className={selectClass}
          value={value ?? ''}
          disabled={!db || (runs !== null && runs.length === 0)}
          onChange={(event) => updateSelection({ [key]: event.target.value || null })}
        >
          <option value="">{runs === null ? (db ? 'Loading runs…' : 'Choose a database') : runs.length === 0 ? 'No runs' : `Choose ${label.toLowerCase()}`}</option>
          {!known && (
            <option value={value ?? ''} disabled>
              {value} (not found)
            </option>
          )}
          {runs?.map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {runLabel(r)}
            </option>
          ))}
        </select>
      </label>
    )
  }

  let body: React.ReactNode
  if (!db) {
    body = <p className="app-card p-6 text-sm text-ink-muted">Choose a database in the scope bar.</p>
  } else if (!baseline || !candidate) {
    body = (
      <p className="app-card p-6 text-sm text-ink-muted">
        Choose a baseline and a candidate run to audit. Both must come from this database.
      </p>
    )
  } else if (baseline === candidate) {
    body = (
      <p role="alert" className="app-card p-6 text-sm text-status-warning">
        Baseline and candidate are the same run; pick two different runs.
      </p>
    )
  } else {
    body = (
      <ComparePanel
        selections={[
          { dbId: db, runId: baseline },
          { dbId: db, runId: candidate },
        ]}
      />
    )
  }

  return (
    <main className="flex-1 overflow-auto p-4 sm:p-6" aria-labelledby="audit-title">
      <div className="mx-auto max-w-6xl">
        <header className="mb-4">
          <p className="eyebrow">Audit</p>
          <h1 id="audit-title" className="mt-1 text-xl font-semibold text-ink">
            Audit
          </h1>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-ink-muted">
            An audit checks whether the evidence supports the declared tolerances between a baseline and a candidate, and links
            each failed check to Investigate.
          </p>
        </header>
        <div className="mb-4 flex flex-wrap items-center gap-4">
          {renderSelect('Baseline', 'baseline', baseline)}
          {renderSelect('Candidate', 'candidate', candidate)}
          {error && (
            <span role="alert" className="text-xs text-status-negative">
              {error}
            </span>
          )}
        </div>
        {body}
      </div>
    </main>
  )
}
