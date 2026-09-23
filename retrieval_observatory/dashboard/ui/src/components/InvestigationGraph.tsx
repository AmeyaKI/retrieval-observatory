import { useMemo, useState } from 'react'
import { InvestigationStage, isStageSummary, PipelineGraph, StageSummary } from '../api'
import { collapseInvocations, collapsedNodeId, LaidOutNode, layoutPipelineGraph, repeatedInvocationCount } from '../utils/dagLayout'
import { OP_ACCENT, OP_LABEL } from '../utils/opTypeColors'
import { EventKind, KIND_GLYPHS, PathHighlight } from '../utils/queryDebugger'
import { captureGlyph, statusGlyph } from './OperatorInspector'
import { GraphTable } from './PipelineDagView'

// The pipeline diagram for Investigate: topology and a stable layout from the run-union
// PipelineGraph, an actual-execution overlay per node from the investigation stages (stored
// aggregates, or the selected trace's spans), and the selected journey's path. No per-candidate
// edges are drawn; every state is text plus a glyph, never colour alone.

export type GraphMode = 'aggregate' | 'query'

export interface InvestigationGraphProps {
  graph: PipelineGraph | null
  stages: InvestigationStage[] | StageSummary[] | null
  mode: GraphMode
  selectedStageId: string | null
  highlight: PathHighlight | null
  collapsed: boolean
  onToggleCollapsed: () => void
  onSelectStage: (opId: string | null) => void
}

export interface NodeOverlay {
  /** Short text lines shown on the card; each states its own unit (queries, candidates, events). */
  lines: string[]
  /** Glyph for the node's state (aggregate: unknown boundaries; query: status/capture), empty when nominal. */
  glyph: string
  observed: boolean
}

const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2]

function matching<S extends InvestigationStage | StageSummary>(nodeId: string, stages: S[], collapsed: boolean): S[] {
  return stages.filter((stage) => (collapsed ? collapsedNodeId(stage.op_id) : stage.op_id) === nodeId)
}

/** Overlay text for one node. Aggregate mode sums the stored summaries that fold onto the node. */
export function nodeOverlay(nodeId: string, stages: InvestigationStage[] | StageSummary[] | null, mode: GraphMode, collapsed: boolean): NodeOverlay {
  if (!stages) return { lines: [mode === 'query' ? 'no trace stages' : 'no stored stage counts'], glyph: '', observed: false }
  if (mode === 'aggregate') {
    const found = matching(nodeId, stages.filter(isStageSummary), collapsed)
    if (found.length === 0) return { lines: ['no invocations recorded'], glyph: '', observed: false }
    const sum = (key: keyof Omit<StageSummary, 'op_id' | 'operator_id'>) => found.reduce((total, stage) => total + stage[key], 0)
    const served = sum('queries_served')
    const skipped = sum('queries_skipped')
    const partial = sum('partial_boundaries')
    return {
      lines: [
        `served ${served} of ${served + skipped} queries`,
        `received ${sum('candidates_received')} candidates`,
        `removed ${sum('removal_events')} · introduced ${sum('introduced')}`,
        `unknown boundaries ${partial}`,
      ],
      glyph: partial > 0 ? '⚠' : skipped > 0 && served === 0 ? '⊘' : '',
      observed: true,
    }
  }
  const found = matching(
    nodeId,
    stages.filter((stage): stage is InvestigationStage => !isStageSummary(stage)),
    collapsed,
  )
  if (found.length === 0) return { lines: ['not observed for this query'], glyph: '', observed: false }
  const statuses = [...new Set(found.map((stage) => stage.status))]
  const first = found[0]
  const captures = [...new Set(found.map((stage) => `${stage.input_capture}/${stage.output_capture}`))]
  const inGlyph = captureGlyph(first.input_capture)
  const outGlyph = captureGlyph(first.output_capture)
  const glyph = statuses.includes('ERROR') || statuses.includes('TIMEOUT') ? '✕' : statuses.includes('SKIPPED_BY_GATE') ? '⊘' : inGlyph || outGlyph
  return {
    lines: [
      statuses.join(' / ') + (found.length > 1 ? ` (${found.length} invocations)` : ''),
      captures.length === 1 ? `in ${first.input_capture} · out ${first.output_capture}` : `capture ${captures.join(', ')}`,
      `received ${found.reduce((total, stage) => total + stage.received, 0)} · emitted ${found.reduce((total, stage) => total + stage.emitted, 0)} candidates`,
    ],
    glyph,
    observed: true,
  }
}

function mapHighlight(highlight: PathHighlight | null, collapsed: boolean): { nodes: Map<string, EventKind>; edges: Set<string>; incomplete: Set<string> } {
  const nodes = new Map<string, EventKind>()
  const edges = new Set<string>()
  const incomplete = new Set<string>()
  if (!highlight) return { nodes, edges, incomplete }
  const id = (opId: string) => (collapsed ? collapsedNodeId(opId) : opId)
  for (const opId of highlight.nodeIds) {
    const kind = highlight.kinds[opId]
    const existing = nodes.get(id(opId))
    if (!existing || kind === 'removed' || kind === 'unknown') nodes.set(id(opId), kind)
  }
  for (const [source, target] of highlight.edges) if (id(source) !== id(target)) edges.add(`${id(source)}→${id(target)}`)
  for (const opId of highlight.incomplete) incomplete.add(id(opId))
  return { nodes, edges, incomplete }
}

function StageCard({
  node,
  overlay,
  kind,
  selected,
  dimmed,
  onSelect,
}: {
  node: LaidOutNode
  overlay: NodeOverlay
  kind: EventKind | null
  selected: boolean
  dimmed: boolean
  onSelect: (id: string) => void
}) {
  const accent = OP_ACCENT[node.op_type] ?? OP_ACCENT.TRANSFORM
  const onPath = kind !== null
  return (
    <foreignObject x={node.x} y={node.y} width={node.w} height={node.h} style={{ overflow: 'visible' }}>
      <button
        type="button"
        onClick={() => onSelect(node.node_id)}
        aria-pressed={selected}
        className="box-border flex h-full w-full flex-col gap-0.5 rounded-xl px-2.5 py-2 text-left"
        style={{
          background: accent.fill,
          border: `${selected || onPath ? 2.5 : 1.5}px solid ${selected ? accent.text : onPath ? 'rgb(var(--accent))' : accent.stroke}`,
          boxShadow: selected ? `0 0 0 2px ${accent.fill}` : undefined,
          opacity: dimmed ? 0.55 : 1,
          width: node.w,
          height: node.h,
        }}
        title={[node.label, node.node_id, ...overlay.lines].join('\n')}
      >
        <div className="flex min-w-0 items-center justify-between gap-1">
          <span className="truncate text-[9px] font-bold uppercase tracking-wide" style={{ color: accent.text }}>
            {OP_LABEL[node.op_type] ?? node.op_type}
          </span>
          {overlay.glyph && (
            <span className="shrink-0 text-[11px] text-ink" aria-hidden="true">
              {overlay.glyph}
            </span>
          )}
        </div>
        <div className="truncate text-xs font-semibold leading-snug text-ink">{node.label}</div>
        {overlay.lines.map((line) => (
          <div key={line} className={`truncate text-[9px] leading-tight ${overlay.observed ? 'text-ink-muted' : 'text-ink-faint italic'}`}>
            {line}
          </div>
        ))}
        {kind && (
          <div className="mt-auto text-[10px] font-medium text-ink">
            <span aria-hidden="true">{KIND_GLYPHS[kind]}</span> {kind}
          </div>
        )}
      </button>
    </foreignObject>
  )
}

const LEGEND: Array<{ heading: string; items: Array<[string, string]> }> = [
  { heading: 'Status', items: [['●', 'FIRED'], ['⊘', 'SKIPPED_BY_GATE'], ['✕', 'ERROR / TIMEOUT']] },
  { heading: 'Capture', items: [['', 'recorded'], ['⚠', 'partial (truncated, positional, inferred)'], ['✕', 'unavailable']] },
  { heading: 'Path', items: [['+', 'introduced'], ['=', 'retained'], ['↑', 'promoted'], ['↓', 'demoted'], ['✕', 'removed'], ['↻', 'recovered'], ['◌', 'unknown']] },
]

const zoomButtonClass =
  'rounded border border-hairline bg-surface px-2 py-0.5 text-xs text-ink hover:bg-surface-muted disabled:opacity-40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-600'

export default function InvestigationGraph({ graph, stages, mode, selectedStageId, highlight, collapsed, onToggleCollapsed, onSelectStage }: InvestigationGraphProps) {
  const [zoomIndex, setZoomIndex] = useState(2)
  const zoom = ZOOM_STEPS[zoomIndex]
  const shown = useMemo(() => (graph ? (collapsed ? collapseInvocations(graph) : graph) : null), [graph, collapsed])
  const layout = useMemo(() => (shown ? layoutPipelineGraph(shown) : null), [shown])
  const repeats = graph ? repeatedInvocationCount(graph) : 0
  const path = useMemo(() => mapHighlight(highlight, collapsed), [highlight, collapsed])

  if (!graph || !shown || !layout) {
    return (
      <p role="status" className="text-sm text-ink-muted">
        No pipeline topology recorded for this run; the tables below still hold every indexed journey.
      </p>
    )
  }

  const selectedId = selectedStageId ? (collapsed ? collapsedNodeId(selectedStageId) : selectedStageId) : null
  const summary = [
    `Pipeline ${shown.pipeline_id}: ${shown.nodes.length} operators, ${shown.edges.length} edges`,
    mode === 'query' ? 'showing one query’s execution' : 'showing counts over the whole run',
    selectedId ? `${selectedId} selected` : null,
    highlight ? `path through ${highlight.nodeIds.join(', ')}` : null,
  ]
    .filter(Boolean)
    .join('; ')

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
        <span>
          {mode === 'query' ? 'One query’s execution' : 'Run totals per operator'} · {shown.nodes.length} operators
        </span>
        {repeats > 0 && (
          <button type="button" onClick={onToggleCollapsed} className={zoomButtonClass} aria-pressed={!collapsed}>
            {collapsed ? 'Expand' : 'Collapse'} repeated invocations ({repeats})
          </button>
        )}
        <span className="ml-auto inline-flex items-center gap-1" role="group" aria-label="Zoom">
          <button type="button" aria-label="Zoom out" className={zoomButtonClass} disabled={zoomIndex === 0} onClick={() => setZoomIndex((i) => Math.max(0, i - 1))}>
            −
          </button>
          <span className="w-10 text-center font-mono tabular-nums">{Math.round(zoom * 100)}%</span>
          <button type="button" aria-label="Zoom in" className={zoomButtonClass} disabled={zoomIndex === ZOOM_STEPS.length - 1} onClick={() => setZoomIndex((i) => Math.min(ZOOM_STEPS.length - 1, i + 1))}>
            +
          </button>
          <button type="button" aria-label="Reset zoom" className={zoomButtonClass} disabled={zoomIndex === 2} onClick={() => setZoomIndex(2)}>
            Reset
          </button>
        </span>
      </div>
      <div className="max-h-[520px] overflow-auto rounded-lg border border-hairline bg-surface-muted/40 pb-2">
        <svg
          width={layout.width * zoom}
          height={layout.height * zoom}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          className="block"
          role="img"
          aria-label={summary}
        >
          <defs>
            <marker id={`inv-arrow-${shown.pipeline_id}`} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse">
              <path d="M0,0 L8,4 L0,8 Z" fill="rgb(var(--ink-faint))" />
            </marker>
            <marker id={`inv-arrow-path-${shown.pipeline_id}`} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse">
              <path d="M0,0 L8,4 L0,8 Z" fill="rgb(var(--accent))" />
            </marker>
          </defs>
          {layout.edges.map((edge) => {
            const onPath = path.edges.has(`${edge.source}→${edge.target}`)
            return (
              <path
                key={`${edge.source}→${edge.target}`}
                d={edge.path}
                fill="none"
                stroke={onPath ? 'rgb(var(--accent))' : 'rgb(var(--ink-faint))'}
                strokeWidth={onPath ? 3 : edge.kind === 'fan_in' ? 2 : 1.5}
                strokeDasharray={edge.kind === 'fan_in' && !onPath ? '5 3' : undefined}
                markerEnd={`url(#inv-arrow${onPath ? '-path' : ''}-${shown.pipeline_id})`}
                opacity={onPath ? 1 : highlight ? 0.35 : 0.7}
                data-on-path={onPath ? 'true' : undefined}
              />
            )
          })}
          {layout.nodes.map((node) => (
            <StageCard
              key={node.node_id}
              node={node}
              overlay={nodeOverlay(node.node_id, stages, mode, collapsed)}
              kind={path.nodes.get(node.node_id) ?? null}
              selected={selectedId === node.node_id}
              dimmed={highlight !== null && !path.nodes.has(node.node_id)}
              onSelect={(id) => onSelectStage(selectedId === id ? null : id)}
            />
          ))}
        </svg>
      </div>
      <dl className="flex flex-wrap gap-x-5 gap-y-1 text-[10px] text-ink-muted" aria-label="Legend">
        {LEGEND.map((group) => (
          <div key={group.heading} className="flex flex-wrap items-center gap-x-2">
            <dt className="font-semibold uppercase tracking-wide text-ink-faint">{group.heading}</dt>
            {group.items.map(([glyph, text]) => (
              <dd key={text} className="inline-flex items-center gap-1">
                {glyph && <span aria-hidden="true">{glyph}</span>}
                {text}
              </dd>
            ))}
          </div>
        ))}
      </dl>
      <details>
        <summary className="cursor-pointer text-xs font-medium text-accent">Operator table (accessible equivalent)</summary>
        <div className="mt-2">
          <GraphTable graph={shown} />
        </div>
      </details>
    </div>
  )
}
