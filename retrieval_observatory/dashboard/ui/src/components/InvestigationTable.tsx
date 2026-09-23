import { KeyboardEvent, ReactNode } from 'react'
import { InvestigationDocumentRow, JourneyRow, QuerySummaryRow } from '../api'
import { DashboardSelection } from '../context/dashboardQuery'
import {
  entityKey,
  evidenceLabel,
  isJourneyRow,
  isQuerySummaryRow,
  nextIndexForKey,
  outcomeGlyph,
  outcomeLabel,
  principalLossBoundaries,
  queryRollups,
  QueryRollup,
  sortForView,
  sourceLanes,
  transitionText,
} from '../utils/queryDebugger'

// The one primary table of Investigate. Four row shapes share the chrome: a semantic table with
// caption and column headers, sortable headers with aria-sort, focusable selectable rows, a live
// summary line, the active URL filters as removable chips, and one reset control.

export type TableShape = 'queries' | 'query-candidates' | 'documents' | 'document-queries'

export interface SortState {
  key: string
  dir: 'asc' | 'desc'
}

export interface InvestigationTableProps {
  shape: TableShape
  /** The queries shape takes the stored per-query summaries, or journey rows (rolled up client-side) when a pair-level filter is set. */
  rows: JourneyRow[] | InvestigationDocumentRow[] | QuerySummaryRow[]
  selection: DashboardSelection
  /** Server-side row total when known; the live line reads "N rows, M shown" (or "N queries" for summaries). */
  total: number | null
  sort: SortState | null
  /** Names the SOURCE operators for the "Source lanes" column; without it every introducing operator counts. */
  isSource?: (opId: string) => boolean
  onSort: (sort: SortState | null) => void
  onSelect: (patch: Partial<DashboardSelection>) => void
  onReset: () => void
}

type SortValue = string | number | null

interface Column<Row> {
  key: string
  header: string
  cell: (row: Row) => ReactNode
  sortValue: (row: Row) => SortValue
  numeric?: boolean
}

const CAPTIONS: Record<TableShape, string> = {
  queries: 'Queries of this run with their relevant deliveries, misses and loss boundaries; activate a row to open its candidates',
  'query-candidates': 'Candidates of the selected query; activate a row to open its journey',
  documents: 'Documents of this run across queries; activate a row to open its queries',
  'document-queries': 'Queries in which the selected document appears; activate a row to open its journey',
}

function Outcome({ outcome }: { outcome: string }) {
  return (
    <>
      <span aria-hidden="true" className="mr-1.5 inline-block w-3 text-center">
        {outcomeGlyph(outcome)}
      </span>
      {outcomeLabel(outcome)}
    </>
  )
}

function mono(value: ReactNode): ReactNode {
  return <span className="font-mono text-xs">{value}</span>
}

// The per-query counts shared by a stored summary and a client-side rollup.
type QueryCounts = Pick<QuerySummaryRow, 'query_id' | 'relevant_delivered' | 'relevant_missed' | 'unjudged_included' | 'unknown_capture'>

const QUERY_COUNT_COLUMNS: Column<QueryCounts>[] = [
  {
    key: 'relevant',
    header: 'Relevant delivered / missed',
    cell: (row) => (
      <>
        <span aria-hidden="true">✓</span> {row.relevant_delivered} delivered · <span aria-hidden="true">✕</span> {row.relevant_missed} missed
      </>
    ),
    sortValue: (row) => row.relevant_missed,
    numeric: true,
  },
  { key: 'unjudged', header: 'Unjudged included', cell: (row) => row.unjudged_included, sortValue: (row) => row.unjudged_included, numeric: true },
  { key: 'unknown', header: 'Unknown capture', cell: (row) => row.unknown_capture, sortValue: (row) => row.unknown_capture, numeric: true },
]

function boundariesCell(boundaries: string[]): ReactNode {
  return boundaries.length ? mono(boundaries.join(', ')) : <span className="text-ink-faint">—</span>
}

const QUERY_COLUMNS: Column<QueryRollup>[] = [
  { key: 'query', header: 'Query', cell: (row) => mono(row.query_id), sortValue: (row) => row.query_id },
  ...QUERY_COUNT_COLUMNS,
  { key: 'boundaries', header: 'Principal loss boundaries', cell: (row) => boundariesCell(row.boundaries), sortValue: (row) => row.boundaries[0] ?? null },
]

const QUERY_SUMMARY_COLUMNS: Column<QuerySummaryRow>[] = [
  {
    key: 'query',
    header: 'Query',
    cell: (row) =>
      row.query_text ? (
        <>
          {row.query_text} <span className="ml-1 font-mono text-xs text-ink-muted">{row.query_id}</span>
        </>
      ) : (
        mono(row.query_id)
      ),
    sortValue: (row) => row.query_id,
  },
  ...QUERY_COUNT_COLUMNS,
  {
    key: 'boundaries',
    header: 'Principal loss boundaries',
    cell: (row) => boundariesCell(principalLossBoundaries(row.loss_boundaries)),
    sortValue: (row) => principalLossBoundaries(row.loss_boundaries)[0] ?? null,
  },
]

function candidateColumns(isSource?: (opId: string) => boolean): Column<JourneyRow>[] {
  return [
    { key: 'entity', header: 'Entity', cell: (row) => mono(entityKey(row)), sortValue: entityKey },
    {
      key: 'judgment',
      header: 'Judgment',
      cell: (row) => (
        <>
          {row.judgment}
          {row.grade != null && <span className="ml-1 text-xs text-ink-muted">grade {row.grade}</span>}
          {row.judgment_source && <span className="ml-1 text-xs text-ink-faint">({row.judgment_source})</span>}
        </>
      ),
      sortValue: (row) => row.judgment,
    },
    {
      key: 'lanes',
      header: 'Source lanes',
      cell: (row) => {
        const lanes = sourceLanes(row, isSource)
        return lanes.length ? mono(lanes.join(', ')) : <span className="text-ink-faint">not observed</span>
      },
      sortValue: (row) => sourceLanes(row, isSource).join(','),
    },
    {
      key: 'final',
      header: 'Final rank / membership',
      cell: (row) => (
        <>
          <span className="tabular-nums">{row.final_rank ?? '—'}</span> <span className="text-ink-muted">{row.final_membership}</span>
        </>
      ),
      sortValue: (row) => row.final_rank,
      numeric: true,
    },
    { key: 'outcome', header: 'Outcome', cell: (row) => <Outcome outcome={row.outcome} />, sortValue: (row) => row.outcome },
    { key: 'boundary', header: 'Loss boundary', cell: (row) => (row.loss_boundary ? mono(row.loss_boundary) : <span className="text-ink-faint">—</span>), sortValue: (row) => row.loss_boundary },
    {
      key: 'evidence',
      header: 'Evidence',
      cell: (row) => {
        const last = [...row.events].reverse().find((event) => event.kind === 'removed' || event.kind === 'unknown') ?? row.events[row.events.length - 1]
        return (
          <>
            {last ? evidenceLabel(last.reason_evidence) : 'unavailable'} · {row.capture_state === 'partial' && <span aria-hidden="true">⚠ </span>}
            {row.capture_state} capture
          </>
        )
      },
      sortValue: (row) => row.capture_state,
    },
  ]
}

const DOCUMENT_COLUMNS: Column<InvestigationDocumentRow>[] = [
  { key: 'entity', header: 'Document', cell: (row) => mono(row.entity), sortValue: (row) => row.entity },
  {
    key: 'relevant',
    header: 'Judged-relevant queries',
    cell: (row) => (
      <span title={row.judged_relevant_queries.join(', ')}>
        {row.judged_relevant_queries.length} of {row.queries}
      </span>
    ),
    sortValue: (row) => row.judged_relevant_queries.length,
    numeric: true,
  },
  { key: 'delivered', header: 'Delivered', cell: (row) => <><span aria-hidden="true">✓</span> {row.delivered}</>, sortValue: (row) => row.delivered, numeric: true },
  { key: 'excluded', header: 'Known downstream loss', cell: (row) => <><span aria-hidden="true">✕</span> {row.excluded}</>, sortValue: (row) => row.excluded, numeric: true },
  { key: 'unobserved', header: 'Unobserved', cell: (row) => <><span aria-hidden="true">○</span> {row.not_observed}</>, sortValue: (row) => row.not_observed, numeric: true },
  { key: 'unknown', header: 'Unknown', cell: (row) => <><span aria-hidden="true">◌</span> {row.unknown}</>, sortValue: (row) => row.unknown, numeric: true },
]

const DOCUMENT_QUERY_COLUMNS: Column<JourneyRow>[] = [
  { key: 'query', header: 'Query', cell: (row) => mono(row.query_id), sortValue: (row) => row.query_id },
  {
    key: 'judgment',
    header: 'Judgment for this entity',
    cell: (row) => (
      <>
        {row.judgment}
        {row.grade != null && <span className="ml-1 text-xs text-ink-muted">grade {row.grade}</span>}
      </>
    ),
    sortValue: (row) => row.judgment,
  },
  {
    key: 'outcome',
    header: 'Final outcome / rank',
    cell: (row) => (
      <>
        <Outcome outcome={row.outcome} /> <span className="tabular-nums text-ink-muted">{row.final_rank != null ? `#${row.final_rank}` : ''}</span>
      </>
    ),
    sortValue: (row) => row.outcome,
  },
  {
    key: 'transitions',
    header: 'Recorded transition sequence',
    cell: (row) => (row.events.length ? mono(transitionText(row)) : <span className="text-ink-faint">not observed</span>),
    sortValue: (row) => row.events.length,
    numeric: true,
  },
  {
    key: 'capture',
    header: 'Capture',
    cell: (row) => (
      <>
        {row.capture_state === 'partial' && <span aria-hidden="true">⚠ </span>}
        {row.capture_state}
      </>
    ),
    sortValue: (row) => row.capture_state,
  },
]

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
}

// Row type is erased here: each shape closes over its own columns, so the renderer stays shape-agnostic.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function shapeRows(props: InvestigationTableProps): Shaped<any> {
  const { shape, rows, selection, sort, isSource, total } = props
  const count = total ?? rows.length
  if (shape === 'documents') {
    const documents = rows.filter((row): row is InvestigationDocumentRow => !isJourneyRow(row) && !isQuerySummaryRow(row))
    return {
      columns: DOCUMENT_COLUMNS,
      display: applySort(documents, DOCUMENT_COLUMNS, sort),
      key: (row) => row.entity,
      patch: (row) => ({ entity: row.entity, query: null, trace: null }),
      selected: (row) => selection.entity === row.entity,
      line: `${count} rows, ${documents.length} shown`,
    }
  }
  if (shape === 'queries') {
    // Stored summaries carry every pair of each query; journey rows only arrive with a pair-level filter.
    const summaries = rows.filter(isQuerySummaryRow)
    if (summaries.length) {
      return {
        columns: QUERY_SUMMARY_COLUMNS,
        display: applySort(summaries, QUERY_SUMMARY_COLUMNS, sort),
        key: (row) => row.query_id,
        patch: (row) => ({ query: row.query_id, trace: row.trace_ids.length === 1 ? row.trace_ids[0] : null, entity: null }),
        selected: (row) => selection.query === row.query_id,
        line: `${count} queries`,
      }
    }
    const rollups = queryRollups(sortForView(rows.filter(isJourneyRow), 'queries'))
    return {
      columns: QUERY_COLUMNS,
      display: applySort(rollups, QUERY_COLUMNS, sort),
      key: (row) => row.query_id,
      patch: (row) => ({ query: row.query_id, trace: row.trace_ids.length === 1 ? row.trace_ids[0] : null, entity: null }),
      selected: (row) => selection.query === row.query_id,
      line: `${count} candidate rows across ${rollups.length} queries (filtered)`,
    }
  }
  const journeys = rows.filter(isJourneyRow)
  if (shape === 'query-candidates') {
    const columns = candidateColumns(isSource)
    return {
      columns,
      display: applySort(sortForView(journeys, 'queries'), columns, sort),
      key: (row) => `${row.trace_id}|${entityKey(row)}`,
      patch: (row) => ({ entity: entityKey(row), trace: row.trace_id }),
      selected: (row) => selection.entity === entityKey(row) && (!selection.trace || selection.trace === row.trace_id),
      line: `${count} rows, ${journeys.length} shown`,
    }
  }
  return {
    columns: DOCUMENT_QUERY_COLUMNS,
    display: applySort(sortForView(journeys, 'documents'), DOCUMENT_QUERY_COLUMNS, sort),
    key: (row) => `${row.trace_id}|${row.query_id}`,
    patch: (row) => ({ query: row.query_id, trace: row.trace_id }),
    selected: (row) => selection.query === row.query_id,
    line: `${count} rows, ${journeys.length} shown`,
  }
}

const headerButtonClass = 'inline-flex items-center gap-1 font-medium hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600'

export default function InvestigationTable(props: InvestigationTableProps) {
  const { shape, selection, sort, onSort, onSelect, onReset } = props
  const shaped = shapeRows(props)
  const chips: Array<[string, Partial<DashboardSelection>]> = []
  if (selection.stage) chips.push([`stage: ${selection.stage}`, { stage: null }])
  if (selection.outcome) chips.push([`outcome: ${outcomeLabel(selection.outcome)}`, { outcome: null }])

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
        <button type="button" onClick={onReset} className="ml-auto rounded border border-hairline px-2 py-0.5 text-xs text-ink hover:bg-surface-muted">
          Reset selection
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{CAPTIONS[shape]}</caption>
          <thead className="text-left text-xs text-ink-faint">
            <tr>
              {shaped.columns.map((column) => {
                const active = sort?.key === column.key
                return (
                  <th key={column.key} scope="col" aria-sort={active ? (sort!.dir === 'asc' ? 'ascending' : 'descending') : 'none'} className="px-3 py-2 font-medium">
                    <button type="button" onClick={() => toggleSort(column.key)} className={headerButtonClass}>
                      {column.header}
                      <span aria-hidden="true" className="text-[10px]">
                        {active ? (sort!.dir === 'asc' ? '▲' : '▼') : '↕'}
                      </span>
                    </button>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
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
                  className={`cursor-pointer border-t border-hairline hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-indigo-600 ${selected ? 'bg-accent-muted/40' : ''}`}
                >
                  {shaped.columns.map((column) => (
                    <td key={column.key} className={`px-3 py-2 ${column.numeric ? 'tabular-nums' : ''}`}>
                      {column.cell(row)}
                      {selected && column === shaped.columns[0] && <span className="ml-2 text-[10px] uppercase tracking-wide text-ink-faint">selected</span>}
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
