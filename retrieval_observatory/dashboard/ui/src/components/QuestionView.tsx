import { InvestigationStage, JourneyRow, PipelineGraph } from '../api'
import { verdictSentence } from '../utils/journeyWords'
import { cameFrom, displayEntity, entityKey, judgedText } from '../utils/queryDebugger'
import JourneyCard from './InvestigationDetail'
import { BADGE } from './InvestigationGraph'

// The parts of one question's page around the diagram: the header with the question and its
// verdict, the journey cards of its correct documents, and what it delivered instead.

const FOCUS_RING = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent'

export interface QuestionHeaderProps {
  queryId: string
  queryText: string | null | undefined
  k: number | null
  /** The question's correct documents. */
  relevant: JourneyRow[]
  /** The document the diagram follows. */
  focus: JourneyRow | null
  graph: PipelineGraph | null
  stages: InvestigationStage[] | null
  singleNamespace: boolean
  onBack: () => void
}

export function QuestionHeader({ queryId, queryText, k, relevant, focus, graph, stages, singleNamespace, onBack }: QuestionHeaderProps) {
  const delivered = relevant.filter((row) => row.outcome === 'relevant_delivered').length
  const tone = delivered < relevant.length ? 'negative' : 'positive'
  return (
    <header>
      <p className="flex flex-wrap items-baseline gap-x-2 text-xs">
        <button type="button" onClick={onBack} className={`text-accent hover:underline ${FOCUS_RING}`}>
          <span aria-hidden="true">← </span>All questions
        </button>
        <span aria-hidden="true" className="text-ink-faint">
          ·
        </span>
        <span className="text-ink-muted">
          Question <span className="font-mono">{queryId}</span>
        </span>
      </p>
      <h2 className="mt-1 text-[22px] font-semibold leading-tight text-ink">{queryText ? `“${queryText}”` : <span className="font-mono">{queryId}</span>}</h2>
      <p className="mt-2 text-sm leading-6 text-ink-muted">
        {relevant.length === 0 ? (
          'This question has no correct documents recorded.'
        ) : (
          <>
            <span className={`mr-2 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ${BADGE[tone]}`}>
              {delivered} of {relevant.length} correct {k != null ? `in the top ${k}` : 'delivered'}
            </span>
            {focus && (
              <>
                <span className="font-mono text-ink">{displayEntity(focus, singleNamespace)}</span>: {verdictSentence(focus, graph, stages, k)}
              </>
            )}
          </>
        )}
      </p>
    </header>
  )
}

export interface CorrectDocumentsProps {
  /** The question's correct documents, in table order. */
  relevant: JourneyRow[]
  /** The document the diagram follows: its card is expanded and carries the page's journey heading. */
  focus: JourneyRow | null
  graph: PipelineGraph | null
  stages: InvestigationStage[] | null
  k: number | null
  singleNamespace: boolean
  onSelect: (row: JourneyRow) => void
}

const key = (row: JourneyRow) => `${row.trace_id}|${entityKey(row)}`

export function CorrectDocuments({ relevant, focus, graph, stages, k, singleNamespace, onSelect }: CorrectDocumentsProps) {
  // A selected document that is not a correct one leads the card; the correct ones stay collapsed.
  const selectedOther = focus && focus.judgment !== 'relevant' ? focus : null
  const card = (row: JourneyRow, open: boolean) => (
    <li key={key(row)}>
      <JourneyCard row={row} graph={graph} stages={stages} k={k} expanded={open} isHeading={open} singleNamespace={singleNamespace} onSelect={() => onSelect(row)} />
    </li>
  )
  return (
    <div className="app-card space-y-4 p-4">
      {selectedOther && (
        <section aria-labelledby="selected-document-title" className="space-y-2">
          <h2 id="selected-document-title" className="text-sm font-semibold text-ink">
            Selected document
          </h2>
          <ul>{card(selectedOther, true)}</ul>
        </section>
      )}
      <section aria-labelledby="correct-documents-title" className="space-y-2">
        <h2 id="correct-documents-title" className="text-sm font-semibold text-ink">
          Correct documents ({relevant.length})
        </h2>
        {relevant.length === 0 ? (
          <p className="text-sm text-ink-muted">None recorded for this question.</p>
        ) : (
          <ul className="space-y-2">{relevant.map((row) => card(row, !selectedOther && focus != null && key(row) === key(focus)))}</ul>
        )}
      </section>
    </div>
  )
}

export interface DeliveredListProps {
  /** The question's final output (`final_membership=included`); 'failed' when that request failed. */
  rows: JourneyRow[] | 'failed'
  k: number | null
  /** Every correct document was delivered: the card is titled "Delivered", not "Delivered instead". */
  allDelivered: boolean
  singleNamespace: boolean
  isSource?: (opId: string) => boolean
}

export function DeliveredList({ rows, k, allDelivered, singleNamespace, isSource }: DeliveredListProps) {
  const cell = 'px-2 py-2 first:pl-0 last:pr-0'
  return (
    <section aria-labelledby="delivered-title" className="app-card p-4">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="delivered-title" className="text-sm font-semibold text-ink">
          {allDelivered ? 'Delivered' : 'Delivered instead'}
        </h2>
        {k != null && <span className="text-xs text-ink-muted">top {k}</span>}
      </div>
      {rows === 'failed' ? (
        <p role="status" className="mt-2 text-sm text-status-negative">
          Could not load the delivered list
        </p>
      ) : rows.length === 0 ? (
        <p className="mt-2 text-sm text-ink-muted">Nothing was delivered for this question.</p>
      ) : (
        <table className="mt-2 w-full text-left text-sm">
          <caption className="sr-only">Documents this question delivered, by rank</caption>
          <thead className="text-xs text-ink-faint">
            <tr>
              {['Rank', 'Document', 'Judged', 'Came from'].map((heading) => (
                <th key={heading} scope="col" className={`${cell} font-medium`}>
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...rows]
              .sort((a, b) => (a.final_rank ?? Infinity) - (b.final_rank ?? Infinity))
              .map((row) => (
                <tr key={key(row)} className="border-t border-hairline align-baseline">
                  <td className={`${cell} tabular-nums text-ink`}>{row.final_rank ?? '—'}</td>
                  <td className={`${cell} break-all font-mono text-xs text-ink`}>{displayEntity(row, singleNamespace)}</td>
                  <td className={`${cell} ${row.judgment === 'relevant' ? 'text-status-positive' : 'text-ink-muted'}`}>{judgedText(row)}</td>
                  <td className={`${cell} text-ink-muted`}>{cameFrom(row, isSource)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
