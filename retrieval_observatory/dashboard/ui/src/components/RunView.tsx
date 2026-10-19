import { ReactNode, useState } from 'react'
import { JourneyRow } from '../api'
import { DashboardSelection } from '../context/dashboardQuery'
import { filterMissed, MissedDocument, MissedQuestion, plural, reasonChips, RunHeadlineWords } from '../utils/flowWords'
import { documentSentence } from '../utils/journeyWords'
import { displayEntity, splitEntity } from '../utils/queryDebugger'
import { BADGE } from './InvestigationGraph'
import InvestigationTable, { SortState } from './InvestigationTable'

// The parts of a run's page around the diagram: the headline that names the step losing the most
// correct documents, the lists of questions and of correct documents that missed the top k (filtered
// by reason and by the selected step), and one document's header.

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
  /** Every question (or, with `kind="documents"`, every correct document) with a miss, from the flow folded like the diagram. */
  questions: MissedQuestion[] | MissedDocument[]
  kind?: 'questions' | 'documents'
  /** Show document ids without their namespace (the documents list). */
  singleNamespace?: boolean
  k: number
  selection: DashboardSelection
  /** The selected step as the folded flow names it, and its plain name; null without one. */
  stage: { id: string; name: string } | null
  stepLabel: (opId: string) => string
  sort: SortState | null
  onSort: (sort: SortState | null) => void
  onSelect: (patch: Partial<DashboardSelection>) => void
}

const chipClass = `whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${FOCUS_RING}`
const resetClass = `rounded border border-hairline bg-surface px-2 py-0.5 text-xs text-ink hover:bg-surface-muted ${FOCUS_RING}`
const CHIP_TONE: Record<string, string> = {
  retained_below_cutoff: BADGE.negative,
  relevant_excluded: BADGE.negative,
  not_observed: BADGE.neutral,
  insufficient_evidence: BADGE.warning,
}

/** Mount with a key of the filters so "Show more" starts over when they change. */
export function MissedQuestions({ questions, kind = 'questions', singleNamespace, k, selection, stage, stepLabel, sort, onSort, onSelect }: MissedQuestionsProps) {
  const [limit, setLimit] = useState(SHOWN)
  const documents = kind === 'documents'
  const rows: Array<MissedQuestion | MissedDocument> = questions
  const atStage = stage ? filterMissed(rows, { stage: stage.id }) : rows
  const shown = filterMissed(atStage, { outcome: selection.outcome })
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
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-2">
        <h2 id="missed-title" className="text-sm font-semibold text-ink">
          {documents ? 'Correct documents that were missed' : 'Questions that missed a correct document'} ({questions.length})
        </h2>
        {/* Any filter, even a reason no chip offers, can be cleared from here. */}
        {(selection.stage || selection.outcome) && (
          <button type="button" onClick={() => onSelect({ stage: null, outcome: null })} className={resetClass}>
            Clear filters
          </button>
        )}
      </div>
      {stage && (
        <div role="status" className="app-inset flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm text-ink">
          <span>
            {atStage.length === 0
              ? `${stage.name} lost no correct documents.`
              : documents
                ? `Showing correct documents that ${stage.name} lost (${atStage.length})`
                : `Showing questions where ${stage.name} lost a correct document (${atStage.length})`}
          </span>
          <button type="button" onClick={() => onSelect({ stage: null })} className={resetClass}>
            Clear
          </button>
        </div>
      )}
      {atStage.length > 0 && (
        <InvestigationTable
          shape={documents ? 'missed-documents' : 'missed'}
          rows={shown.slice(0, limit) as MissedQuestion[] | MissedDocument[]}
          singleNamespace={singleNamespace}
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
            {limit} of {plural(shown.length, documents ? 'document' : 'question')}
          </span>
          <button type="button" onClick={() => setLimit((value) => value + SHOWN)} className={`font-medium text-accent hover:underline ${FOCUS_RING}`}>
            Show more
          </button>
        </p>
      )}
    </section>
  )
}
