import { KeyboardEvent, ReactNode } from 'react'
import { FlowMiss, InvestigationDocumentRow, JourneyRow, QuerySummaryRow } from '../api'
import { DashboardSelection } from '../context/dashboardQuery'
import { MissedQuestion, missLine, plural } from '../utils/flowWords'
import { ranksTrail } from '../utils/journeyWords'
import {
  cameFrom,
  displayEntity,
  entityKey,
  isJourneyRow,
  isQuerySummaryRow,
  judgedText,
  nextIndexForKey,
  outcomeLabel,
  outcomeText,
  outcomeTone,
  OutcomeTone,
  queryRollups,
  sortForView,
  splitEntity,
} from '../utils/queryDebugger'

// The tables of Investigate. Five row shapes share the chrome: a semantic table with caption and
// column headers, sortable headers with aria-sort (an arrow on the active column only), focusable
// selectable rows, a live summary line, the active URL filters as removable chips with "Clear
// filters" while one is set, and rows that stack into blocks below 640 px instead of the page
// scrolling sideways.

export type TableShape = 'queries' | 'missed' | 'query-candidates' | 'documents' | 'document-queries'

/** One row of the missed list: a question's missed correct documents and how many correct documents it has. */
export interface MissedRow extends MissedQuestion {
  /** From its stored summary (or all missed when it got none); null when unknown. */
  relevant: number | null
}

export interface SortState {
  key: string
  dir: 'asc' | 'desc'
}

export interface InvestigationTableProps {
  shape: TableShape
  /** The queries shape takes the stored per-query summaries, or journey rows (rolled up client-side) when a pair-level filter is set. */
  rows: JourneyRow[] | InvestigationDocumentRow[] | QuerySummaryRow[] | MissedRow[]
  selection: DashboardSelection
  /** Server-side row total when known (the missed list: the rows after its filters). */
  total: number | null
  sort: SortState | null
  /** Names the SOURCE operators for the "Came from" column; without it every introducing operator counts. */
  isSource?: (opId: string) => boolean
  /** The cutoff, for "pushed out of the top k" and the "Correct in top k" column. */
  k?: number | null
  /** Show ids without their namespace (the scope has only one). */
  singleNamespace?: boolean
  /** A step's plain name; the id when absent. */
  stepLabel?: (opId: string) => string
  /** Each question's missed correct documents (from the flow): the questions' "What happened" lines and texts. */
  misses?: Map<string, FlowMiss[]>
  /** Controls at the right of the toolbar (the missed list's reason filters). */
  actions?: ReactNode
  onSort: (sort: SortState | null) => void
  onSelect: (patch: Partial<DashboardSelection>) => void
}

type SortValue = string | number | null

interface Column<Row> {
  key: string
  header: string
  cell: (row: Row) => ReactNode
  sortValue: (row: Row) => SortValue
  numeric?: boolean
  /** Below 640 px (stacked rows): order and look of the cell. */
  stack: string
}

const CAPTIONS: Record<TableShape, string> = {
  queries: 'Questions of this run with their correct documents in the top k; activate a row to open the question',
  missed: 'Questions that missed a correct document and what happened to it; activate a row to open the question',
  'query-candidates': 'Candidates of this question; activate a row to follow that document',
  documents: 'Documents of this run with the questions they are correct for; activate a row to open the document',
  'document-queries': 'Questions in which the selected document appears; activate a row to follow it',
}

const TONE_TEXT: Record<OutcomeTone, string> = {
  positive: 'text-status-positive',
  negative: 'text-status-negative',
  warning: 'text-status-warning',
  neutral: 'text-ink-muted',
}

// Stacked rows below 640 px: the lead cell on line one (with what happened, when it fits), the rest after.
export const LINE_TWO = 'max-sm:text-xs max-sm:text-ink-muted'
export const DOT = "max-sm:before:mr-2 max-sm:before:content-['·']"
const QUESTION_STACK = 'max-sm:order-1 max-sm:basis-full'
const WHAT_STACK = 'max-sm:order-5 max-sm:basis-full sm:w-2/5'
/** Short cells keep one line on a wide screen so the question column takes the slack. */
const NOWRAP = 'sm:whitespace-nowrap'

/** A word that stands in for the hidden column header on a phone. */
function phone(text: string): ReactNode {
  return <span className="sm:hidden">{text}</span>
}

function questionCell(id: string, text: string | null | undefined): ReactNode {
  return text ? (
    <>
      {text} <span className="ml-1 whitespace-nowrap font-mono text-xs text-ink-muted">{id}</span>
    </>
  ) : (
    <span className="whitespace-nowrap font-mono text-xs">{id}</span>
  )
}

function correctHeader(k: number | null): string {
  return k != null ? `Correct in top ${k}` : 'Correct delivered'
}

/** `{d} of {n}`: green when all were delivered, red when none, amber in between. */
function correctCell(delivered: number, relevant: number, k: number | null): ReactNode {
  const tone = delivered === relevant ? TONE_TEXT.positive : delivered === 0 ? TONE_TEXT.negative : TONE_TEXT.warning
  return (
    <span className={`font-semibold ${tone}`}>
      {delivered} of {relevant}
      {phone(k != null ? ` correct in top ${k}` : ' correct delivered')}
    </span>
  )
}

function missLines(misses: FlowMiss[], k: number | null, nameOf: (opId: string) => string): ReactNode {
  return misses.map((miss) => {
    const { text, sub } = missLine(miss, k, nameOf)
    return (
      <span key={`${miss.trace_id}|${miss.namespace}:${miss.entity_id}`} className="block">
        {text}
        {sub && <span className="block text-xs text-ink-muted">{sub}</span>}
      </span>
    )
  })
}

function missedColumns(k: number | null, nameOf: (opId: string) => string): Column<MissedRow>[] {
  const delivered = (row: MissedRow) => (row.relevant != null ? Math.max(0, row.relevant - row.misses.length) : null)
  return [
    { key: 'query', header: 'Question', cell: (row) => questionCell(row.query_id, row.query_text), sortValue: (row) => row.query_id, stack: QUESTION_STACK },
    {
      key: 'correct',
      header: correctHeader(k),
      cell: (row) => (row.relevant != null ? correctCell(delivered(row)!, row.relevant, k) : <span className={`font-semibold ${TONE_TEXT.negative}`}>{row.misses.length} missed</span>),
      sortValue: delivered,
      numeric: true,
      stack: `max-sm:order-4 ${NOWRAP}`,
    },
    { key: 'outcome', header: 'What happened', cell: (row) => missLines(row.misses, k, nameOf), sortValue: (row) => missLine(row.misses[0], k, nameOf).text, stack: WHAT_STACK },
  ]
}

// The per-query counts shared by a stored summary and a client-side rollup.
type QueryCounts = Pick<QuerySummaryRow, 'query_id' | 'relevant_delivered' | 'relevant_missed' | 'trace_ids'> & { query_text?: string | null }

function queryColumns(k: number | null, misses: Map<string, FlowMiss[]>, nameOf: (opId: string) => string): Column<QueryCounts>[] {
  return [
    {
      key: 'query',
      header: 'Question',
      cell: (row) => questionCell(row.query_id, row.query_text ?? misses.get(row.query_id)?.[0]?.query_text),
      sortValue: (row) => row.query_id,
      stack: QUESTION_STACK,
    },
    {
      key: 'correct',
      header: correctHeader(k),
      cell: (row) => {
        const relevant = row.relevant_delivered + row.relevant_missed
        return relevant > 0 ? correctCell(row.relevant_delivered, relevant, k) : <span className="text-ink-faint">—</span>
      },
      sortValue: (row) => row.relevant_missed,
      numeric: true,
      stack: `max-sm:order-4 ${NOWRAP}`,
    },
    {
      key: 'outcome',
      header: 'What happened',
      cell: (row) => {
        const own = misses.get(row.query_id)
        if (own?.length) return missLines(own, k, nameOf)
        if (row.relevant_missed > 0) return <span className={TONE_TEXT.negative}>{row.relevant_missed} missed</span>
        return row.relevant_delivered > 0 ? 'All delivered' : <span className="text-ink-muted">No correct documents recorded</span>
      },
      sortValue: (row) => row.relevant_missed,
      stack: WHAT_STACK,
    },
  ]
}

function candidateColumns(k: number | null, singleNamespace: boolean, isSource?: (opId: string) => boolean): Column<JourneyRow>[] {
  return [
    {
      key: 'rank',
      header: 'Rank',
      cell: (row) => (
        <>
          {phone('Rank ')}
          {row.final_rank ?? '—'}
        </>
      ),
      sortValue: (row) => row.final_rank,
      numeric: true,
      stack: `max-sm:order-4 ${LINE_TWO}`,
    },
    {
      key: 'entity',
      header: 'Document',
      cell: (row) => <span className="font-mono text-xs max-sm:break-all sm:whitespace-nowrap">{displayEntity(row, singleNamespace)}</span>,
      sortValue: entityKey,
      stack: 'max-sm:order-1 max-sm:min-w-0 max-sm:flex-1',
    },
    { key: 'judged', header: 'Judged', cell: judgedText, sortValue: (row) => row.judgment, stack: `max-sm:order-5 ${LINE_TWO} ${DOT} ${NOWRAP}` },
    { key: 'from', header: 'Came from', cell: (row) => cameFrom(row, isSource), sortValue: (row) => cameFrom(row, isSource), stack: `max-sm:order-6 ${LINE_TWO} ${DOT}` },
    {
      key: 'outcome',
      header: 'What happened',
      cell: (row) => <span className={TONE_TEXT[outcomeTone(row.outcome)]}>{outcomeText(row, k)}</span>,
      sortValue: (row) => row.outcome,
      stack: `max-sm:order-2 ${NOWRAP}`,
    },
  ]
}

/** Correct-document misses of a document: its correct questions it was not delivered in. */
function documentMisses(row: InvestigationDocumentRow): number {
  return Math.max(0, row.judged_relevant_queries.length - row.delivered)
}

function documentColumns(singleNamespace: boolean): Column<InvestigationDocumentRow>[] {
  return [
    {
      key: 'entity',
      header: 'Document',
      cell: (row) => <span className="font-mono text-xs max-sm:break-all sm:whitespace-nowrap">{displayEntity(splitEntity(row.entity), singleNamespace)}</span>,
      sortValue: (row) => row.entity,
      stack: 'max-sm:order-1 max-sm:basis-full',
    },
    {
      key: 'relevant',
      header: 'Correct for',
      cell: (row) =>
        row.judged_relevant_queries.length > 0 ? (
          <span title={row.judged_relevant_queries.join(', ')}>
            {phone('Correct for ')}
            {plural(row.judged_relevant_queries.length, 'question')}
          </span>
        ) : (
          <span className="text-ink-faint">
            {phone('Correct for ')}—
          </span>
        ),
      sortValue: (row) => row.judged_relevant_queries.length,
      numeric: true,
      stack: `max-sm:order-4 ${LINE_TWO} ${NOWRAP}`,
    },
    {
      key: 'delivered',
      header: 'Delivered',
      cell: (row) => (
        <>
          {phone('Delivered ')}
          {row.delivered}
        </>
      ),
      sortValue: (row) => row.delivered,
      numeric: true,
      stack: `max-sm:order-5 ${LINE_TWO} ${DOT} ${NOWRAP}`,
    },
    {
      key: 'missed',
      header: 'Missed',
      cell: (row) => (
        <span className={documentMisses(row) > 0 ? TONE_TEXT.negative : undefined}>
          {phone('Missed ')}
          {documentMisses(row)}
        </span>
      ),
      sortValue: documentMisses,
      numeric: true,
      stack: `max-sm:order-6 ${LINE_TWO} ${DOT} ${NOWRAP}`,
    },
    {
      key: 'queries',
      header: 'Appears in',
      cell: (row) => (
        <>
          {phone('Appears in ')}
          {plural(row.queries, 'question')}
        </>
      ),
      sortValue: (row) => row.queries,
      numeric: true,
      stack: `max-sm:order-7 ${LINE_TWO} ${DOT} ${NOWRAP}`,
    },
  ]
}

function documentQueryColumns(k: number | null, misses: Map<string, FlowMiss[]>, nameOf: (opId: string) => string): Column<JourneyRow>[] {
  return [
    {
      key: 'query',
      header: 'Question',
      cell: (row) => questionCell(row.query_id, misses.get(row.query_id)?.[0]?.query_text),
      sortValue: (row) => row.query_id,
      stack: 'max-sm:order-1 max-sm:min-w-0 max-sm:flex-1',
    },
    { key: 'judged', header: 'Judged', cell: judgedText, sortValue: (row) => row.judgment, stack: `max-sm:order-4 ${LINE_TWO} ${NOWRAP}` },
    {
      key: 'outcome',
      header: 'What happened',
      cell: (row) => <span className={TONE_TEXT[outcomeTone(row.outcome)]}>{outcomeText(row, k)}</span>,
      sortValue: (row) => row.outcome,
      stack: `max-sm:order-2 ${NOWRAP}`,
    },
    { key: 'ranks', header: 'Ranks', cell: (row) => ranksTrail(row, nameOf), sortValue: (row) => row.final_rank, stack: `max-sm:order-5 ${LINE_TWO} ${DOT}` },
  ]
}

function compare(a: SortValue, b: SortValue): number {
  if (a === b) return 0
  if (a === null) return 1
  if (b === null) return -1
  return typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b))
}

export function applySort<Row>(rows: Row[], columns: Column<Row>[], sort: SortState | null): Row[] {
  if (!sort) return rows
  const column = columns.find((c) => c.key === sort.key)
  if (!column) return rows
  const sign = sort.dir === 'asc' ? 1 : -1
  return [...rows].map((row, index) => ({ row, index })).sort((x, y) => sign * compare(column.sortValue(x.row), column.sortValue(y.row)) || x.index - y.index).map(({ row }) => row)
}

function Chip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-hairline bg-surface-muted px-2 py-0.5 text-xs text-ink">
      {label}
      <button type="button" onClick={onRemove} aria-label={`Remove filter ${label}`} className="text-ink-muted hover:text-ink">
        ✕
      </button>
    </span>
  )
}

interface Shaped<Row> {
  columns: Column<Row>[]
  display: Row[]
  key: (row: Row) => string
  patch: (row: Row) => Partial<DashboardSelection>
  selected: (row: Row) => boolean
  /** The live summary line above the table. */
  line: string
  /** The URL filters show as chips in the toolbar (the missed list shows them above it instead). */
  chips: boolean
}

// Row type is erased here: each shape closes over its own columns, so the renderer stays shape-agnostic.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function shapeRows(props: InvestigationTableProps): Shaped<any> {
  const { shape, selection, sort, isSource, total, k = null, singleNamespace = false, misses = new Map(), stepLabel = (opId: string) => opId } = props
  const count = total ?? props.rows.length
  const openQuestion = (row: { query_id: string; trace_ids: string[] }) => ({ query: row.query_id, trace: row.trace_ids.length === 1 ? row.trace_ids[0] : null, entity: null })
  if (shape === 'missed') {
    const missed = props.rows as MissedRow[]
    const columns = missedColumns(k, stepLabel)
    return {
      columns,
      display: applySort(missed, columns, sort),
      key: (row) => row.query_id,
      patch: (row) => ({ query: row.query_id, trace: row.trace_id, entity: null }),
      selected: (row) => selection.query === row.query_id,
      line: `${plural(count, 'question')} · ${missed.length} shown`,
      chips: false,
    }
  }
  const rows = props.rows as Array<JourneyRow | InvestigationDocumentRow | QuerySummaryRow>
  if (shape === 'documents') {
    const documents = rows.filter((row): row is InvestigationDocumentRow => !isJourneyRow(row) && !isQuerySummaryRow(row))
    // Documents that missed a question they are correct for lead; the server order otherwise.
    const ordered = [...documents.filter((row) => documentMisses(row) > 0), ...documents.filter((row) => documentMisses(row) === 0)]
    const columns = documentColumns(singleNamespace)
    return {
      columns,
      display: applySort(ordered, columns, sort),
      key: (row) => row.entity,
      patch: (row) => ({ entity: row.entity, query: null, trace: null }),
      selected: (row) => selection.entity === row.entity,
      line: `${plural(count, 'document')} · ${documents.length} shown`,
      chips: true,
    }
  }
  if (shape === 'queries') {
    // Stored summaries carry every pair of each query; journey rows only arrive with a pair-level filter.
    const columns = queryColumns(k, misses, stepLabel)
    const summaries = rows.filter(isQuerySummaryRow)
    const rollups = summaries.length ? [] : queryRollups(sortForView(rows.filter(isJourneyRow), 'queries'))
    return {
      columns,
      display: applySort<QueryCounts>(summaries.length ? summaries : rollups, columns, sort),
      key: (row) => row.query_id,
      patch: openQuestion,
      selected: (row) => selection.query === row.query_id,
      line: summaries.length ? plural(count, 'question') : `${plural(count, 'candidate row')} across ${plural(rollups.length, 'question')} (filtered)`,
      chips: true,
    }
  }
  const journeys = rows.filter(isJourneyRow)
  if (shape === 'query-candidates') {
    const columns = candidateColumns(k, singleNamespace, isSource)
    return {
      columns,
      display: applySort(sortForView(journeys, 'queries'), columns, sort),
      key: (row) => `${row.trace_id}|${entityKey(row)}`,
      patch: (row) => ({ entity: entityKey(row), trace: row.trace_id }),
      selected: (row) => selection.entity === entityKey(row) && (!selection.trace || selection.trace === row.trace_id),
      line: `${plural(count, 'candidate')} · ${journeys.length} shown`,
      chips: true,
    }
  }
  const columns = documentQueryColumns(k, misses, stepLabel)
  return {
    columns,
    display: applySort(sortForView(journeys, 'documents'), columns, sort),
    key: (row) => `${row.trace_id}|${row.query_id}`,
    patch: (row) => ({ query: row.query_id, trace: row.trace_id }),
    selected: (row) => selection.query === row.query_id,
    line: `${plural(count, 'question')} · ${journeys.length} shown`,
    chips: true,
  }
}

const FOCUS = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent'
const headerButtonClass = `inline-flex items-center gap-1 whitespace-nowrap font-medium hover:text-ink ${FOCUS}`
const SELECTED_BAR = 'shadow-[inset_3px_0_0_0_rgb(var(--accent))]'
const resetClass = `rounded border border-hairline px-2 py-0.5 text-xs text-ink hover:bg-surface-muted ${FOCUS}`
export const STACKED_ROW = "max-sm:flex max-sm:flex-wrap max-sm:items-baseline max-sm:gap-x-2 max-sm:px-3 max-sm:py-2 max-sm:after:order-3 max-sm:after:basis-full max-sm:after:content-['']"

export default function InvestigationTable(props: InvestigationTableProps) {
  const { shape, selection, sort, stepLabel, actions, onSort, onSelect } = props
  const shaped = shapeRows(props)
  const chips: Array<[string, Partial<DashboardSelection>]> = []
  if (shaped.chips && selection.stage) chips.push([`Lost at ${stepLabel ? stepLabel(selection.stage) : selection.stage}`, { stage: null }])
  if (shaped.chips && selection.outcome) chips.push([outcomeLabel(selection.outcome), { outcome: null }])

  const toggleSort = (key: string) => {
    if (!sort || sort.key !== key) onSort({ key, dir: 'asc' })
    else if (sort.dir === 'asc') onSort({ key, dir: 'desc' })
    else onSort(null)
  }

  const onRowKey = (event: KeyboardEvent<HTMLTableRowElement>, index: number, patch: Partial<DashboardSelection>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onSelect(patch)
      return
    }
    const next = nextIndexForKey(event.key, index, shaped.display.length)
    if (next === null) return
    event.preventDefault()
    const sibling = event.currentTarget.parentElement?.children[next]
    if (sibling instanceof HTMLElement) sibling.focus()
  }

  return (
    <div className="app-card">
      <div className="flex flex-wrap items-center gap-2 border-b border-hairline px-3 py-2 text-xs">
        <p aria-live="polite" className="text-ink-muted">
          {shaped.line}
        </p>
        {chips.map(([label, patch]) => (
          <Chip key={label} label={label} onRemove={() => onSelect(patch)} />
        ))}
        {chips.length > 0 && (
          <button type="button" onClick={() => onSelect({ stage: null, outcome: null })} className={`ml-auto ${resetClass}`}>
            Clear filters
          </button>
        )}
        {actions && <div className="ml-auto flex flex-wrap gap-2">{actions}</div>}
      </div>
      <div className="overflow-x-auto">
        {/* Rows turn into stacked blocks on a phone, so the table never needs a floor width. */}
        <table className="w-full text-sm max-sm:block">
          <caption className="sr-only">{CAPTIONS[shape]}</caption>
          <thead className="text-left text-xs text-ink-faint max-sm:sr-only">
            <tr>
              {shaped.columns.map((column) => {
                const active = sort?.key === column.key
                return (
                  <th key={column.key} scope="col" aria-sort={active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-3 py-2 font-medium">
                    <button type="button" onClick={() => toggleSort(column.key)} className={headerButtonClass}>
                      {column.header}
                      {active && <span aria-hidden="true">{sort!.dir === 'asc' ? '▲' : '▼'}</span>}
                    </button>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody className="max-sm:block">
            {shaped.display.map((row, index) => {
              const selected = shaped.selected(row)
              const patch = shaped.patch(row)
              return (
                <tr
                  key={shaped.key(row)}
                  tabIndex={0}
                  aria-selected={selected}
                  onClick={() => onSelect(patch)}
                  onKeyDown={(event) => onRowKey(event, index, patch)}
                  className={`cursor-pointer border-t border-hairline align-top hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent ${STACKED_ROW} ${selected ? SELECTED_BAR : ''}`}
                >
                  {shaped.columns.map((column) => (
                    <td key={column.key} className={`px-3 py-2 ${column.numeric ? 'tabular-nums' : ''} max-sm:p-0 ${column.stack}`}>
                      {column.cell(row)}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
