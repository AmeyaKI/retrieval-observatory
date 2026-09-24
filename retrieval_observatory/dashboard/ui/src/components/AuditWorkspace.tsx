import { useEffect, useState } from 'react'
import { fetchComparison, fetchRuns, ReleaseAudit, ReleaseDecision, Run } from '../api'
import { useDashboardContext } from '../context/DashboardContext'
import AuditReport, { AuditFallback } from './AuditReport'
import { runLabel } from './GlobalContextBar'
import StatusPanel from './StatusPanel'

// Audit: pick a baseline and a candidate run (URL: baseline/candidate) and an optional local
// release-policy path (URL: policy), then render the release audit the server builds for them.
// Baseline selection stays explicit: nothing defaults to the latest run.

type AuditResult =
  | { key: string; audit: ReleaseAudit | null; decision: ReleaseDecision | null }
  | { key: string; error: string }

const selectClass =
  'rounded-md border border-hairline bg-surface px-2 py-1 text-xs text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600 disabled:opacity-60 max-w-[20rem]'

export default function AuditWorkspace() {
  const { selection, updateSelection } = useDashboardContext()
  const { db, baseline, candidate, policy } = selection
  const [runs, setRuns] = useState<Run[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [policyDraft, setPolicyDraft] = useState(policy ?? '')
  const [result, setResult] = useState<AuditResult | null>(null)
  const ready = Boolean(db && baseline && candidate && baseline !== candidate)
  const key = JSON.stringify([db, baseline, candidate, policy])

  useEffect(() => setPolicyDraft(policy ?? ''), [policy])

  useEffect(() => {
    if (!ready || !db || !baseline || !candidate) return
    let cancelled = false
    fetchComparison(
      [
        { dbId: db, runId: baseline },
        { dbId: db, runId: candidate },
      ],
      policy || undefined,
    )
      .then((data) => {
        if (!cancelled) setResult({ key, audit: data.audit ?? null, decision: data.release_decision ?? null })
      })
      .catch((raw: unknown) => {
        if (!cancelled) setResult({ key, error: raw instanceof Error ? raw.message : 'Could not load the audit' })
      })
    return () => {
      cancelled = true
    }
  }, [key, ready])

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
  } else if (!result || result.key !== key) {
    body = <StatusPanel kind="loading" message="Loading the release audit…" />
  } else if ('error' in result) {
    const readOnly = /\b403\b/.test(result.error) && result.error.includes('policy_path')
    body = (
      <StatusPanel
        kind="error"
        title={readOnly ? 'This server does not read local policy files' : 'Audit could not be loaded'}
        message={result.error}
      />
    )
  } else if (result.audit) {
    body = <AuditReport audit={result.audit} db={db} />
  } else {
    body = <AuditFallback decision={result.decision} db={db} baseline={baseline} candidate={candidate} />
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
        <form
          className="mb-4 flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            updateSelection({ policy: policyDraft.trim() || null })
          }}
        >
          <label className="min-w-0 flex-1 text-xs text-ink-muted sm:max-w-md">
            Local release-policy path
            <input
              value={policyDraft}
              onChange={(event) => setPolicyDraft(event.target.value)}
              placeholder="retobs/release-policy.yaml"
              className="mt-1 w-full rounded-md border border-hairline bg-surface px-2 py-1 font-mono text-xs text-ink"
            />
          </label>
          <button type="submit" className="rounded-md bg-indigo-600 px-3 py-1 text-xs font-semibold text-white">
            Apply policy
          </button>
          {policy && (
            <button type="button" onClick={() => updateSelection({ policy: null })} className="rounded-md border border-hairline px-3 py-1 text-xs text-ink">
              Clear
            </button>
          )}
          <p className="basis-full text-[10px] text-ink-faint">
            The path is read locally by this RetObs process; policy content is not sent to an external service.
          </p>
        </form>
        {body}
      </div>
    </main>
  )
}
