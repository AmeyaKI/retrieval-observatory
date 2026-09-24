import { Fragment, useEffect, useRef, useState } from 'react'
import { CAPABILITY_NAMES, CapabilityReport, fetchIntegration, fetchIntegrations, IntegrationRecord, IntegrationSummary } from '../api'
import { useDashboardContext } from '../context/DashboardContext'
import { buildHash, investigateLink } from '../utils/focusedRoutes'

// Connect: the concise empty state (master plan 3.1). One install line, the one-sentence
// agent request, the manual path, the known databases, and what gets captured. With a
// database selected it also lists that database's verified integrations, and with one
// selected (URL `integration=`) it shows the record read-only: the exact local setup, the
// plan summary, the verified capabilities, the unresolved mappings and the first
// investigation link. The plan itself is edited in the repository, never here.

export const AGENT_REQUEST =
  'Ask your coding agent to connect retobs to this existing retrieval pipeline, run your benchmark, and open a document-flow investigation.'

export const AGENT_QUICKSTART_HREF = 'https://github.com/AmeyaKI/retrieval-observatory/blob/main/docs/integrations/AGENT_QUICKSTART.md'

const codeClass = 'app-inset mt-2 overflow-x-auto px-3 py-2 font-mono text-xs text-ink'
const linkClass = 'text-accent underline-offset-2 hover:underline'
const monoClass = 'font-mono text-ink'
const thClass = 'py-1 pr-3 text-left font-medium text-ink-faint'
const tdClass = 'py-1 pr-3 align-top'

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="app-card p-5" aria-labelledby={`connect-step-${n}`}>
      <p className="eyebrow">Step {n}</p>
      <h2 id={`connect-step-${n}`} className="mt-1 font-semibold text-ink">
        {title}
      </h2>
      <div className="mt-2 text-sm leading-6 text-ink-muted">{children}</div>
    </section>
  )
}

/** Status vocabulary: a glyph next to the word, never colour alone. */
export function statusGlyph(status: string): string {
  return status === 'ready' ? '●' : status === 'partial' ? '◐' : '○'
}

/** `topology_observed` → "Topology observed". */
export function capabilityLabel(name: string): string {
  const words = name.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function StatusText({ status }: { status: string }) {
  return (
    <span className="whitespace-nowrap">
      <span aria-hidden="true">{statusGlyph(status)}</span> {status}
    </span>
  )
}

function depthLabel(depth: IntegrationSummary['depth']): string {
  return depth === 'internal' ? 'internal transitions' : 'final output only'
}

function VerifiedAt({ iso }: { iso: string }) {
  const date = new Date(iso)
  const text = Number.isNaN(date.getTime()) ? iso : date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  return <time dateTime={iso}>{text}</time>
}

function Code({ children }: { children: string }) {
  return <code className={monoClass}>{children}</code>
}

function SubHeading({ children }: { children: string }) {
  return <h3 className="mt-5 text-sm font-semibold text-ink">{children}</h3>
}

function TextList({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="mt-1">None</p>
  return (
    <ul className="mt-1 list-disc space-y-1 pl-5">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  )
}

export function IntegrationList({ db, integrations }: { db: string; integrations: IntegrationSummary[] }) {
  if (integrations.length === 0) {
    return (
      <p className="mt-2 text-sm text-ink-muted">
        No verified integration in this database yet. Run <Code>retobs integrate . --phase verify</Code> in the project to record one.
      </p>
    )
  }
  return (
    <ul className="mt-2 divide-y divide-hairline text-sm">
      {integrations.map((item) => (
        <li key={item.integration_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
          <a href={buildHash('connect', { db, integration: item.integration_id })} className={`${linkClass} font-mono`}>
            {item.service_id} · {item.pipeline_id}
          </a>
          <span className="text-xs text-ink-muted">
            <StatusText status={item.status} /> · {depthLabel(item.depth)} · verified <VerifiedAt iso={item.verified_at} />
          </span>
        </li>
      ))}
    </ul>
  )
}

function Boundary({ boundary }: { boundary: IntegrationRecord['boundary'] }) {
  if (boundary.kind === 'entrypoint_return') {
    return (
      <>
        Final output: what <Code>{boundary.symbol ?? '?'}</Code> returns in <Code>{boundary.relative_path ?? '?'}</Code>
      </>
    )
  }
  if (boundary.kind === 'operator_output') {
    return (
      <>
        Final output: the output of operator <Code>{boundary.op_id ?? boundary.symbol ?? '?'}</Code>
      </>
    )
  }
  return <>Final boundary unresolved</>
}

function Judgments({ judgments }: { judgments: IntegrationRecord['judgments'] }) {
  if (judgments.status !== 'resolved') {
    const notes = judgments.notes ?? []
    return <>Judgments unresolved{notes.length > 0 ? `: ${notes.join('; ')}` : ''}</>
  }
  const paths = (['queries', 'qrels', 'corpus'] as const).filter((key) => judgments[key])
  return (
    <>
      Judgments:{' '}
      {paths.map((key, index) => (
        <Fragment key={key}>
          {index > 0 && ', '}
          {key} <Code>{judgments[key] as string}</Code>
        </Fragment>
      ))}
    </>
  )
}

export function IntegrationPanel({ db, record }: { db: string; record: IntegrationRecord }) {
  const install = record.actions.find((action) => action.kind === 'install')
  const benchmark = record.actions.find((action) => action.kind === 'benchmark_setup')
  const scenarios = record.actions.filter((action) => action.kind === 'scenario_execution')
  const integrate = `retobs integrate ${record.project_root}`
  const { identity, investigation } = record

  return (
    <section className="app-card p-5 text-sm leading-6 text-ink-muted" aria-labelledby="connect-integration">
      <p className="eyebrow">Integration</p>
      <h2 id="connect-integration" className="mt-1 font-mono font-semibold text-ink">
        {record.service_id} · {record.pipeline_id}
      </h2>
      <p className="text-xs">
        <StatusText status={record.status} /> · {depthLabel(record.depth)} · verified <VerifiedAt iso={record.verified_at} /> · version {record.version}
      </p>

      <SubHeading>Setup</SubHeading>
      {install?.command && <pre className={codeClass}>{install.command}</pre>}
      <pre className={codeClass}>
        {`${integrate} --phase plan --output retobs/integration-plan.json\n${integrate} --phase apply --plan retobs/integration-plan.json\n${integrate} --phase verify --db ${record.db_path}`}
      </pre>
      {scenarios.length > 0 && <p className="mt-2">Exercise each verification scenario before verifying:</p>}
      {scenarios.map((action, index) =>
        action.command ? (
          <pre key={index} className={codeClass}>
            {action.command}
          </pre>
        ) : (
          <p key={index} className="mt-1">
            {action.description}
          </p>
        ),
      )}
      {benchmark?.command && (
        <>
          <p className="mt-2">Run the benchmark through the instrumented callable:</p>
          <pre className={codeClass}>{benchmark.command}</pre>
        </>
      )}

      <SubHeading>Plan summary</SubHeading>
      <p className="mt-1">
        <Boundary boundary={record.boundary} />
      </p>
      <p>
        Candidates identified by <Code>{identity.candidate_id_field}</Code> ({identity.unit}); query id from <Code>{identity.query_id}</Code>
      </p>
      <p>
        <Judgments judgments={record.judgments} />
      </p>
      <p>
        {record.depth === 'internal'
          ? 'Internal transitions are observed'
          : 'Final output only: per-stage loss attribution is unavailable until internal operators are instrumented'}
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs" aria-label={`Operators of ${record.integration_id}`}>
          <thead>
            <tr>
              {['Operator', 'Type', 'Symbol', 'Inputs', 'Outputs', 'Parents'].map((label) => (
                <th key={label} scope="col" className={thClass}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {record.operators.map((op) => (
              <tr key={op.op_id}>
                <td className={`${tdClass} ${monoClass}`}>
                  {op.op_id}
                  {op.invocation === 'async' && <span className="ml-1 rounded border border-hairline px-1 font-sans text-ink-muted">async</span>}
                </td>
                <td className={tdClass}>{op.op_type}</td>
                <td className={tdClass}>
                  <Code>{op.symbol}</Code> in <Code>{op.relative_path}</Code>
                </td>
                <td className={tdClass}>
                  <Code>{op.input_mapping}</Code>
                </td>
                <td className={tdClass}>
                  <Code>{op.output_mapping}</Code>
                  {op.capture && (
                    <>
                      {' · capture '}
                      <Code>{op.capture}</Code>
                    </>
                  )}
                </td>
                <td className={`${tdClass} ${monoClass}`}>{op.parent_ids.length > 0 ? op.parent_ids.join(', ') : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <SubHeading>Verified capabilities</SubHeading>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs" aria-label={`Verified capabilities of ${record.integration_id}`}>
          <thead>
            <tr>
              <th scope="col" className={thClass}>
                Capability
              </th>
              <th scope="col" className={thClass}>
                Status
              </th>
              <th scope="col" className={thClass}>
                Scope
              </th>
            </tr>
          </thead>
          <tbody>
            {CAPABILITY_NAMES.map((name) => {
              const report = record.capabilities[name] as CapabilityReport | undefined
              const status = report?.status ?? 'unavailable'
              const expected = record.expected_capabilities[name]
              const failures = report?.failures ?? []
              return (
                <Fragment key={name}>
                  <tr className="border-t border-hairline">
                    <td className={`${tdClass} text-ink`}>{capabilityLabel(name)}</td>
                    <td className={tdClass}>
                      <StatusText status={status} />
                      {expected && expected !== status && <span className="ml-2 text-ink-faint">expected {expected}</span>}
                    </td>
                    <td className={tdClass}>{report?.scope ?? ''}</td>
                  </tr>
                  {failures.length > 0 && (
                    <tr>
                      <td colSpan={3} className="pb-2 pl-4">
                        <ul className="list-disc space-y-1 pl-4">
                          {failures.map((failure, index) => (
                            <li key={index}>
                              <Code>{failure.code}</Code> — {failure.detail} — <span className="text-ink">{failure.fix}</span>
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      <SubHeading>Unresolved mappings</SubHeading>
      <TextList items={record.unresolved} />
      <SubHeading>Open questions</SubHeading>
      <TextList items={record.open_questions} />

      <SubHeading>First investigation</SubHeading>
      {investigation ? (
        <p className="mt-2">
          <a
            href={investigateLink({ db, run: investigation.run_id, pipeline: investigation.pipeline_id })}
            className="inline-block rounded-md bg-accent px-3 py-1.5 font-medium text-white hover:opacity-90"
          >
            Open the first investigation
          </a>
          <span className="ml-2 text-xs">
            run <Code>{investigation.run_id}</Code>
          </span>
        </p>
      ) : (
        <>
          <p className="mt-1">No run for this pipeline yet.</p>
          {benchmark && (benchmark.command ? <pre className={codeClass}>{benchmark.command}</pre> : <p>{benchmark.description}</p>)}
          <p className="mt-2">Run the benchmark, then verify again to record the first investigation.</p>
        </>
      )}

      {record.errors.length > 0 && (
        <>
          <SubHeading>Errors</SubHeading>
          <ul role="alert" className="mt-1 list-disc space-y-1 pl-5 text-status-negative">
            {record.errors.map((error, index) => (
              <li key={index}>{error}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

type ListState = { kind: 'idle' | 'loading' } | { kind: 'ready'; items: IntegrationSummary[] } | { kind: 'failed'; message: string }
type RecordState = { kind: 'idle' | 'loading' } | { kind: 'ready'; record: IntegrationRecord } | { kind: 'missing' } | { kind: 'failed'; message: string }

function errorMessage(raw: unknown): string {
  return raw instanceof Error ? raw.message : String(raw)
}

export default function ConnectWorkspace() {
  const { selection, databases } = useDashboardContext()
  const { db, integration } = selection
  const [list, setList] = useState<ListState>({ kind: 'idle' })
  const [record, setRecord] = useState<RecordState>({ kind: 'idle' })
  const listSequence = useRef(0)
  const recordSequence = useRef(0)

  // Each stream is sequence-guarded: a response for a scope that is no longer selected never lands.
  useEffect(() => {
    if (!db) {
      setList({ kind: 'idle' })
      return
    }
    const mySequence = ++listSequence.current
    setList({ kind: 'loading' })
    fetchIntegrations(db)
      .then((items) => {
        if (mySequence === listSequence.current) setList({ kind: 'ready', items })
      })
      .catch((raw: unknown) => {
        if (mySequence === listSequence.current) setList({ kind: 'failed', message: errorMessage(raw) })
      })
  }, [db])

  useEffect(() => {
    if (!db || !integration) {
      setRecord({ kind: 'idle' })
      return
    }
    const mySequence = ++recordSequence.current
    setRecord({ kind: 'loading' })
    fetchIntegration(db, integration)
      .then((item) => {
        if (mySequence === recordSequence.current) setRecord({ kind: 'ready', record: item })
      })
      .catch((raw: unknown) => {
        if (mySequence !== recordSequence.current) return
        const message = errorMessage(raw)
        setRecord(message.includes('integration_not_found') ? { kind: 'missing' } : { kind: 'failed', message })
      })
  }, [db, integration])

  const dbPath = databases.find((item) => item.db_id === db)?.path ?? db

  return (
    <main className="flex-1 overflow-auto p-4 sm:p-6" aria-labelledby="connect-title">
      <div className="mx-auto max-w-4xl space-y-4">
        <header>
          <p className="eyebrow">Connect</p>
          <h1 id="connect-title" className="mt-1 text-xl font-semibold text-ink">
            Connect an existing retrieval pipeline
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-ink-muted">
            retobs records what each operator actually received and emitted, then shows where each relevant document
            was lost. Nothing here changes how your pipeline runs.
          </p>
        </header>

        <Step n={1} title="Install">
          <pre className={codeClass}>pip install retrieval-observatory</pre>
        </Step>

        <Step n={2} title="Ask your coding agent">
          <p>One request is enough; the agent reads the repository and proposes a small patch you review.</p>
          <blockquote className={`${codeClass} whitespace-pre-wrap font-sans`}>{AGENT_REQUEST}</blockquote>
          <p className="mt-2">
            <a href={AGENT_QUICKSTART_HREF} className={linkClass}>
              Agent quickstart
            </a>{' '}
            describes what the agent inspects and what it must report when internals are not observable.
          </p>
        </Step>

        <Step n={3} title="Or do it by hand">
          <ol className="list-decimal space-y-2 pl-5">
            <li>
              Propose and apply the integration patch:
              <pre className={codeClass}>retobs integrate .</pre>
            </li>
            <li>
              Run your benchmark through the instrumented callable:
              <pre className={codeClass}>retobs evaluate module:callable --queries queries.jsonl --qrels qrels.tsv</pre>
            </li>
            <li>
              Open the dashboard:
              <pre className={codeClass}>retobs serve</pre>
            </li>
          </ol>
        </Step>

        {db && (
          <section className="app-card p-5" aria-labelledby="connect-integrations">
            <h2 id="connect-integrations" className="font-semibold text-ink">
              Verified integrations
            </h2>
            {list.kind === 'ready' ? (
              <IntegrationList db={db} integrations={list.items} />
            ) : list.kind === 'failed' ? (
              <p role="alert" className="mt-2 text-sm text-status-negative">
                Could not load the integrations of this database: {list.message}
              </p>
            ) : (
              <p role="status" className="mt-2 text-sm text-ink-muted">
                Loading integrations…
              </p>
            )}
          </section>
        )}

        {db && integration && record.kind === 'ready' && <IntegrationPanel db={db} record={record.record} />}
        {db && integration && record.kind !== 'ready' && (
          <section className="app-card p-5" aria-labelledby="connect-integration">
            <p className="eyebrow">Integration</p>
            <h2 id="connect-integration" className="mt-1 font-mono font-semibold text-ink">
              {integration}
            </h2>
            <p role={record.kind === 'failed' ? 'alert' : 'status'} className="mt-2 text-sm leading-6 text-ink-muted">
              {record.kind === 'missing' ? (
                <>
                  No verification record for <Code>{integration}</Code> in this database. Run{' '}
                  <Code>{`retobs integrate . --phase verify --db ${dbPath}`}</Code> in the project.
                </>
              ) : record.kind === 'failed' ? (
                `Could not load this integration: ${record.message}`
              ) : (
                'Loading integration…'
              )}
            </p>
          </section>
        )}

        <section className="app-card p-5" aria-labelledby="connect-databases">
          <h2 id="connect-databases" className="font-semibold text-ink">
            Databases
          </h2>
          {databases.length === 0 ? (
            <p className="mt-2 text-sm text-ink-muted">No databases are registered with this server yet.</p>
          ) : (
            <ul className="mt-2 divide-y divide-hairline text-sm">
              {databases.map((item) => (
                <li key={item.db_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span>
                    <span className="font-medium text-ink">{item.label}</span>
                    <span className="ml-2 font-mono text-xs text-ink-muted">{item.path}</span>
                  </span>
                  <span className="text-xs text-ink-muted">
                    {item.run_count} {item.run_count === 1 ? 'run' : 'runs'}
                    {item.run_count > 0 && (
                      <>
                        {' · '}
                        <a href={buildHash('investigate', { db: item.db_id })} className={linkClass}>
                          Investigate
                        </a>
                      </>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="app-card p-5" aria-labelledby="connect-captured">
          <h2 id="connect-captured" className="font-semibold text-ink">
            What gets captured
          </h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-muted">
            <li>The actual inputs and outputs of each operator, per query.</li>
            <li>Candidate identity across stages (document or chunk, with its namespace).</li>
            <li>The final output boundary the evaluation is scored against.</li>
            <li>Judgments, so every outcome is stated with its relevance label.</li>
          </ul>
          <p className="mt-2 text-sm text-ink-muted">
            Details:{' '}
            <a href={AGENT_QUICKSTART_HREF} className={linkClass}>
              docs/integrations/AGENT_QUICKSTART.md
            </a>
          </p>
        </section>
      </div>
    </main>
  )
}
