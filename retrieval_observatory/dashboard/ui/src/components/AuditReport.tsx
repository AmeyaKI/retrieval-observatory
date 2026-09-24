import type { ReactNode } from 'react'
import type { AuditCheck, AuditFieldComparison, ReleaseAudit, ReleaseDecision } from '../api'
import { investigateLink } from '../utils/focusedRoutes'
import ReleaseDecisionCard from './ReleaseDecisionCard'
import StatusPanel from './StatusPanel'

// Audit report: renders the `audit-1` release artifact (the same JSON the CLI and CI emit),
// decision first, then the evidence behind it. Pure: everything comes from `audit` and `db`.

const thClass = 'py-1 pr-3 text-left font-medium text-ink-faint'
const tdClass = 'py-1 pr-3 align-top'
const monoClass = 'font-mono text-ink'
const linkClass = 'text-accent underline-offset-2 hover:underline'

/** Status vocabulary: a glyph next to the word, never colour alone. */
const GLYPHS: Record<string, string> = { PASS: '●', READY: '●', HOLD: '◐', BLOCK: '○', FAIL: '✕' }
const TONES: Record<string, string> = {
  PASS: 'text-status-positive',
  READY: 'text-status-positive',
  HOLD: 'text-status-warning',
  BLOCK: 'text-status-negative',
  FAIL: 'text-status-negative',
}

function Status({ status }: { status: string }) {
  return (
    <span className={`whitespace-nowrap font-semibold ${TONES[status] ?? 'text-ink'}`}>
      <span aria-hidden="true">{GLYPHS[status] ?? '○'}</span> {status}
    </span>
  )
}

const CLASSIFICATIONS: Record<AuditFieldComparison['classification'], string> = {
  invariant: 'invariant',
  expected: 'expected change',
  unexpected: 'unexpected',
  evidence_invalid: 'evidence invalid',
  unknown: 'unknown',
}

function num(value: number | null | undefined, digits = 4): string {
  return value == null ? '—' : value.toFixed(digits)
}

function signed(value: number | null | undefined): string {
  return value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(4)}`
}

function pct(value: number | null | undefined, digits = 0): string {
  return value == null ? '—' : `${(value * 100).toFixed(digits)}%`
}

function text(value: unknown): string {
  if (value == null) return '—'
  return typeof value === 'string' ? value : JSON.stringify(value)
}

function Section({ id, title, children }: { id: string; title: ReactNode; children: ReactNode }) {
  return (
    <section className="app-card p-4 sm:p-5" aria-labelledby={id}>
      <h2 id={id} className="font-semibold text-ink">
        {title}
      </h2>
      <div className="mt-2 text-sm text-ink-muted">{children}</div>
    </section>
  )
}

function Table({ label, headers, children }: { label: string; headers: string[]; children: ReactNode }) {
  return (
    <div className="mt-2 overflow-x-auto">
      <table className="w-full text-xs" aria-label={label}>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header} scope="col" className={thClass}>
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-hairline">{children}</tbody>
      </table>
    </div>
  )
}

const CHECK_HEADERS = ['Check', 'Target', 'Effect', 'Interval', 'Tolerance', 'Status', 'Paired / attempted']
const CHANGED_ID = 'audit-changed-queries'

function scrollToChanged(event: React.MouseEvent) {
  // A plain `#…` href would be read as a route by the hash router; scroll instead.
  event.preventDefault()
  document.getElementById(CHANGED_ID)?.scrollIntoView({ behavior: 'smooth' })
}

function CheckRow({ check }: { check: AuditCheck }) {
  return (
    <tr>
      <td className={`${tdClass} ${monoClass}`}>
        {check.id}
        {check.affected_query_ids.length > 0 && (
          <a href={`#${CHANGED_ID}`} onClick={scrollToChanged} className={`ml-2 font-sans ${linkClass}`}>
            queries: {check.affected_query_ids.length}
          </a>
        )}
      </td>
      <td className={tdClass}>{check.target ?? check.metric}</td>
      <td className={`${tdClass} font-mono`}>{signed(check.effect)}</td>
      <td className={`${tdClass} whitespace-nowrap font-mono`}>
        [{signed(check.ci_low)}, {signed(check.ci_high)}]
      </td>
      <td className={`${tdClass} font-mono`}>{check.tolerance}</td>
      <td className={tdClass}>
        <Status status={check.status} />
        {check.status !== 'PASS' && check.sample_limitation && <p className="text-ink-muted">{check.sample_limitation}</p>}
      </td>
      <td className={`${tdClass} whitespace-nowrap font-mono`}>
        {check.paired_n} / {check.attempted_n} ({pct(check.pair_coverage)})
      </td>
    </tr>
  )
}

function Dl({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
      {rows.map(([term, value]) => (
        <div key={term} className="contents">
          <dt className="text-ink-faint">{term}</dt>
          <dd className={`${monoClass} break-all`}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

export default function AuditReport({ audit, db }: { audit: ReleaseAudit; db: string | null }) {
  const { decision, policy, compatibility, operational, statistics, investigation } = audit
  const provenance = [...compatibility.provenance.invariants, ...compatibility.provenance.interventions, ...compatibility.provenance.consistency]
  const scope = investigation.scope
  const download = 'data:application/json;charset=utf-8,' + encodeURIComponent(JSON.stringify(audit, null, 2))

  return (
    <div className="space-y-4">
      <Section id="audit-decision" title={<>Decision: <Status status={decision.status} /></>}>
        <ul className="list-disc space-y-0.5 pl-5">
          {decision.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
        <p className="mt-2">
          <span className="font-medium text-ink">Next action:</span> {decision.next_action}
        </p>
        <p className="mt-1 text-xs">
          exit code {decision.exit_code}
          {' · '}
          {policy.configured ? (
            <>
              policy <span className={monoClass}>{policy.id ?? 'unnamed'}</span> (schema {policy.schema_version ?? '—'},{' '}
              <span className={monoClass}>{policy.digest ?? 'no digest'}</span>) from <span className={monoClass}>{policy.source ?? '—'}</span>
            </>
          ) : (
            'no policy: a decision cannot PASS'
          )}
        </p>
      </Section>

      <Section id="audit-compatibility" title={<>Compatibility: <Status status={compatibility.status} /></>}>
        <Table label="Provenance fields" headers={['Field', 'Baseline', 'Candidate', 'Classification']}>
          {provenance.map((row) => (
            <tr key={row.field}>
              <td className={`${tdClass} ${monoClass}`}>{row.field}</td>
              <td className={`${tdClass} font-mono break-all`}>{text(row.baseline)}</td>
              <td className={`${tdClass} font-mono break-all`}>{text(row.candidate)}</td>
              <td className={tdClass}>{CLASSIFICATIONS[row.classification] ?? row.classification}</td>
            </tr>
          ))}
        </Table>
        {compatibility.findings.length > 0 && (
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs">
            {compatibility.findings.map((f) => (
              <li key={f.code + f.detail}>{`${f.code} — ${f.detail} — ${f.next_action}`}</li>
            ))}
          </ul>
        )}
        {compatibility.provenance.unknown_fields.length > 0 && (
          <p className="mt-2 text-xs">Unclassified fields: {compatibility.provenance.unknown_fields.join(', ')}</p>
        )}
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs" aria-label="Claim readiness">
          {Object.values(audit.readiness).map((claim) => (
            <li key={claim.scope}>
              {claim.scope.replace(/_/g, ' ')}: <Status status={claim.status} />
              {claim.findings.length > 0 && <span className="text-ink-muted"> ({claim.findings.map((f) => f.code).join(', ')})</span>}
            </li>
          ))}
        </ul>
      </Section>

      <Section id="audit-checks" title="Checks">
        <Table label="Policy checks" headers={CHECK_HEADERS}>
          {audit.checks.map((check) => (
            <CheckRow key={check.id} check={check} />
          ))}
        </Table>
      </Section>

      {audit.slices.length > 0 && (
        <Section id="audit-slices" title="Slices">
          {audit.slices.map((slice) => (
            <div key={slice.id} className="mt-3 first:mt-0">
              <p className="text-xs">
                <span className={monoClass}>
                  {slice.field} = {text(slice.value)}
                </span>{' '}
                <Status status={slice.status} /> · paired n {slice.paired_n}
                {slice.sample_limitation && ` · ${slice.sample_limitation}`}
              </p>
              <Table label={`Checks for ${slice.id}`} headers={CHECK_HEADERS}>
                {slice.guards.map((check) => (
                  <CheckRow key={check.id} check={check} />
                ))}
              </Table>
            </div>
          ))}
        </Section>
      )}

      {operational && (
        <Section id="audit-operational" title={<>Operational: <Status status={operational.status} /></>}>
          <Table label="Failure rates" headers={['Role', 'Run', 'Failed / attempted', 'Failure rate']}>
            {(['baseline', 'candidate'] as const).map((role) => (
              <tr key={role}>
                <td className={tdClass}>{role}</td>
                <td className={`${tdClass} ${monoClass}`}>{operational[role].run_id}</td>
                <td className={`${tdClass} font-mono`}>
                  {operational[role].failed_n} / {operational[role].attempted_n ?? '—'}
                </td>
                <td className={`${tdClass} font-mono`}>{pct(operational[role].failure_rate, 1)}</td>
              </tr>
            ))}
          </Table>
          <p className="mt-2 text-xs">
            cap {pct(operational.max_failure_rate, 1)}
            {operational.code && ` · ${operational.code}`} · {operational.detail}
          </p>
        </Section>
      )}

      <Section id={CHANGED_ID} title="Changed queries">
        {investigation.changed_queries.length === 0 ? (
          <p>No paired query changed on the decision metric.</p>
        ) : (
          <ul className="divide-y divide-hairline text-xs">
            {investigation.changed_queries.map((q) => (
              <li key={`${q.metric}:${q.query_id}`} className="flex flex-wrap gap-x-3 py-1">
                <a
                  className={`${linkClass} font-mono`}
                  href={investigateLink({
                    db,
                    run: scope.candidate_run_id,
                    pipeline: scope.pipeline_id,
                    view: 'queries',
                    query: q.query_id,
                    compare: scope.baseline_run_id,
                  })}
                >
                  {q.query_id}
                </a>
                <span>{q.metric}</span>
                <span className="font-mono">
                  {num(q.baseline)} → {num(q.candidate)} ({signed(q.delta)})
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <details className="app-card p-4 sm:p-5">
        <summary className="cursor-pointer font-semibold text-ink">Statistics</summary>
        <div className="mt-2">
          <Dl
            rows={[
              ['Confidence', num(statistics.confidence_level, 3)],
              ['Adjusted confidence', num(statistics.adjusted_confidence_level, 3)],
              ['Family size', statistics.family_size ?? '—'],
              ['Resamples', statistics.resamples ?? '—'],
              ['Seed', statistics.seed ?? '—'],
              ['Interval method', statistics.interval_method ?? '—'],
              ['Expected queries', audit.coverage.expected_query_count ?? '—'],
              ['Min pair coverage', pct(audit.coverage.min_pair_coverage)],
            ]}
          />
        </div>
      </details>

      <details className="app-card p-4 sm:p-5">
        <summary className="cursor-pointer font-semibold text-ink">All paired metrics</summary>
        <Table label="Paired metrics" headers={['Metric', 'Baseline', 'Candidate', 'Effect', 'q', 'n', 'Decision']}>
          {Object.entries(audit.metrics).map(([metric, m]) => (
            <tr key={metric}>
              <td className={`${tdClass} ${monoClass}`}>{metric}</td>
              <td className={`${tdClass} font-mono`}>{num(m.baseline_mean)}</td>
              <td className={`${tdClass} font-mono`}>{num(m.candidate_mean)}</td>
              <td className={`${tdClass} font-mono`}>{signed(m.effect)}</td>
              <td className={`${tdClass} font-mono`}>{num(m.q_value, 3)}</td>
              <td className={`${tdClass} font-mono`}>{m.paired_n}</td>
              <td className={tdClass}>{m.decision}</td>
            </tr>
          ))}
        </Table>
      </details>

      <p className="text-xs">
        <a href={download} download="release-audit.json" className={linkClass}>
          Download release-audit.json
        </a>
      </p>

      <Section id="audit-sources" title="Sources">
        <div className="grid gap-4 sm:grid-cols-2">
          {(['baseline', 'candidate'] as const).map((role) => {
            const source = audit.sources[role]
            return (
              <div key={role}>
                <p className="eyebrow">{role}</p>
                <Dl
                  rows={[
                    ['Run', source.run_id],
                    ['Experiment', source.experiment_name ?? '—'],
                    ['Dataset', source.dataset.name ?? '—'],
                    ['Query hash', source.dataset.query_hash ?? '—'],
                    ['Corpus hash', source.dataset.corpus_hash ?? '—'],
                    ['Qrel hash', source.dataset.qrel_hash ?? '—'],
                    ['Judgments', source.judgment_digest ?? '—'],
                    ['Manifest schema', source.manifest_schema_version ?? '—'],
                  ]}
                />
              </div>
            )
          })}
        </div>
      </Section>
    </div>
  )
}

/** Older servers send no `audit`: show the legacy decision card, or say the audit is unavailable. */
export function AuditFallback({
  decision,
  db,
  baseline,
  candidate,
}: {
  decision: ReleaseDecision | null | undefined
  db: string | null
  baseline: string
  candidate: string
}) {
  if (!decision) {
    return <StatusPanel kind="unavailable" title="Release audit unavailable" message="This server's comparison response carries no release audit." />
  }
  return (
    <ReleaseDecisionCard
      decision={decision}
      onQueryMetricSelect={(_metric, query) => {
        window.location.hash = investigateLink({ db, run: candidate, view: 'queries', query, compare: baseline }).slice(1)
      }}
    />
  )
}
