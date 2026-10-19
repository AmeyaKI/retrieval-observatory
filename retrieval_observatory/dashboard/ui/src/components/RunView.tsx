import { ReactNode, useState } from 'react'
import { JourneyRow, QuerySummaryRow } from '../api'
import { DashboardSelection } from '../context/dashboardQuery'
import { filterMissed, MissedQuestion, reasonChips, RunHeadlineWords } from '../utils/flowWords'
import { documentSentence } from '../utils/journeyWords'
import { displayEntity, splitEntity } from '../utils/queryDebugger'
import { BADGE } from './InvestigationGraph'
import InvestigationTable, { MissedRow, SortState } from './InvestigationTable'

// The parts of a run's page around the diagram: the headline that names the step losing the most
// correct documents, the list of questions that missed one (filtered by reason and by the selected
// step), and one document's header.

const FOCUS_RING = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent'
const SHOWN = 50

/** Numbers in ink semibold; a digit inside a word (the 25 of "bm25") is left alone. */
function emphasize(text: string): ReactNode {
  return text.split(/(\b\d+%?)/).map((part, index) =>
    index % 2 === 1 ? (
      <span key={index} className="font-semibold text-ink">
        {part}
      </span>
    ) : (
      part
    ),
  )
}

export function RunHeadline({ words }: { words: RunHeadlineWords }) {
  const at = words.lost ? words.headline.indexOf(words.lost) : -1
  return (
    <header>
      <h2 className="text-[22px] font-semibold leading-tight text-ink">
        {at < 0 ? (
          words.headline
        ) : (
          <>
            {words.headline.slice(0, at)}
            <span className="text-status-negative">{words.lost}</span>
            {words.headline.slice(at + words.lost!.length)}
          </>
        )}
      </h2>
      {words.lede.length > 0 && <p className="mt-2 max-w-4xl text-[15px] leading-6 text-ink-muted">{emphasize(words.lede.join(' '))}</p>}
    </header>
  )
}

export interface DocumentHeaderProps {
  /** The URL's `namespace:entity_id`. */
  entity: string
  rows: JourneyRow[]
  /** Questions the document appears in. */
  questions: number
  singleNamespace: boolean
  onBack: () => void
}

export function DocumentHeader({ entity, rows, questions, singleNamespace, onBack }: DocumentHeaderProps) {
  return (
    <header>
      <p className="flex flex-wrap items-baseline gap-x-2 text-xs">
        <button type="button" onClick={onBack} className={`text-accent hover:underline ${FOCUS_RING}`}>
          <span aria-hidden="true">← </span>All documents
        </button>
        <span aria-hidden="true" className="text-ink-faint">
          ·
        </span>
        <span className="text-ink-muted">
          Document <span className="font-mono">{displayEntity(splitEntity(entity), singleNamespace)}</span>
        </span>
      </p>
      <h2 className="mt-1 text-[22px] font-semibold leading-tight text-ink">{documentSentence(rows, questions)}</h2>
    </header>
  )
}

export interface MissedQuestionsProps {
  /** Every question with a missed correct document, from the flow folded like the diagram. */
  questions: MissedQuestion[]
  k: number
  selection: DashboardSelection
  /** The selected step as the folded flow names it, and its plain name; null without one. */
  stage: { id: string; name: string } | null
  /** The loaded stored summaries, for each question's number of correct documents. */
  summaries: Map<string, QuerySummaryRow>
  stepLabel: (opId: string) => string
  sort: SortState | null
  onSort: (sort: SortState | null) => void
  onSelect: (patch: Partial<DashboardSelection>) => void
}

const chipClass = `whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${FOCUS_RING}`
const CHIP_TONE: Record<string, string> = {
  retained_below_cutoff: BADGE.negative,
  relevant_excluded: BADGE.negative,
  not_observed: BADGE.neutral,
  insufficient_evidence: BADGE.warning,
}

/** Mount with a key of the filters so "Show more" starts over when they change. */
export function MissedQuestions({ questions, k, selection, stage, summaries, stepLabel, sort, onSort, onSelect }: MissedQuestionsProps) {
  const [limit, setLimit] = useState(SHOWN)
  const atStage = stage ? filterMissed(questions, { stage: stage.id }) : questions
  const shown = filterMissed(atStage, { outcome: selection.outcome })
  const rows: MissedRow[] = shown.slice(0, limit).map((question) => {
    const summary = summaries.get(question.query_id)
    const relevant = summary ? summary.relevant_delivered + summary.relevant_missed : question.none ? question.misses.length : null
    return { ...question, relevant }
  })
  const chips = reasonChips(atStage).map((chip) => {
    const active = selection.outcome === chip.outcome
    return (
      <button
        key={chip.outcome}
        type="button"
        aria-pressed={active}
        onClick={() => onSelect({ outcome: active ? null : chip.outcome })}
        className={`${chipClass} ${CHIP_TONE[chip.outcome]} ${active ? 'ring-2 ring-accent' : ''}`}
      >
        {chip.label}
      </button>
    )
  })
  return (
    <section aria-labelledby="missed-title" className="space-y-2">
      <h2 id="missed-title" className="pt-2 text-sm font-semibold text-ink">
        Questions that missed a correct document ({questions.length})
      </h2>
      {stage && (
        <div role="status" className="app-inset flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm text-ink">
          <span>{atStage.length > 0 ? `Showing questions where ${stage.name} lost a correct document (${atStage.length})` : `${stage.name} lost no correct documents.`}</span>
          <button type="button" onClick={() => onSelect({ stage: null })} className={`rounded border border-hairline bg-surface px-2 py-0.5 text-xs text-ink hover:bg-surface-muted ${FOCUS_RING}`}>
            Clear
          </button>
        </div>
      )}
      {atStage.length > 0 && (
        <InvestigationTable
          shape="missed"
          rows={rows}
          selection={selection}
          total={shown.length}
          sort={sort}
          k={k}
          stepLabel={stepLabel}
          actions={chips}
          onSort={onSort}
          onSelect={onSelect}
        />
      )}
      {shown.length > limit && (
        <p className="flex items-center gap-3 text-xs text-ink-muted">
          <span>
            {limit} of {shown.length} questions
          </span>
          <button type="button" onClick={() => setLimit((value) => value + SHOWN)} className={`font-medium text-accent hover:underline ${FOCUS_RING}`}>
            Show more
          </button>
        </p>
      )}
    </section>
  )
}
