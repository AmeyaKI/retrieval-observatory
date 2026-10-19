import { useCallback, useMemo, useRef, useState } from 'react'
import { InvestigationFlow, InvestigationStage, JourneyRow, PipelineGraph, StageSummary } from '../api'
import { collapseInvocations, collapsedNodeId, repeatedInvocationCount } from '../utils/dagLayout'
import { FlowEdge, FlowNode, FlowResult, layoutFlow, Orientation } from '../utils/flowLayout'
import {
  CardWords,
  firedCount,
  flowStepOf,
  foldedAggregate,
  foldedStage,
  foldFlow,
  pathCard,
  plural,
  questionCard,
  ResultWords,
  resultWords,
  runCard,
  stepKind,
  stepName,
  Tone,
} from '../utils/flowWords'
import { pathHighlight } from '../utils/queryDebugger'

// The pipeline diagram for Investigate. Run mode: where the run's correct documents go (line
// thickness = correct documents passing). Question mode: one question's candidates in and out.
// Path mode: one document's rank at each step. Every card is a button that selects the step.

export type GraphMode = 'run' | 'question' | 'path'

export interface InvestigationGraphProps {
  graph: PipelineGraph | null
  flow: InvestigationFlow | null
  stages: StageSummary[] | null
  traceStages: InvestigationStage[] | null
  focus: JourneyRow | null
  k: number | null
  selectedStageId: string | null
  collapsed: boolean
  onToggleCollapsed: () => void
  onSelectStage: (opId: string | null) => void
  /** Container width before the first measurement (and in server-side rendering). */
  width?: number
}

export function graphMode(focus: JourneyRow | null, traceStages: InvestigationStage[] | null): GraphMode {
  return focus ? 'path' : traceStages ? 'question' : 'run'
}

/** Pill colours per tone, shared by step cards, journey cards and outcome pills. */
export const BADGE: Record<Tone, string> = {
  negative: 'bg-status-negative/10 text-status-negative',
  positive: 'bg-status-positive/10 text-status-positive',
  // accent-muted is under 4.5:1 behind accent text in dark mode; a 15 % accent tint is not.
  accent: 'bg-accent-muted text-accent dark:bg-accent/15',
  warning: 'bg-status-warning/10 text-status-warning',
  neutral: 'border border-hairline bg-surface-muted text-ink-muted',
}

const NOTE: Record<Tone, string> = {
  negative: 'text-status-negative',
  positive: 'text-status-positive',
  accent: 'text-accent',
  warning: 'text-status-warning',
  neutral: 'text-ink-muted',
}

const FOCUS_RING = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent'
const FAINT = 'rgb(var(--ink-faint) / .35)'

export function StepCard({
  node,
  words,
  selected,
  onPath,
  onSelect,
}: {
  node: FlowNode
  words: CardWords
  selected: boolean
  onPath: boolean
  onSelect: (id: string) => void
}) {
  const { name, id } = stepName(node)
  const kind = stepKind(node.op_type)
  const lossy = words.badge?.tone === 'negative'
  const border = selected
    ? 'border-2 border-accent'
    : lossy
      ? 'border-2 border-status-negative/60'
      : onPath
        ? 'border-2 border-accent'
        : node.is_final_output
          ? 'border border-status-positive/50'
          : words.ghost
            ? 'border border-ink-faint/50'
            : 'border border-hairline'
  const title = [node.label, node.node_id, kind, words.metric, words.badge?.text, words.fullNote ?? words.note].filter(Boolean).join('\n')
  return (
    <foreignObject x={node.x} y={node.y} width={node.w} height={node.h} style={{ overflow: 'visible' }}>
      <button
        type="button"
        onClick={() => onSelect(node.node_id)}
        aria-pressed={selected}
        title={title}
        className={`box-border flex h-full w-full flex-col overflow-hidden rounded-xl p-2.5 text-left ${border} ${words.ghost ? 'border-dashed bg-surface-muted' : 'bg-surface'} ${FOCUS_RING}`}
        style={{ width: node.w, height: node.h }}
      >
        {/* Fixed rows (CARD_H): kind, name, id, one metric line, two lines of badge and note. */}
        <span className="flex h-4 min-w-0 shrink-0 items-center justify-between gap-2 text-xs leading-4 text-ink-faint">
          <span className="truncate">{kind}</span>
          {selected && <span className="shrink-0 text-accent">Selected</span>}
        </span>
        <span className={`h-5 shrink-0 truncate text-sm font-semibold leading-5 ${words.ghost ? 'text-ink-faint' : 'text-ink'}`}>{name}</span>
        {id && <span className="h-4 shrink-0 truncate font-mono text-xs leading-4 text-ink-faint">{id}</span>}
        {words.metric && <span className={`h-4 shrink-0 truncate text-[13px] leading-4 ${words.ghost ? 'text-ink-faint' : 'text-ink-muted'}`}>{words.metric}</span>}
        {(words.badge || words.note) && (
          <span className="mt-0.5 line-clamp-2 text-xs leading-4">
            {words.badge && <span className={`box-decoration-clone rounded-full px-1.5 py-px font-semibold ${BADGE[words.badge.tone]}`}>{words.badge.text}</span>}
            {words.badge && words.note && ' '}
            {words.note && <span className={NOTE[words.noteTone ?? 'neutral']}>{words.note}</span>}
          </span>
        )}
      </button>
    </foreignObject>
  )
}

/** The result after the only final step. Not a control and hidden from assistive technology: the
 * same facts are in the final step's table row and the page text. */
function ResultCard({ box, words }: { box: FlowResult; words: ResultWords }) {
  const positive = words.figure != null || words.noteTone === 'positive'
  return (
    <foreignObject x={box.x} y={box.y} width={box.w} height={box.h} aria-hidden="true">
      <div
        className={`box-border flex h-full w-full flex-col overflow-hidden rounded-xl border bg-surface p-2.5 ${positive ? 'border-status-positive/50' : 'border-hairline'}`}
        style={{ width: box.w, height: box.h }}
      >
        <span className="h-4 shrink-0 text-xs leading-4 text-ink-faint">Final result</span>
        <span className="h-5 shrink-0 truncate text-sm font-semibold leading-5 text-ink">{words.name}</span>
        {words.figure && <span className="mt-1 shrink-0 truncate text-lg font-semibold leading-6 tabular-nums text-status-positive">{words.figure}</span>}
        {words.note && <span className={`mt-0.5 line-clamp-2 text-xs leading-4 ${NOTE[words.noteTone ?? 'neutral']}`}>{words.note}</span>}
      </div>
    </foreignObject>
  )
}

/** The accessible equivalent of the diagram: one row per step with its correct-document counts. */
export function FlowTable({ graph, flow }: { graph: PipelineGraph; flow: InvestigationFlow | null }) {
  const counted = flow && flow.totals.relevant > 0 ? flow : null
  const cell = 'px-3 py-2'
  return (
    <div className={`overflow-x-auto rounded-lg border border-hairline ${FOCUS_RING}`} tabIndex={0} role="region" aria-label={`Pipeline steps for ${graph.pipeline_id}`}>
      <table className="w-full text-left text-xs">
        <caption className="sr-only">Pipeline steps for {graph.pipeline_id}</caption>
        <thead className="bg-surface-muted text-ink-muted">
          <tr>
            {['Step', 'Kind', 'Ran for', 'Correct in', 'Correct out', 'Lost here'].map((heading) => (
              <th key={heading} scope="col" className={`${cell} font-medium`}>
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="tabular-nums text-ink-muted">
          {graph.nodes.map((node) => {
            const { name, id } = stepName(node)
            const step = flowStepOf(counted, node.node_id)
            return (
              <tr key={node.node_id} className="border-t border-hairline">
                <th scope="row" className={`${cell} font-medium text-ink`}>
                  {name}
                  {id && <span className="ml-1.5 font-mono font-normal text-ink-faint">{id}</span>}
                </th>
                <td className={cell}>{stepKind(node.op_type)}</td>
                <td className={cell}>
                  {firedCount(node, graph.trace_count)} of {plural(graph.trace_count, 'question')}
                </td>
                <td className={cell}>{step && node.op_type !== 'SOURCE' ? step.input : '—'}</td>
                <td className={cell}>{step ? step.output : '—'}</td>
                <td className={cell}>{step ? step.lost_total : '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** Width of the wrapper, measured once mounted; `fallback` until then (and in tests). */
function useContainerWidth(fallback: number): [(element: HTMLDivElement | null) => void, number] {
  const [width, setWidth] = useState(fallback)
  const observer = useRef<ResizeObserver | null>(null)
  const measure = useCallback((element: HTMLDivElement | null) => {
    observer.current?.disconnect()
    observer.current = null
    if (!element || typeof ResizeObserver === 'undefined') return
    observer.current = new ResizeObserver((entries) => {
      const next = Math.floor(entries[0]?.contentRect.width ?? 0)
      if (next > 0) setWidth(next)
    })
    observer.current.observe(element)
  }, [])
  return [measure, width]
}

type Box = { x: number; y: number; w: number; h: number }

/** An edge label is drawn only where it fits the gap between the two cards without touching them. */
function labelFits(orientation: Orientation, s: Box, t: Box, text: string): boolean {
  if (orientation === 'horizontal') return t.x - (s.x + s.w) >= text.length * 7 + 8
  return t.y - (s.y + s.h) >= 18
}

const toggleClass = `rounded border border-hairline bg-surface px-2 py-0.5 text-xs text-ink hover:bg-surface-muted ${FOCUS_RING}`

export default function InvestigationGraph({
  graph,
  flow,
  stages,
  traceStages,
  focus,
  k,
  selectedStageId,
  collapsed,
  onToggleCollapsed,
  onSelectStage,
  width: initialWidth,
}: InvestigationGraphProps) {
  const [measure, width] = useContainerWidth(initialWidth ?? 1200)
  const shown = useMemo(() => (graph ? (collapsed ? collapseInvocations(graph) : graph) : null), [graph, collapsed])
  const layout = useMemo(() => (shown ? layoutFlow(shown, { width }) : null), [shown, width])
  const folded = useMemo(() => foldFlow(flow, collapsed), [flow, collapsed])

  if (!graph || !shown || !layout) {
    return (
      <p role="status" className="text-sm text-ink-muted">
        No pipeline steps were recorded for this run, so there is no diagram; the lists below still show everything indexed.
      </p>
    )
  }

  const fold = (opId: string) => (collapsed ? collapsedNodeId(opId) : opId)
  const mode = graphMode(focus, traceStages)
  const counted = folded && folded.totals.relevant > 0 ? folded : null
  const cutoff = k ?? flow?.k ?? null
  const repeats = repeatedInvocationCount(graph)
  const selectedId = selectedStageId ? fold(selectedStageId) : null
  const highlight = focus ? pathHighlight(focus, graph) : null
  const pathNodes = new Set(highlight?.nodeIds.map(fold) ?? [])
  const pathEdges = new Set(highlight?.edges.map(([source, target]) => `${fold(source)}→${fold(target)}`) ?? [])
  const at = new Map<string, Box>(layout.nodes.map((node) => [node.node_id, node]))
  const nodes = [...layout.nodes].sort((a, b) => a.col - b.col || a.row - b.row)
  // With a result card the final step carries only its own facts; the card says what was delivered.
  const separate = layout.result !== null
  const finalRank = focus && focus.final_membership === 'included' ? focus.final_rank : null

  const wordsFor = (node: FlowNode): CardWords => {
    if (focus) {
      const events = focus.events.filter((event) => fold(event.op_id) === node.node_id)
      const stage = traceStages ? foldedStage(traceStages, node.node_id, collapsed) : null
      const boundary = focus.loss_boundary != null && fold(focus.loss_boundary) === node.node_id
      return pathCard(node, events, stage, cutoff, node.is_final_output && !separate, finalRank, boundary)
    }
    if (traceStages) return questionCard(node, foldedStage(traceStages, node.node_id, collapsed))
    return runCard(node, flowStepOf(folded, node.node_id), folded, shown, foldedAggregate(stages, node.node_id, collapsed), separate)
  }

  type Styled = { stroke: string; strokeWidth: number; strokeDasharray?: string; label: string | null; onPath: boolean }
  const faint: Styled = { stroke: FAINT, strokeWidth: 1.5, label: null, onPath: false }
  const accent: Styled = { stroke: 'rgb(var(--accent))', strokeWidth: 4, label: null, onPath: true }
  const counts = (count: number, dashed: boolean): Styled =>
    dashed || count === 0 ? { ...faint, strokeDasharray: '5 4' } : { ...faint, strokeWidth: 2 + (16 * count) / counted!.totals.relevant, label: `${count} correct` }
  const edgeStyle = (edge: FlowEdge): Styled => {
    const key = `${edge.source}→${edge.target}`
    if (mode === 'path') return pathEdges.has(key) ? accent : faint
    if (mode === 'run' && counted) return counts(counted.copresence[key] ?? 0, edge.conditional && edge.kind === 'fan_in')
    return faint
  }
  const resultStyle = (): Styled => {
    if (mode === 'path') return finalRank != null ? accent : faint
    if (mode === 'run' && counted) return counts(counted.totals.delivered, false)
    return faint
  }
  const edges = layout.edges.map((edge) => ({ edge, key: `${edge.source}→${edge.target}`, from: at.get(edge.source)!, to: at.get(edge.target)!, ...edgeStyle(edge) }))
  if (layout.result) {
    const { edge } = layout.result
    edges.push({ edge, key: `${edge.source}→result`, from: at.get(edge.source)!, to: layout.result, ...resultStyle() })
  }

  const summary =
    `Pipeline ${shown.pipeline_id}: ${shown.nodes.length} steps, ${shown.edges.length} edges; ` +
    (mode === 'path' ? `showing the path of ${focus!.entity_id}` : mode === 'question' ? 'showing one question' : 'showing correct documents over the whole run') +
    (selectedId ? `; ${selectedId} selected` : '')
  const neverFound = mode === 'run' ? counted?.totals.never_found ?? 0 : 0

  return (
    <div className="space-y-2">
      <div ref={measure} className={layout.overflowX ? 'overflow-x-auto' : undefined}>
        <svg width={layout.width} height={layout.height} viewBox={`0 0 ${layout.width} ${layout.height}`} className="mx-auto block" role="group" aria-label={summary}>
          {edges.map(({ edge, key, from, to, label, onPath, ...style }) => (
            <path
              key={key}
              d={edge.path}
              fill="none"
              strokeLinecap="round"
              style={style}
              data-on-path={onPath ? 'true' : undefined}
            />
          ))}
          {nodes.map((node) => (
            <StepCard
              key={node.node_id}
              node={node}
              words={wordsFor(node)}
              selected={selectedId === node.node_id}
              onPath={mode === 'path' && pathNodes.has(node.node_id)}
              onSelect={(id) => onSelectStage(selectedId === id ? null : id)}
            />
          ))}
          {layout.result && <ResultCard box={layout.result} words={resultWords(mode, counted, cutoff, finalRank)} />}
          {edges.map(
            ({ edge, key, from, to, label }) =>
              label &&
              labelFits(layout.orientation, from, to, label) && (
                <text
                  key={`label-${key}`}
                  x={edge.mid.x}
                  y={edge.mid.y}
                  textAnchor="middle"
                  dominantBaseline="central"
                  className="tabular-nums"
                  style={{ fontSize: 12, fontWeight: 500, fill: 'rgb(var(--ink-muted))', stroke: 'rgb(var(--surface))', strokeWidth: 3, paintOrder: 'stroke' }}
                >
                  {label}
                </text>
              ),
          )}
        </svg>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted">
        {mode === 'path' ? (
          <span>Rank of {focus!.entity_id} at each step</span>
        ) : mode === 'question' ? (
          <span>Candidates in and out of each step for this question</span>
        ) : (
          counted && <span>Line thickness = correct documents passing · dashed = ran for only some questions</span>
        )}
        {neverFound > 0 && <span className="rounded-md border border-dashed border-status-negative/50 px-2 py-0.5 text-status-negative">{neverFound} never found by any search</span>}
        {repeats > 0 && (
          <button type="button" onClick={onToggleCollapsed} className={toggleClass} aria-pressed={!collapsed}>
            {collapsed ? 'Expand' : 'Collapse'} repeated invocations ({repeats})
          </button>
        )}
        <details className="open:basis-full">
          <summary className="cursor-pointer font-medium text-accent">Show the steps as a table</summary>
          <div className="mt-2">
            <FlowTable graph={shown} flow={folded} />
          </div>
        </details>
      </div>
    </div>
  )
}
