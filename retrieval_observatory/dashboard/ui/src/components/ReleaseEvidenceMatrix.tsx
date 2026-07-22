import { ClaimReadiness } from '../api'

const LABELS: Record<string, string> = {
  promotion: 'Promotion',
  aggregate_or_slice_evaluation: 'Aggregate or slice evaluation',
  lineage_diagnosis: 'Lineage diagnosis',
  lineage_diff: 'Lineage diff',
  production_trace: 'Production trace',
}

function statusClass(status: ClaimReadiness['status']): string {
  if (status === 'READY') return 'border-emerald-300 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-200'
  if (status === 'HOLD') return 'border-amber-300 bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-100'
  return 'border-red-300 bg-red-50 text-red-900 dark:bg-red-950/30 dark:text-red-100'
}

export default function ReleaseEvidenceMatrix({ readiness }: { readiness: Record<string, ClaimReadiness> }) {
  const entries = Object.entries(readiness)
  if (entries.length === 0) return null
  return (
    <section aria-labelledby="release-readiness-heading" className="space-y-2">
      <h3 id="release-readiness-heading" className="text-sm font-semibold text-ink">Claim readiness</h3>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {entries.map(([scope, claim]) => (
          <div key={scope} className={`rounded border p-2 ${statusClass(claim.status)}`}>
            <div className="flex items-center justify-between gap-2 text-xs font-semibold">
              <span>{LABELS[scope] ?? scope.replace(/_/g, ' ')}</span>
              <span>{claim.status}</span>
            </div>
            {claim.findings.length > 0 ? (
              <ul className="mt-1 list-disc pl-4 text-[11px]">
                {claim.findings.map((finding, index) => <li key={`${finding.code}:${index}`}>{finding.detail}</li>)}
              </ul>
            ) : <p className="mt-1 text-[11px]">Required evidence is available for this claim.</p>}
          </div>
        ))}
      </div>
    </section>
  )
}
