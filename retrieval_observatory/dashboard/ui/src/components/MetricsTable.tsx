import { MetricEntry, MetricsMap, StageContribution } from '../api'
import { formatMetricKey } from '../utils/formatMetricKey'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY, lookupGlossary } from '../utils/metricGlossary'
import { fmtQuality, fmtLatencyMs } from '../utils/format'

interface Props {
  metrics: MetricsMap
  pValues?: Record<string, number>
  /** Published baselines keyed by "metric@k" e.g. {"ndcg@10": 0.326} */
  baselines?: Record<string, number>
  /** Latency budget in ms — highlights latency_p50 cells green/red */
  latencyBudgetMs?: number
  /** Per-pipeline diagnostic label counts from aggregate_diagnostics.by_pipeline */
  diagnosticsByPipeline?: Record<string, { n: number; labels: Record<string, number> }>
  /** Stage contributions from overview — used to render inline q-value delta pills */
  stageContributions?: StageContribution[]
}

function fmtCell(v: number, isLatency: boolean): string {
  return isLatency ? fmtLatencyMs(v) : fmtQuality(v)
}

function isLatencyPercentile(metricName: string): boolean {
  return metricName.startsWith('latency_p')
}

function ciLabel(entry: MetricEntry, isLatencyPercentileRow: boolean): string {
  if (isLatencyPercentileRow) return '—'
  if (entry.ci_low == null || entry.ci_high == null) return '—'
  const isLatency = entry.metric_name.startsWith('latency')
  return `[${fmtCell(entry.ci_low, isLatency)}, ${fmtCell(entry.ci_high, isLatency)}]`
}

function latencySummaryHint(): JSX.Element {
  return (
    <span
      className="ml-1 text-[9px] text-ink-faint cursor-help"
      title={METRIC_GLOSSARY.latency_percentile_summary}
    >
      (pct)
    </span>
  )
}

function CIBadge({ entry }: { entry: MetricEntry }) {
  if (isLatencyPercentile(entry.metric_name)) return null
  if (entry.n < 30) {
    return <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-status-neutral/10 text-status-neutral font-medium cursor-help" title={`n=${entry.n} (<30). ${METRIC_GLOSSARY.underpowered}`}>underpowered</span>
  }
  if (entry.ci_low == null || entry.ci_high == null) return null
  const ciWidth = entry.ci_high - entry.ci_low
  const meanAbs = Math.abs(entry.mean)
  const relWidth = ciWidth / Math.max(meanAbs, 0.001)
  if (relWidth >= 0.35) {
    return <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-status-warning/10 text-status-warning font-medium cursor-help" title={`Relative CI width ${(relWidth * 100).toFixed(0)}% (threshold 35%). ${METRIC_GLOSSARY.wide_ci}`}>wide CI</span>
  }
  if (ciWidth >= 0.05 && meanAbs < 0.2) {
    return (
      <span
        className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-status-warning/10 text-status-warning font-medium cursor-help"
        title={`CI width ${ciWidth.toFixed(3)} (threshold 0.05) and |mean| ${meanAbs.toFixed(3)} (<0.2). ${METRIC_GLOSSARY.wide_ci_abs}`}
      >
        sparse CI
      </span>
    )
  }
  if (relWidth < 0.15) {
    return <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-status-positive/10 text-status-positive font-medium cursor-help" title={`Relative CI width ${(relWidth * 100).toFixed(0)}% (<15%). ${METRIC_GLOSSARY.stable}`}>stable</span>
  }
  return null
}

function ZeroRateBadge({ zeroPct }: { zeroPct: number }) {
  if (zeroPct <= 20) return null
  const high = zeroPct > 40
  return (
    <span
      className={`ml-1.5 text-[9px] px-1 py-0.5 rounded font-medium cursor-help ${
        high ? 'bg-status-negative/10 text-status-negative' : 'bg-status-warning/10 text-status-warning'
      }`}
      title={`Zero-score rate ${zeroPct.toFixed(1)}% (warn >20%, high >40%). ${METRIC_GLOSSARY.high_zero_pct}`}
    >
      {high ? 'high zeros' : 'zeros warning'}
    </span>
  )
}

function isProfileMetric(name: string): boolean {
  return name.startsWith('profile_')
}

/** Build a lookup: toPipelineId → { metricLabel → delta info } for the final-stage of each pipeline pair. */
function buildDeltaLookup(contributions: StageContribution[]): Map<string, Map<string, { absolute: number; q_value: number | null; significant: boolean }>> {
  const map = new Map<string, Map<string, { absolute: number; q_value: number | null; significant: boolean }>>()
  for (const contrib of contributions) {
    const inner = new Map<string, { absolute: number; q_value: number | null; significant: boolean }>()
    for (const [label, delta] of Object.entries(contrib.deltas)) {
      inner.set(label, { absolute: delta.absolute, q_value: delta.q_value, significant: delta.significant })
    }
    map.set(contrib.to_pipeline, inner)
  }
  return map
}

const HEALTH_METRIC_NAMES = new Set(['failure_rate', 'timeout_rate', 'dropout_count'])
const E2E_LATENCY_NAMES = new Set(['latency_p50', 'latency_p95', 'latency_p99'])
const LATENCY_PERCENTILE_ORDER = ['latency_p50', 'latency_p95', 'latency_p99']

const METRIC_ORDER = ['ndcg', 'recall', 'precision', 'mrr', 'map', 'latency']
function metricSortKey(metricName: string): number {
  const idx = METRIC_ORDER.findIndex((m) => metricName.toLowerCase().includes(m))
  return idx === -1 ? 99 : idx
}

function fmtPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`
}

export default function MetricsTable({ metrics, pValues, baselines = {}, latencyBudgetMs, diagnosticsByPipeline, stageContributions = [] }: Props) {
  const deltaLookup = buildDeltaLookup(stageContributions)
  const hasBaselines = Object.keys(baselines).length > 0

  // --- Extract stage_index=-1 data: health metrics + E2E latency ---
  const pipelineHealth: Record<string, Record<string, MetricEntry>> = {}
  const e2eLatency: Record<string, MetricEntry[]> = {}

  for (const [, entry] of Object.entries(metrics)) {
    if (entry.stage_index !== -1) continue
    if (HEALTH_METRIC_NAMES.has(entry.metric_name)) {
      pipelineHealth[entry.pipeline_id] ??= {}
      pipelineHealth[entry.pipeline_id][entry.metric_name] = entry
    }
    if (E2E_LATENCY_NAMES.has(entry.metric_name)) {
      e2eLatency[entry.pipeline_id] ??= []
      e2eLatency[entry.pipeline_id].push(entry)
    }
  }

  // Sort E2E latency entries P50 → P95 → P99
  for (const pid of Object.keys(e2eLatency)) {
    e2eLatency[pid].sort((a, b) =>
      LATENCY_PERCENTILE_ORDER.indexOf(a.metric_name) - LATENCY_PERCENTILE_ORDER.indexOf(b.metric_name)
    )
  }

  // --- Group positive-stage entries by pipeline_id, then stage_index ---
  const byPipeline: Record<string, Record<number, Array<[string, MetricEntry]>>> = {}
  const pipelineOrder: string[] = []

  for (const [key, entry] of Object.entries(metrics)) {
    if (entry.stage_index < 0) continue
    if (!byPipeline[entry.pipeline_id]) {
      byPipeline[entry.pipeline_id] = {}
      pipelineOrder.push(entry.pipeline_id)
    }
    if (!byPipeline[entry.pipeline_id][entry.stage_index]) {
      byPipeline[entry.pipeline_id][entry.stage_index] = []
    }
    byPipeline[entry.pipeline_id][entry.stage_index].push([key, entry])
  }

  // Also collect pipelines that only appear in stage_index=-1 (e.g. health-only)
  for (const pid of Object.keys(pipelineHealth)) {
    if (!pipelineOrder.includes(pid)) pipelineOrder.push(pid)
  }

  // Sort entries within each stage: NDCG → Recall → MRR → MAP → Latency
  for (const pid of pipelineOrder) {
    for (const stage of Object.keys(byPipeline[pid] ?? {})) {
      byPipeline[pid][Number(stage)].sort(([, a], [, b]) =>
        metricSortKey(a.metric_name) - metricSortKey(b.metric_name) ||
        (a.k - b.k)
      )
    }
  }

  // Detect multi-stage pipelines for stage role labels
  const pipelineStages: Record<string, Set<number>> = {}
  for (const [, e] of Object.entries(metrics)) {
    if (e.stage_index < 0) continue
    if (!pipelineStages[e.pipeline_id]) pipelineStages[e.pipeline_id] = new Set()
    pipelineStages[e.pipeline_id].add(e.stage_index)
  }
  const multiStagePipelines = new Set(
    Object.entries(pipelineStages)
      .filter(([, stages]) => stages.size > 1)
      .map(([pid]) => pid)
  )

  // Scored coverage: dropout_count.n = total_attempted; first quality metric .n = scored
  const scoredCoverage: Record<string, { scored: number; attempted: number }> = {}
  for (const pid of pipelineOrder) {
    const attempted = pipelineHealth[pid]?.dropout_count?.n ?? null
    const stageZeroEntries = byPipeline[pid]?.[0]
    const firstQuality = stageZeroEntries?.find(([, e]) =>
      ['ndcg', 'recall', 'precision', 'mrr', 'map'].includes(e.metric_name)
    )
    const scored = firstQuality?.[1]?.n ?? null
    if (attempted != null && scored != null) {
      scoredCoverage[pid] = { scored, attempted }
    }
  }

  if (pipelineOrder.length === 0) {
    return <p className="text-sm text-ink-faint">No metrics available.</p>
  }

  const toPipelineLabel = (pid: string) =>
    pid.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

  const toStageLabel = (pid: string, stage: number): string => {
    if (!multiStagePipelines.has(pid)) return ''
    return stage === 0 ? 'Stage 0 · Retrieval' : `Stage ${stage} · Reranking`
  }

  // Column count helper — keeps colSpan in sync with header columns
  const colCount = hasBaselines ? (pValues ? 8 : 7) : (pValues ? 7 : 6)

  return (
    <div className="overflow-x-auto">
      <p className="text-xs text-ink-muted mb-2">
        Stability badges use explicit thresholds (underpowered n&lt;30, wide CI relative width &ge;35%, sparse CI width &ge;0.05 with low mean, stable relative width &lt;15%, high zeros &gt;40%).
        <MetricTooltip text={`${METRIC_GLOSSARY.underpowered}\n\n${METRIC_GLOSSARY.wide_ci}\n\n${METRIC_GLOSSARY.wide_ci_abs}\n\n${METRIC_GLOSSARY.stable}\n\n${METRIC_GLOSSARY.high_zero_pct}`} />
      </p>
      <table className="min-w-full text-sm">
        <thead>
          <tr className="bg-surface-muted text-left">
            <th className="px-3 py-2 font-semibold text-ink-muted">
              Metric
              <MetricTooltip text={METRIC_GLOSSARY.stage} />
            </th>
            <th className="px-3 py-2 font-semibold text-ink-muted text-right">Mean</th>
            <th className="px-3 py-2 font-semibold text-ink-muted text-right">Std</th>
            <th className="px-3 py-2 font-semibold text-ink-muted text-right">
              95% CI
              <MetricTooltip text={METRIC_GLOSSARY.ci} alignLeft />
            </th>
            <th className="px-3 py-2 font-semibold text-ink-muted text-right">N</th>
            <th className="px-3 py-2 font-semibold text-ink-muted text-right">
              Zero%
              <MetricTooltip text={METRIC_GLOSSARY.zero_pct} alignLeft />
            </th>
            {hasBaselines && (
              <th className="px-3 py-2 font-semibold text-ink-faint text-right text-xs">
                Ref (BM25)
                <MetricTooltip text={METRIC_GLOSSARY.ref_bm25} alignLeft />
              </th>
            )}
            {pValues && (
              <th className="px-3 py-2 font-semibold text-ink-muted text-right">
                p-value
                <MetricTooltip text={METRIC_GLOSSARY.p_value} alignLeft />
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {pipelineOrder.map((pid, pidIdx) => {
            const stages = Object.keys(byPipeline[pid] ?? {}).map(Number).sort((a, b) => a - b)
            const health = pipelineHealth[pid] ?? {}
            const coverage = scoredCoverage[pid] ?? null
            const diagLabels = diagnosticsByPipeline?.[pid]
            const e2e = e2eLatency[pid] ?? []
            const isMultiStage = multiStagePipelines.has(pid)

            // Health strip values
            const failureRate = health.failure_rate?.mean ?? 0
            const timeoutRate = health.timeout_rate?.mean ?? 0
            const dropoutCount = health.dropout_count?.mean ?? 0
            const hasHealth = health.failure_rate != null

            const coveragePct = coverage ? coverage.scored / coverage.attempted : null
            const coverageLow = coveragePct != null && coveragePct < 0.95

            return (
              <>
                {/* Pipeline group header */}
                <tr key={`header-${pid}`} className={pidIdx > 0 ? 'border-t-2 border-hairline' : ''}>
                  <td
                    colSpan={colCount}
                    className="px-3 py-2 bg-surface-muted text-xs font-bold text-ink-muted uppercase tracking-wide"
                  >
                    {toPipelineLabel(pid)}
                  </td>
                </tr>

                {/* Pipeline Health Strip */}
                {(hasHealth || coverage || diagLabels) && (
                  <tr key={`health-${pid}`}>
                    <td colSpan={colCount} className="px-3 py-1.5 bg-surface-muted border-t border-hairline">
                      <div className="flex flex-wrap gap-1.5 items-center">
                        {/* Scored coverage */}
                        {coverage && (
                          <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                            coverageLow
                              ? 'bg-status-negative/10 text-status-negative'
                              : 'bg-surface text-ink-muted'
                          }`}>
                            Scored {coverage.scored}/{coverage.attempted}
                            {coverageLow ? ' ⚠' : ''}
                          </span>
                        )}

                        {/* Failure rate */}
                        {hasHealth && (
                          <>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                              failureRate > 0.05
                                ? 'bg-status-negative/10 text-status-negative'
                                : failureRate > 0.01
                                ? 'bg-status-warning/10 text-status-warning'
                                : 'bg-surface text-ink-faint'
                            }`}>
                              Failure {fmtPct(failureRate)}
                            </span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                              timeoutRate > 0.02
                                ? 'bg-status-negative/10 text-status-negative'
                                : timeoutRate > 0.005
                                ? 'bg-status-warning/10 text-status-warning'
                                : 'bg-surface text-ink-faint'
                            }`}>
                              Timeout {fmtPct(timeoutRate)}
                            </span>
                            {dropoutCount > 0 && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface text-ink-faint font-medium">
                                Dropped {dropoutCount.toFixed(0)}
                              </span>
                            )}
                          </>
                        )}

                        {/* Per-pipeline diagnostic failure labels */}
                        {diagLabels && diagLabels.n > 0 && (() => {
                          const labelOrder = ['candidate_miss', 'reranker_drop', 'not_retrieved_by_any_pipeline', 'qrel_not_in_corpus', 'corpus_identity_unknown', 'lexical_mismatch', 'semantic_mismatch']
                          return labelOrder
                            .filter((l) => (diagLabels.labels[l] ?? 0) > 0)
                            .map((label) => {
                              const pct = ((diagLabels.labels[label] / diagLabels.n) * 100).toFixed(0)
                              const display = label.replace(/_/g, ' ')
                              const isHigh = diagLabels.labels[label] / diagLabels.n > 0.3
                              return (
                                <span key={label} className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                                  isHigh ? 'bg-status-warning/10 text-status-warning' : 'bg-surface text-ink-faint'
                                }`}>
                                  {display} {pct}%
                                </span>
                              )
                            })
                        })()}
                      </div>
                    </td>
                  </tr>
                )}

                {stages.map((stage, stageIdx) => {
                  const stageLabel = toStageLabel(pid, stage)
                  const rows = byPipeline[pid][stage]
                  const isLastStage = stageIdx === stages.length - 1
                  const pipelineDeltas = isLastStage ? deltaLookup.get(pid) : undefined
                  return (
                    <>
                      {/* Stage sub-header (only for multi-stage pipelines) */}
                      {stageLabel && (
                        <tr key={`stage-${pid}-${stage}`}>
                          <td
                            colSpan={colCount}
                            className="px-3 py-1 bg-surface-muted text-[11px] font-semibold text-accent border-t border-hairline"
                          >
                            {stageLabel}
                          </td>
                        </tr>
                      )}

                      {/* Metric rows */}
                      {rows.map(([key, entry]) => {
                        const pv = pValues?.[key]
                        const significant = pv !== undefined && pv < 0.05
                        const isLatencyPct = isLatencyPercentile(entry.metric_name)
                        const isLatency = entry.metric_name.startsWith('latency')
                        const isP50 = entry.metric_name === 'latency_p50'
                        const isP99 = entry.metric_name === 'latency_p99'
                        const baselineKey = entry.k > 0 ? `${entry.metric_name}@${entry.k}` : null
                        const baselineVal = baselineKey ? baselines[baselineKey] : undefined
                        const zeroPctHigh = !isLatency && entry.zero_pct > 40
                        const zeroPctMed = !isLatency && entry.zero_pct > 20 && !zeroPctHigh

                        // Latency budget highlighting for P50 rows
                        const withinBudget = isP50 && latencyBudgetMs != null && entry.mean <= latencyBudgetMs
                        const overBudget = isP50 && latencyBudgetMs != null && entry.mean > latencyBudgetMs
                        const meanCellClass = withinBudget
                          ? 'bg-status-positive/10 text-status-positive'
                          : overBudget
                          ? 'bg-status-negative/10 text-status-negative'
                          : ''

                        // Q-value delta pill for last-stage quality metrics
                        const deltaKey = entry.k > 0 ? `${entry.metric_name}@${entry.k}` : entry.metric_name
                        const delta = !isLatency ? pipelineDeltas?.get(deltaKey) : undefined

                        return (
                          <tr key={key} className="hover:bg-surface-muted border-t border-hairline">
                            <td className="px-3 pl-6 py-2 text-ink-muted">
                              {formatMetricKey(key, multiStagePipelines, true)}
                              {entry.metric_name === 'temporal_recall' && (
                                <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded bg-accent/10 text-accent font-medium">time-aware</span>
                              )}
                              {lookupGlossary(entry.metric_name) && (
                                <MetricTooltip text={lookupGlossary(entry.metric_name)!} />
                              )}
                            </td>
                            <td className={`px-3 py-2 text-right tabular-nums font-medium ${meanCellClass}`}>
                              {fmtCell(entry.mean, isLatency)}
                              {isLatencyPct && latencySummaryHint()}
                              <CIBadge entry={entry} />
                              <ZeroRateBadge zeroPct={entry.zero_pct} />
                              {delta && (
                                <span
                                  className={`ml-1.5 text-[9px] px-1 py-0.5 rounded font-medium ${
                                    delta.significant
                                      ? delta.absolute >= 0
                                        ? 'bg-status-positive/10 text-status-positive'
                                        : 'bg-status-negative/10 text-status-negative'
                                      : 'bg-surface-muted text-ink-faint'
                                  }`}
                                  title={delta.q_value != null ? `q=${delta.q_value.toFixed(3)} (BH-corrected)` : 'ns'}
                                >
                                  {delta.absolute >= 0 ? '+' : ''}{delta.absolute.toFixed(3)}
                                  {delta.q_value != null ? ` q=${delta.q_value.toFixed(3)}` : ' ns'}
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-ink-muted">
                              {isLatencyPct || entry.std == null ? (
                                <span className="text-ink-faint" title={METRIC_GLOSSARY.latency_percentile_summary}>—</span>
                              ) : (
                                fmtCell(entry.std, isLatency)
                              )}
                            </td>
                            <td className="px-3 py-2 text-right tabular-nums text-ink-muted text-xs">
                              {ciLabel(entry, isLatencyPct)}
                            </td>
                            <td className="px-3 py-2 text-right text-ink-muted">
                              {isP99 && entry.n < 100
                                ? <span className="text-[9px] px-1 py-0.5 rounded bg-status-warning/10 text-status-warning font-medium" title="P99 on fewer than 100 queries is unreliable">{entry.n} low N</span>
                                : entry.n
                              }
                            </td>
                            <td className={`px-3 py-2 text-right text-xs tabular-nums font-medium ${
                              zeroPctHigh ? 'text-status-negative bg-status-negative/10' :
                              zeroPctMed ? 'text-status-warning bg-status-warning/10' :
                              'text-ink-faint'
                            }`}>
                              {isLatencyPct || isProfileMetric(entry.metric_name) ? (
                                isProfileMetric(entry.metric_name) && entry.zero_pct >= 99 ? (
                                  <span
                                    className="cursor-help"
                                    title={entry.metric_name.includes('network') ? METRIC_GLOSSARY.profile_network_ms : METRIC_GLOSSARY.profile_compute_ms}
                                  >
                                    —
                                  </span>
                                ) : '—'
                              ) : `${entry.zero_pct}% (${entry.zero_count}/${entry.n})`}
                            </td>
                            {hasBaselines && (
                              <td className="px-3 py-2 text-right text-ink-faint text-xs tabular-nums">
                                {baselineVal !== undefined ? fmtQuality(baselineVal) : '—'}
                              </td>
                            )}
                            {pValues && (
                              <td className={`px-3 py-2 text-right tabular-nums ${significant ? 'font-bold text-accent' : 'text-ink-muted'}`}>
                                {pv !== undefined ? `${pv.toFixed(3)}${significant ? ' *' : ''}` : '—'}
                              </td>
                            )}
                          </tr>
                        )
                      })}
                    </>
                  )
                })}

                {/* E2E Total Latency rows (multi-stage only — stage_index=-1 latency) */}
                {isMultiStage && e2e.length > 0 && (
                  <>
                    <tr key={`e2e-header-${pid}`}>
                      <td
                        colSpan={colCount}
                        className="px-3 py-1 bg-accent/10 text-[11px] font-semibold text-accent border-t border-accent/30"
                      >
                        E2E Total Latency
                      </td>
                    </tr>
                    {e2e.map((entry) => {
                      const isP50 = entry.metric_name === 'latency_p50'
                      const isP99 = entry.metric_name === 'latency_p99'
                      const withinBudget = isP50 && latencyBudgetMs != null && entry.mean <= latencyBudgetMs
                      const overBudget = isP50 && latencyBudgetMs != null && entry.mean > latencyBudgetMs
                      const meanCellClass = withinBudget
                        ? 'bg-status-positive/10 text-status-positive'
                        : overBudget
                        ? 'bg-status-negative/10 text-status-negative'
                        : ''
                      const label = entry.metric_name === 'latency_p50'
                        ? 'E2E P50'
                        : entry.metric_name === 'latency_p95'
                        ? 'E2E P95'
                        : 'E2E P99'
                      return (
                        <tr key={`e2e-${pid}-${entry.metric_name}`} className="hover:bg-surface-muted border-t border-hairline">
                          <td className="px-3 pl-6 py-2 text-ink-muted font-semibold">
                            {label}
                            {lookupGlossary(entry.metric_name) && (
                              <MetricTooltip text={lookupGlossary(entry.metric_name)!} />
                            )}
                          </td>
                          <td className={`px-3 py-2 text-right tabular-nums font-semibold ${meanCellClass}`}>
                            {fmtLatencyMs(entry.mean)}
                            {latencySummaryHint()}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-ink-muted">
                            <span title={METRIC_GLOSSARY.latency_percentile_summary}>—</span>
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-ink-muted text-xs">
                            <span title={METRIC_GLOSSARY.latency_percentile_summary}>—</span>
                          </td>
                          <td className="px-3 py-2 text-right text-ink-muted">
                            {isP99 && entry.n < 100
                              ? <span className="text-[9px] px-1 py-0.5 rounded bg-status-warning/10 text-status-warning font-medium" title="P99 on fewer than 100 queries is unreliable">{entry.n} low N</span>
                              : entry.n
                            }
                          </td>
                          <td className="px-3 py-2 text-right text-ink-faint">—</td>
                          {hasBaselines && <td className="px-3 py-2 text-right text-ink-faint">—</td>}
                          {pValues && <td className="px-3 py-2 text-right text-ink-faint">—</td>}
                        </tr>
                      )
                    })}
                  </>
                )}
              </>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
