import { useEffect, useRef, useState } from 'react'
import {
  buildInvestigationProjection,
  ComparisonEnvelope,
  fetchInvestigationComparison,
  fetchInvestigationComparisonQuery,
  fetchInvestigationDocument,
  fetchInvestigationDocuments,
  fetchInvestigationQueries,
  fetchInvestigationQuery,
  fetchPipelineGraphs,
  InvestigationDocumentRow,
  InvestigationEnvelope,
  InvestigationFinding,
  InvestigationParams,
  InvestigationStage,
  isStageSummary,
  JourneyDiffRow,
  JourneyRow,
  PipelineGraph,
  QuerySummaryRow,
  StageSummary,
} from '../api'
import { useDashboardContext } from '../context/DashboardContext'
import { DashboardSelection } from '../context/dashboardQuery'
import { auditLink, buildHash } from '../utils/focusedRoutes'
import { entityKey, isJourneyRow, OUTCOME_LABELS, pathHighlight, stageFilter } from '../utils/queryDebugger'
import CandidateLineageDiff from './CandidateLineageDiff'
import InvestigationDetail from './InvestigationDetail'
import InvestigationGraph from './InvestigationGraph'
import InvestigationTable, { SortState, TableShape } from './InvestigationTable'
import OperatorInspector from './OperatorInspector'

// Investigate: scope bar (shell) → pipeline diagram → one primary table → selected journey detail.
// Every selection lives in the URL (updateSelection); the only component state is request
// phases, table sort and the graph's collapse/zoom. Two request streams, each sequence-guarded:
// the scope stream (run-union graph + stored stage aggregates, once per db/run/pipeline) and the
// view stream (the list or drill-down the URL names). With `compare=` set on the queries view the
// view stream asks for paired journey rows against that baseline run instead; the scope stream
// still draws the selected (candidate) run's graph.

export const PAGE_SIZE = 50

/** Re-exported for the shell and tests that read the outcome vocabulary from this module. */
export { OUTCOME_LABELS, entityKey }

export interface PipelineHint {
  runId: string
  ids: string[]
}

// The queries list carries stored per-query summaries (`scope.rows_kind === 'query_summaries'`) unless a
// pair-level filter is set, in which case it carries the matching journey rows.
type Row = JourneyRow | QuerySummaryRow | InvestigationDocumentRow | JourneyDiffRow
type Envelope =
  | InvestigationEnvelope<JourneyRow>
  | InvestigationEnvelope<JourneyRow | QuerySummaryRow>
  | InvestigationEnvelope<InvestigationDocumentRow>
  | ComparisonEnvelope
type Mode = TableShape

function isComparison(envelope: Envelope): envelope is ComparisonEnvelope {
  return 'comparison' in envelope
}

/** A diff row also carries `query_id`; only a journey row carries its events. */
function isJourney(row: Row): row is JourneyRow {
  return 'events' in row && isJourneyRow(row)
}

/** Comparison mode: the queries view diffed against a baseline run; the documents view stays single-run. */
function comparing(selection: DashboardSelection): boolean {
  return Boolean(selection.compare) && selection.view === 'queries'
}

export interface InvestigationError {
  message: string
  status: number | null
  code: string | null
  detail: string | null
}

/** api.ts surfaces non-2xx responses as `label: STATUS TEXT — body`; recover the service's {code, detail}. */
export function describeInvestigationError(error: unknown): InvestigationError {
  const message = error instanceof Error ? error.message : String(error)
  const head = message.match(/:\s(\d{3})\s[^—]*(?:—\s([\s\S]*))?$/)
  const status = head ? Number(head[1]) : null
  const body = head?.[2] ?? ''
  let code: string | null = null
  let detail: string | null = null
  try {
    const parsed = JSON.parse(body) as { detail?: unknown }
    const inner = parsed.detail
    if (inner && typeof inner === 'object') {
      code = typeof (inner as { code?: unknown }).code === 'string' ? (inner as { code: string }).code : null
      detail = typeof (inner as { detail?: unknown }).detail === 'string' ? (inner as { detail: string }).detail : null
    } else if (typeof inner === 'string') detail = inner
  } catch {
    code = body.match(/"code"\s*:\s*"([a-z_]+)"/)?.[1] ?? null
    detail = body.match(/"detail"\s*:\s*"([^"]*)/)?.[1] ?? null
  }
  if (!code && status === 409) code = 'read_only'
  return { message, status, code, detail }
}

/** Pipeline ids named by a `pipeline_required` detail (`run 'r' has pipelines ['a', 'b']; …` or a JSON list). */
export function pipelineIdsFromDetail(detail: string | null): string[] {
  if (!detail) return []
  const list = detail.match(/\[([^\]]*)\]/)?.[1]
  if (!list) return []
  return list
    .split(',')
    .map((item) => item.trim().replace(/^['"]|['"]$/g, ''))
    .filter(Boolean)
}

export function modeFor(selection: DashboardSelection): Mode {
  if (selection.view === 'documents') return selection.entity ? 'document-queries' : 'documents'
  return selection.query ? 'query-candidates' : 'queries'
}

const DRILL_DOWN: ReadonlySet<Mode> = new Set<Mode>(['query-candidates', 'document-queries'])

/** Lists filter by stage on the server (they paginate); drill-downs filter client-side so branch-local
 * removals at that stage stay visible next to the final loss boundary. */
function requestFor(db: string, run: string, selection: DashboardSelection, cursor: string | null): Promise<Envelope> {
  const mode = modeFor(selection)
  if (comparing(selection)) {
    const paired: InvestigationParams = { against: selection.compare, pipeline_id: selection.pipeline, limit: PAGE_SIZE, cursor }
    return selection.query
      ? fetchInvestigationComparisonQuery(db, run, selection.query, paired)
      : fetchInvestigationComparison(db, run, paired)
  }
  const params: InvestigationParams = {
    pipeline_id: selection.pipeline,
    stage_id: DRILL_DOWN.has(mode) ? null : selection.stage,
    outcome: selection.outcome,
    limit: PAGE_SIZE,
    cursor,
  }
  switch (mode) {
    case 'documents':
      return fetchInvestigationDocuments(db, run, params)
    case 'document-queries':
      return fetchInvestigationDocument(db, run, selection.entity as string, params)
    case 'query-candidates':
      return fetchInvestigationQuery(db, run, selection.query as string, { ...params, trace_id: selection.trace })
    default:
      return fetchInvestigationQueries(db, run, params)
  }
}

type Phase =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'failed'; error: InvestigationError }
  | { kind: 'ready'; envelope: Envelope; rows: Row[]; partialRows: number; loadingMore: boolean; moreError: string | null }

type Scope =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'ready'; graphs: PipelineGraph[]; stages: StageSummary[] | null; pipelineId: string | null; graphError: string | null }

function partialCount(envelope: Envelope): number {
  return envelope.capabilities?.capture?.partial_rows ?? 0
}

/** The stored aggregates a list envelope carries; a query envelope's trace spans do not qualify. */
function aggregateStages(envelope: Envelope): StageSummary[] | null {
  const stages = envelope.stages
  if (!stages || stages.length === 0) return stages ? [] : null
  return isStageSummary(stages[0]) ? (stages as StageSummary[]) : null
}

function traceStagesOf(envelope: Envelope): InvestigationStage[] | null {
  const stages = envelope.stages
  if (!stages || stages.length === 0) return null
  return isStageSummary(stages[0]) ? null : (stages as InvestigationStage[])
}

type BuildState = { kind: 'idle' } | { kind: 'running' } | { kind: 'refused'; message: string } | { kind: 'failed'; message: string }

/** Starts `request` for `cursor` unless a request for that cursor is already in flight: two fast
 * "Load more" clicks share one render's closure, so the disabled button alone cannot stop the
 * second. Returns null when skipped; the slot is released when the request settles. */
export function singleFlight<T>(inFlight: { current: string | null }, cursor: string, request: () => Promise<T>): Promise<T> | null {
  if (inFlight.current === cursor) return null
  inFlight.current = cursor
  return request().finally(() => {
    if (inFlight.current === cursor) inFlight.current = null
  })
}

/** Applies an index build's outcome only while the scope it started for (db/run/pipeline) is still
 * selected; a late result after a run switch is dropped. */
export function settleBuild(
  build: Promise<{ status: string; error?: string | null }>,
  isCurrent: () => boolean,
  run: string,
  setBuild: (state: BuildState) => void,
  reload: () => void,
): Promise<void> {
  return build
    .then((result) => {
      if (!isCurrent()) return
      if (result.status === 'failed') setBuild({ kind: 'failed', message: result.error ?? 'Indexing failed' })
      else {
        setBuild({ kind: 'idle' })
        reload()
      }
    })
    .catch((raw: unknown) => {
      if (!isCurrent()) return
      const error = describeInvestigationError(raw)
      if (error.status === 409) {
        setBuild({
          kind: 'refused',
          message: `This database is opened read-only, so the index cannot be built from the dashboard. Run \`retobs storage index ${run}\` where the database is writable.`,
        })
      } else setBuild({ kind: 'failed', message: error.detail ?? error.message })
    })
}

function Notice({ tone, title, children }: { tone: 'warning' | 'neutral' | 'negative'; title: string; children?: React.ReactNode }) {
  const color = tone === 'warning' ? 'text-status-warning' : tone === 'negative' ? 'text-status-negative' : 'text-status-neutral'
  return (
    <div role="status" className="app-inset px-3 py-2 text-xs">
      <span className={`font-semibold ${color}`}>{title}</span>
      {children && <span className="ml-2 text-ink-muted">{children}</span>}
    </div>
  )
}

function Panel({ title, children, id }: { title: string; children: React.ReactNode; id?: string }) {
  return (
    <section aria-labelledby={id} className="app-card p-6 text-sm">
      <h2 id={id} className="font-semibold text-ink">
        {title}
      </h2>
      <div className="mt-2 leading-6 text-ink-muted">{children}</div>
    </section>
  )
}

const linkClass = 'text-accent underline underline-offset-2'
const buttonClass =
  'rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600'

interface Props {
  /** Reports the pipelines the service names for the current run, so the scope bar can offer them. */
  onPipelines?: (hint: PipelineHint | null) => void
}

export default function InvestigateWorkspace({ onPipelines }: Props) {
  const { selection, databases, updateSelection } = useDashboardContext()
  const { db, run, view } = selection
  const mode = modeFor(selection)
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  const [scope, setScope] = useState<Scope>({ kind: 'idle' })
  const [build, setBuild] = useState<BuildState>({ kind: 'idle' })
  const [reloadTick, setReloadTick] = useState(0)
  const [sort, setSort] = useState<SortState | null>(null)
  const [collapsed, setCollapsed] = useState(true)
  const sequence = useRef(0)
  const scopeSequence = useRef(0)
  const loadingCursor = useRef<string | null>(null)
  // The scope an index build belongs to; excludes reloadTick so a Retry mid-build keeps its result.
  const buildScope = JSON.stringify([db, run, selection.pipeline])
  const buildScopeRef = useRef(buildScope)
  buildScopeRef.current = buildScope
  const onPipelinesRef = useRef(onPipelines)
  onPipelinesRef.current = onPipelines

  // Only the fields that change the request take part in the key.
  const requestKey = JSON.stringify([
    db,
    run,
    selection.pipeline,
    DRILL_DOWN.has(mode) ? null : selection.stage,
    selection.outcome,
    view,
    view === 'queries' ? selection.query : null,
    view === 'queries' && selection.query ? selection.trace : null,
    view === 'documents' ? selection.entity : null,
    view === 'queries' ? selection.compare : null,
    reloadTick,
  ])

  useEffect(() => {
    if (!db || !run) {
      setPhase({ kind: 'idle' })
      return
    }
    const mySequence = ++sequence.current
    setPhase({ kind: 'loading' })
    setBuild({ kind: 'idle' })
    requestFor(db, run, selection, null)
      .then((envelope) => {
        if (mySequence !== sequence.current) return
        setPhase({ kind: 'ready', envelope, rows: envelope.rows as Row[], partialRows: partialCount(envelope), loadingMore: false, moreError: null })
        onPipelinesRef.current?.({ runId: run, ids: envelope.scope.pipeline_id ? [envelope.scope.pipeline_id] : [] })
      })
      .catch((raw: unknown) => {
        if (mySequence !== sequence.current) return
        const error = describeInvestigationError(raw)
        setPhase({ kind: 'failed', error })
        if (error.code === 'pipeline_required') onPipelinesRef.current?.({ runId: run, ids: pipelineIdsFromDetail(error.detail) })
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey])

  // Scope stream: the run-union topology and the stored per-operator aggregates, once per scope.
  const scopeKey = JSON.stringify([db, run, selection.pipeline, reloadTick])
  useEffect(() => {
    if (!db || !run) {
      setScope({ kind: 'idle' })
      return
    }
    const mySequence = ++scopeSequence.current
    setScope({ kind: 'loading' })
    const graphs = fetchPipelineGraphs(db, run).then(
      (list) => ({ list, error: null as string | null }),
      (raw: unknown) => ({ list: [] as PipelineGraph[], error: raw instanceof Error ? raw.message : String(raw) }),
    )
    const aggregates = fetchInvestigationQueries(db, run, { pipeline_id: selection.pipeline, limit: 1 }).then(
      (envelope) => ({ stages: aggregateStages(envelope), pipelineId: envelope.scope.pipeline_id as string | null }),
      () => ({ stages: null, pipelineId: null }),
    )
    Promise.all([graphs, aggregates]).then(([graph, aggregate]) => {
      if (mySequence !== scopeSequence.current) return
      setScope({ kind: 'ready', graphs: graph.list, stages: aggregate.stages, pipelineId: aggregate.pipelineId, graphError: graph.error })
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeKey])

  const reload = () => setReloadTick((tick) => tick + 1)

  const loadMore = () => {
    if (phase.kind !== 'ready' || !phase.envelope.next_cursor || !db || !run) return
    const mySequence = sequence.current
    const cursor = phase.envelope.next_cursor
    // Keyed by sequence too: a new scope may hand out the same cursor while the old request is pending.
    const request = singleFlight(loadingCursor, `${mySequence}:${cursor}`, () => requestFor(db, run, selection, cursor))
    if (!request) return
    setPhase({ ...phase, loadingMore: true, moreError: null })
    request
      .then((envelope) => {
        if (mySequence !== sequence.current) return
        setPhase((current) =>
          current.kind === 'ready'
            ? {
                kind: 'ready',
                envelope,
                rows: [...current.rows, ...(envelope.rows as Row[])],
                partialRows: current.partialRows + partialCount(envelope),
                loadingMore: false,
                moreError: null,
              }
            : current,
        )
      })
      .catch((raw: unknown) => {
        if (mySequence !== sequence.current) return
        setPhase((current) =>
          current.kind === 'ready' ? { ...current, loadingMore: false, moreError: describeInvestigationError(raw).message } : current,
        )
      })
  }

  const buildIndex = () => {
    if (!db || !run || phase.kind !== 'ready') return
    const envelopeScope = phase.envelope.scope
    const started = buildScope
    setBuild({ kind: 'running' })
    void settleBuild(
      buildInvestigationProjection(db, run, {
        pipeline_id: selection.pipeline ?? envelopeScope.pipeline_id,
        unit: envelopeScope.unit,
        k: envelopeScope.k ?? undefined,
      }),
      () => buildScopeRef.current === started,
      run,
      setBuild,
      reload,
    )
  }

  const select = (patch: Partial<DashboardSelection>) => updateSelection(patch)
  const resetSelection = () => select({ query: null, trace: null, entity: null, stage: null, outcome: null })
  const clearDrillDown = () =>
    select(view === 'documents' ? { entity: null, query: null, trace: null } : { query: null, trace: null, entity: null })

  const dbRunCount = databases.find((d) => d.db_id === db)?.run_count
  const title = run ? `Run ${run}` : 'Investigate'

  // Graph inputs derived from the two streams.
  const envelope = phase.kind === 'ready' ? phase.envelope : null
  const effectivePipeline = selection.pipeline ?? envelope?.scope.pipeline_id ?? (scope.kind === 'ready' ? scope.pipelineId : null)
  const graphs = scope.kind === 'ready' ? scope.graphs : []
  const graph = graphs.find((g) => g.pipeline_id === effectivePipeline) ?? (graphs.length === 1 ? graphs[0] : null)
  const traceStages = envelope && mode === 'query-candidates' ? traceStagesOf(envelope) : null
  const aggregate = scope.kind === 'ready' ? scope.stages : null
  const journeyRows = phase.kind === 'ready' ? phase.rows.filter(isJourney) : []
  const selectedRow =
    mode === 'query-candidates'
      ? journeyRows.find((row) => entityKey(row) === selection.entity && (!selection.trace || row.trace_id === selection.trace)) ?? null
      : mode === 'document-queries'
        ? journeyRows.find((row) => row.query_id === selection.query && (!selection.trace || row.trace_id === selection.trace)) ?? null
        : null
  const highlight = selectedRow ? pathHighlight(selectedRow, graph) : null
  const opTypes = new Map(graph?.nodes.map((node) => [node.node_id, node.op_type]) ?? [])
  const isSource = graph ? (opId: string) => opTypes.get(opId) === 'SOURCE' : undefined

  let body: React.ReactNode
  if (!db || !run) {
    body = (
      <Panel id="investigate-prompt" title="Choose a run">
        <p>Pick a database and a run in the scope bar to load its queries and documents.</p>
        {dbRunCount === 0 && (
          <p className="mt-2">
            This database has no runs yet.{' '}
            <a href={buildHash('connect', { db })} className={linkClass}>
              Connect a pipeline
            </a>{' '}
            to record one.
          </p>
        )}
      </Panel>
    )
  } else if (phase.kind === 'loading' || phase.kind === 'idle') {
    body = (
      <div role="status" className="app-card p-6 text-sm text-ink-muted">
        Loading {view}…
      </div>
    )
  } else if (phase.kind === 'failed') {
    const { error } = phase
    if (error.code === 'pipeline_required') {
      const ids = pipelineIdsFromDetail(error.detail)
      body = (
        <Panel id="investigate-pipeline" title="Choose a pipeline">
          <p>This run recorded more than one pipeline. Pick one to investigate:</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {ids.map((id) => (
              <li key={id}>
                <a href={buildHash('investigate', { ...selection, pipeline: id })} className={`${linkClass} font-mono`}>
                  {id}
                </a>
              </li>
            ))}
          </ul>
        </Panel>
      )
    } else if (error.status === 404) {
      body = (
        <Panel id="investigate-missing" title="Nothing recorded for this scope">
          <p>{error.detail ?? error.message}</p>
          <p className="mt-2">
            {DRILL_DOWN.has(mode) ? (
              <button type="button" onClick={clearDrillDown} className={linkClass}>
                Back to all {view}
              </button>
            ) : (
              <button type="button" onClick={() => select({ run: null })} className={linkClass}>
                Choose another run
              </button>
            )}
          </p>
        </Panel>
      )
    } else {
      body = (
        <div role="alert" className="app-card p-6 text-sm">
          <p className="font-semibold text-status-negative">The request failed</p>
          <p className="mt-1 break-words text-ink-muted">{error.detail ?? error.message}</p>
          <button type="button" onClick={reload} className={`${buttonClass} mt-3`}>
            Retry
          </button>
        </div>
      )
    }
  } else {
    const { rows, partialRows } = phase
    const ready = phase.envelope
    const comparison = isComparison(ready) ? ready : null
    const findings = ready.findings ?? []
    const has = (code: string) => findings.some((f) => f.code === code)
    const indexUnavailable = has('projection_unavailable')
    const indexStale = has('projection_stale')
    const multipleTraces = has('multiple_traces') && mode === 'query-candidates' && !selection.trace
    const traceIds = [...new Set(journeyRows.map((row) => row.trace_id))]
    const tableRows: Row[] = DRILL_DOWN.has(mode) ? stageFilter(journeyRows, selection.stage) : rows
    const buildButton = (label: string) => (
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button type="button" onClick={buildIndex} disabled={build.kind === 'running' || build.kind === 'refused'} className={buttonClass}>
          {build.kind === 'running' ? 'Indexing…' : label}
        </button>
        {build.kind === 'refused' && <span className="text-xs text-ink-muted">{build.message}</span>}
        {build.kind === 'failed' && (
          <span role="alert" className="text-xs text-status-negative">
            {build.message}
          </span>
        )}
      </div>
    )

    body = (
      <div className="space-y-3">
        {indexUnavailable && (
          <Panel id="investigate-index" title="Index this run">
            <p>
              Journey rows for this run have not been indexed yet{rows.length === 0 ? `, so the ${view} list is empty` : ''}.
              Indexing reads the recorded traces once and stores the per-query outcomes.
            </p>
            {buildButton('Index this run')}
          </Panel>
        )}
        {indexStale && (
          <div role="status" className="app-inset px-3 py-2 text-xs">
            <span className="font-semibold text-status-warning">Stale index — rebuild</span>
            <span className="ml-2 text-ink-muted">
              The stored rows predate the current judgments or derivation; counts may not match the traces.
            </span>
            {buildButton('Rebuild index')}
          </div>
        )}
        {partialRows > 0 && (
          <Notice tone="warning" title={`${partialRows} of ${rows.length} rows are evidence-limited`}>
            An operator boundary was not fully captured for them, so no removal reason is asserted.
          </Notice>
        )}
        {comparison && (
          <div role="status" className="app-inset px-3 py-2 text-xs">
            Comparing candidate <code className="font-mono">{run}</code> against baseline <code className="font-mono">{selection.compare}</code>
            {' · '}
            <a href={auditLink({ db, baseline: selection.compare, candidate: run })} className={linkClass}>
              Back to audit
            </a>
          </div>
        )}

        <section aria-labelledby="investigate-graph-title" className="app-card space-y-2 p-4">
          <div className="flex flex-wrap items-baseline gap-2">
            <h2 id="investigate-graph-title" className="text-sm font-semibold text-ink">
              Pipeline {effectivePipeline ? <span className="font-mono">{effectivePipeline}</span> : null}
            </h2>
            {graph && (
              <span className="text-xs text-ink-muted">
                {graph.trace_count} {graph.trace_count === 1 ? 'trace' : 'traces'} · {graph.complete_trace_count} complete
              </span>
            )}
            {scope.kind === 'ready' && scope.graphError && <span className="text-xs text-ink-faint">topology unavailable: {scope.graphError}</span>}
          </div>
          {scope.kind === 'loading' ? (
            <p role="status" className="text-sm text-ink-muted">
              Loading pipeline…
            </p>
          ) : (
            <InvestigationGraph
              graph={graph}
              stages={traceStages ?? aggregate}
              mode={traceStages ? 'query' : 'aggregate'}
              selectedStageId={selection.stage}
              highlight={highlight}
              collapsed={collapsed}
              onToggleCollapsed={() => setCollapsed((value) => !value)}
              onSelectStage={(opId) => select({ stage: opId })}
            />
          )}
          {selection.stage && (
            <OperatorInspector
              opId={selection.stage}
              stage={traceStages?.find((stage) => stage.op_id === selection.stage) ?? null}
              aggregate={aggregate?.find((stage) => stage.op_id === selection.stage) ?? null}
            />
          )}
        </section>

        {DRILL_DOWN.has(mode) && (
          <p className="text-sm text-ink-muted">
            {mode === 'query-candidates' ? 'Query' : 'Document'}{' '}
            <code className="font-mono text-ink">{mode === 'query-candidates' ? selection.query : selection.entity}</code>
            {mode === 'query-candidates' && selection.trace && (
              <>
                {' '}
                · trace <code className="font-mono text-ink">{selection.trace}</code>
              </>
            )}
            {' · '}
            <button type="button" onClick={clearDrillDown} className={linkClass}>
              All {view}
            </button>
          </p>
        )}
        {multipleTraces && (
          <Notice tone="neutral" title={`This query has ${traceIds.length} traces`}>
            Pick one to see its execution:
            {traceIds.map((traceId) => (
              <button key={traceId} type="button" onClick={() => select({ trace: traceId })} className={`${linkClass} ml-2 font-mono`}>
                {traceId}
              </button>
            ))}
          </Notice>
        )}
        {comparison && <CandidateLineageDiff envelope={comparison} onSelectEntity={(entity, query) => select({ query, entity })} />}
        {!comparison && rows.length === 0 && !indexUnavailable && (
          <Panel id="investigate-empty" title={`No ${view} for this scope`}>
            <p>
              {selection.stage || selection.outcome
                ? 'No rows match the current stage/outcome filters.'
                : 'The index holds no rows for this run and pipeline.'}
            </p>
            {(selection.stage || selection.outcome) && (
              <button type="button" onClick={resetSelection} className={`${linkClass} mt-2`}>
                Reset selection
              </button>
            )}
          </Panel>
        )}
        {!comparison && rows.length > 0 && (
          <InvestigationTable
            shape={mode}
            rows={tableRows as JourneyRow[] | QuerySummaryRow[] | InvestigationDocumentRow[]}
            selection={selection}
            total={ready.total}
            sort={sort}
            isSource={isSource}
            onSort={setSort}
            onSelect={select}
            onReset={resetSelection}
          />
        )}
        {ready.next_cursor && (
          <div className="flex items-center gap-3">
            <button type="button" onClick={loadMore} disabled={phase.loadingMore} className={buttonClass}>
              {phase.loadingMore ? 'Loading…' : 'Load more'}
            </button>
            <span className="text-xs text-ink-muted">
              {rows.length}
              {ready.total != null ? ` of ${ready.total}` : ''} rows
            </span>
            {phase.moreError && (
              <span role="alert" className="text-xs text-status-negative">
                {phase.moreError}
              </span>
            )}
          </div>
        )}
        {!comparison && selectedRow && <InvestigationDetail row={selectedRow} stages={traceStages} />}
        <EvidenceDetails envelope={ready} findings={findings} derivation={journeyRows[0]?.derivation_version ?? null} />
      </div>
    )
  }

  return (
    <main className="flex-1 overflow-auto p-4 sm:p-6" aria-labelledby="investigate-title">
      <div className="mx-auto max-w-6xl">
        <header className="mb-4">
          <p className="eyebrow">Investigate</p>
          <h1 id="investigate-title" className="mt-1 text-xl font-semibold text-ink">
            {title}
          </h1>
        </header>
        <section id="investigate-view" role="tabpanel" aria-labelledby={`view-tab-${view}`}>
          {body}
        </section>
      </div>
    </main>
  )
}

function EvidenceDetails({ envelope, findings, derivation }: { envelope: Envelope; findings: InvestigationFinding[]; derivation: string | null }) {
  const { scope, capabilities, coverage } = envelope
  const entries: Array<[string, string | number | null | undefined]> = [
    ['Run', scope.run_id],
    ['Pipeline', scope.pipeline_id],
    ['Boundary', scope.boundary],
    ['Unit', scope.unit],
    ['k', scope.k],
    ['Relevance threshold', scope.relevance_threshold],
    ['Evaluation digest', scope.evaluation_digest],
    ['Judgment digest', scope.judgment_digest],
    ['Index', capabilities?.projection],
    ['Judgments', capabilities?.judgments],
    ['Capture', capabilities ? `${capabilities.capture.complete_rows} complete · ${capabilities.capture.partial_rows} partial` : null],
    ['Queries attempted', coverage?.queries_attempted],
    ['Queries with traces', coverage?.queries_with_traces],
    ['Queries indexed', coverage?.queries_projected],
    ['Pairs', coverage?.pairs],
    ['Events', coverage?.events],
    ['Derivation', derivation],
  ]
  return (
    <details className="app-inset p-3 text-xs">
      <summary className="cursor-pointer font-medium text-ink">Evidence details</summary>
      <dl className="mt-2 grid gap-x-6 gap-y-1 sm:grid-cols-2">
        {entries
          .filter(([, value]) => value !== null && value !== undefined && value !== '')
          .map(([label, value]) => (
            <div key={label} className="flex justify-between gap-3">
              <dt className="text-ink-faint">{label}</dt>
              <dd className="truncate font-mono text-ink" title={String(value)}>
                {String(value)}
              </dd>
            </div>
          ))}
      </dl>
      {findings.length > 0 && (
        <ul className="mt-3 space-y-1">
          {findings.map((finding, index) => (
            <li key={`${finding.code}-${index}`}>
              <span className="font-mono text-ink">{finding.code}</span>
              <span className="ml-2 text-ink-muted">{finding.detail}</span>
              {finding.action && <span className="ml-2 text-ink-faint">— {finding.action}</span>}
            </li>
          ))}
        </ul>
      )}
    </details>
  )
}
