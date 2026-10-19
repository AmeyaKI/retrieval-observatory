import { ComparisonEnvelope, JourneyDiffRow, JourneySide, StageAlignment } from '../api'
import { alignmentLabel, changeWords, compareHeadline, diffTotals, isCorrect, sideWords, sortDiffRows } from '../utils/comparisonDiffs'
import { captureWord, plural } from '../utils/flowWords'
import { displayEntity } from '../utils/queryDebugger'
import { BADGE } from './InvestigationGraph'
import { DOT, LINE_TWO, STACKED_ROW } from './InvestigationTable'

// Run comparison in words: the headline counts correct documents gained, lost and moved; the tables
// read Question · Document · Before · After · Change. Observed differences in recorded journeys only;
// a changed path is a fact, not an explanation.

const FOCUS = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent'
const NOTICE = 'app-inset px-3 py-2 text-[13px]'

interface HeadlineProps {
  envelope: ComparisonEnvelope
  /** Every loaded page of paired rows (the envelope carries only the last page). */
  rows: JourneyDiffRow[]
  auditHref?: string
}

/** The compare headline, the two runs in one muted line and calm notices; stands where a run's headline does. */
export function CompareHeadline({ envelope, rows, auditHref }: HeadlineProps) {
  const { baseline_run_id, candidate_run_id, compatibility } = envelope.comparison
  const limited = diffTotals(rows).captureLimited
  return (
    <header className="space-y-2">
      <h2 className="text-[22px] font-semibold leading-tight text-ink">{compareHeadline(rows, envelope.total, baseline_run_id)}</h2>
      <p className="text-[13px] text-ink-muted">
        Candidate <span className="font-mono">{candidate_run_id}</span> · baseline <span className="font-mono">{baseline_run_id}</span> ·{' '}
        {plural(envelope.total ?? rows.length, 'document')} compared
        {auditHref && (
          <>
            {' · '}
            <a href={auditHref} className={`text-accent underline underline-offset-2 ${FOCUS}`}>
              Back to audit
            </a>
          </>
        )}
      </p>
      {compatibility.corpus_changed ? (
        <p role="status" className={`${NOTICE} text-ink`}>
          The corpus changed between the runs, so documents are not paired; each run's evidence is shown as recorded.
        </p>
      ) : compatibility.query_inputs_identical === false ? (
        <p role="status" className={`${NOTICE} text-ink-muted`}>
          The question inputs differ between the runs; questions whose input changed can't be compared.
        </p>
      ) : null}
      {limited > 0 && (
        <p role="status" className={`${NOTICE} text-ink-muted`}>
          {limited === 1 ? '1 row was only partly recorded, so its reasons are not asserted.' : `${limited} rows were only partly recorded, so their reasons are not asserted.`}
        </p>
      )}
      {compatibility.findings.length > 0 && (
        <details className="app-inset p-3 text-xs">
          <summary className="cursor-pointer font-medium text-ink">Technical details</summary>
          <ul className="mt-2 space-y-1">
            {compatibility.findings.map((finding, index) => (
              <li key={`${finding.code}-${index}`}>
                <span className="font-mono text-ink">{finding.code}</span>
                <span className="text-ink-muted"> — {finding.detail}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </header>
  )
}

function SideText({ side, k, stepNameOf }: { side: JourneySide | null; k: number | null; stepNameOf: (opId: string) => string }) {
  return (
    <>
      {sideWords(side, k, stepNameOf)}
      {side?.capture_state === 'partial' && <span className="text-ink-muted"> · {captureWord('partial')}</span>}
    </>
  )
}

interface TableProps {
  caption: string
  /** A visible caption titles the table; inside a disclosure the summary does, so it is read-only to screen readers. */
  captionVisible: boolean
  rows: JourneyDiffRow[]
  showQuery: boolean
  singleNamespace: boolean
  k: number | null
  stepNameOf: (opId: string) => string
  onSelectEntity: (entity: string, queryId: string) => void
}

// Stacked, line two reads `q-outage · Dropped by Recency Filter → Delivered at #2`.
const ARROW = "max-sm:before:mr-2 max-sm:before:content-['→']"

/** Question · Document · Before · After · Change; rows stack into two lines below 640 px. */
function DiffTable({ caption, captionVisible, rows, showQuery, singleNamespace, k, stepNameOf, onSelectEntity }: TableProps) {
  return (
    <div className="app-card">
      <table className="w-full text-sm max-sm:block">
        <caption className={captionVisible ? 'border-b border-hairline px-3 py-2 text-left text-sm font-semibold text-ink max-sm:block' : 'sr-only'}>{caption}</caption>
        <thead className="text-left text-xs text-ink-faint max-sm:sr-only">
          <tr>
            {showQuery && (
              <th scope="col" className="px-3 py-2 font-medium">
                Question
              </th>
            )}
            {['Document', 'Before', 'After', 'Change'].map((header) => (
              <th key={header} scope="col" className="px-3 py-2 font-medium">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="max-sm:block">
          {rows.map((row) => {
            const words = changeWords(row.change)
            // Red and green mean a correct document lost or delivered; other rows' changes stay neutral.
            const tone = isCorrect(row) ? words.tone : 'neutral'
            return (
              <tr key={`${row.query_id}:${row.namespace}:${row.entity_id}`} className={`border-t border-hairline align-top ${STACKED_ROW}`}>
                {showQuery && <td className={`px-3 py-2 font-mono text-xs max-sm:order-4 max-sm:p-0 sm:whitespace-nowrap ${LINE_TWO}`}>{row.query_id}</td>}
                <td className="px-3 py-2 max-sm:order-1 max-sm:min-w-0 max-sm:flex-1 max-sm:p-0">
                  <button
                    type="button"
                    onClick={() => onSelectEntity(`${row.namespace}:${row.entity_id}`, row.query_id)}
                    className={`text-left font-mono text-xs text-accent underline-offset-2 hover:underline max-sm:break-all sm:whitespace-nowrap ${FOCUS}`}
                  >
                    {displayEntity(row, singleNamespace)}
                  </button>
                </td>
                <td className={`px-3 py-2 max-sm:order-5 max-sm:p-0 ${LINE_TWO} ${showQuery ? DOT : ''}`}>
                  <SideText side={row.baseline} k={k} stepNameOf={stepNameOf} />
                </td>
                <td className={`px-3 py-2 max-sm:order-6 max-sm:p-0 ${LINE_TWO} ${ARROW}`}>
                  <SideText side={row.candidate} k={k} stepNameOf={stepNameOf} />
                </td>
                <td className="px-3 py-2 max-sm:order-2 max-sm:p-0">
                  <span title={row.detail || undefined} className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ${BADGE[tone]}`}>
                    {words.label}
                  </span>
                  {row.alignment !== 'aligned' && <span className="ml-2 text-xs text-ink-muted">{alignmentLabel(row.alignment)}</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** One line when every step matches; otherwise only the differences. */
function StageDifferences({ alignment }: { alignment: StageAlignment }) {
  const renamed = alignment.matched.filter(([baseline, candidate]) => baseline !== candidate)
  const same = alignment.matched.length - renamed.length
  if (renamed.length === 0 && alignment.baseline_only.length === 0 && alignment.candidate_only.length === 0) {
    if (same === 0) return null
    return <p className="text-sm text-ink-muted">{same === 1 ? 'The one step matches between the runs.' : `All ${same} steps match between the runs.`}</p>
  }
  const ids = (list: string[]) =>
    list.map((id, index) => (
      <span key={id}>
        {index > 0 && ', '}
        <code className="font-mono text-xs text-ink">{id}</code>
      </span>
    ))
  return (
    <section aria-labelledby="stage-differences-title" className="space-y-1 text-sm">
      <h2 id="stage-differences-title" className="font-semibold text-ink">
        Steps that differ between the runs
      </h2>
      <ul className="list-disc space-y-0.5 pl-5 text-ink-muted">
        {renamed.map(([baseline, candidate]) => (
          <li key={`${baseline}:${candidate}`}>
            <code className="font-mono text-xs text-ink">{baseline}</code> in the baseline matches <code className="font-mono text-xs text-ink">{candidate}</code> in the
            candidate
          </li>
        ))}
        {alignment.baseline_only.length > 0 && <li>Only in the baseline: {ids(alignment.baseline_only)}</li>}
        {alignment.candidate_only.length > 0 && <li>Only in the candidate: {ids(alignment.candidate_only)}</li>}
      </ul>
      {same > 0 && <p className="text-ink-muted">{same === 1 ? 'The other step matches.' : `The other ${same} steps match.`}</p>}
    </section>
  )
}

interface Props {
  envelope: ComparisonEnvelope
  /** Every loaded page of paired rows (the envelope carries only the last page). */
  rows: JourneyDiffRow[]
  /** A step's display name for "Dropped by …"; the id when omitted. */
  stepNameOf?: (opId: string) => string
  onSelectEntity: (entity: string, queryId: string) => void
}

/** Correct documents that changed, then other changes and the unchanged rows (collapsed), then stage alignment. */
export default function CandidateLineageDiff({ envelope, rows, stepNameOf = (opId) => opId, onSelectEntity }: Props) {
  const { stage_alignment } = envelope.comparison
  const sorted = sortDiffRows(rows)
  const changed = sorted.filter((row) => row.change !== 'unchanged')
  const correct = changed.filter(isCorrect)
  const other = changed.filter((row) => !isCorrect(row))
  const unchanged = sorted.filter((row) => row.change === 'unchanged')
  const shared = {
    showQuery: !envelope.scope.query_id,
    singleNamespace: new Set(rows.map((row) => row.namespace)).size <= 1,
    k: envelope.scope.k,
    stepNameOf,
    onSelectEntity,
  }
  const otherCaption = `Other changes (${other.length})`
  const unchangedCaption = `Unchanged (${unchanged.length})`

  return (
    <section aria-label="Comparison" className="space-y-3">
      {rows.length === 0 ? (
        <p className="text-sm text-ink-muted">No documents to compare for this scope.</p>
      ) : (
        <>
          {correct.length > 0 ? (
            <DiffTable caption={`Correct documents that changed (${correct.length})`} captionVisible rows={correct} {...shared} />
          ) : (
            <p className="text-sm text-ink-muted">No correct document changed between the runs.</p>
          )}
          {other.length > 0 &&
            (correct.length > 0 ? (
              <details className="space-y-2">
                <summary className="cursor-pointer pt-2 text-sm font-semibold text-ink">{otherCaption}</summary>
                <DiffTable caption={otherCaption} captionVisible={false} rows={other} {...shared} />
              </details>
            ) : (
              <DiffTable caption={otherCaption} captionVisible rows={other} {...shared} />
            ))}
          {unchanged.length > 0 && (
            <details className="space-y-2">
              <summary className="cursor-pointer pt-2 text-sm font-semibold text-ink">{unchangedCaption}</summary>
              <DiffTable caption={unchangedCaption} captionVisible={false} rows={unchanged} {...shared} />
            </details>
          )}
        </>
      )}
      {stage_alignment && <StageDifferences alignment={stage_alignment} />}
    </section>
  )
}
