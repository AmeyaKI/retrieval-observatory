import { useEffect, useMemo, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ErrorBar,
} from 'recharts'
import { MetricsMap } from '../api'
import { MetricTooltip } from './MetricTooltip'
import { METRIC_GLOSSARY } from '../utils/metricGlossary'
import { fmtQuality } from '../utils/format'
import { buildPipelineColorMap, collectPipelineIds, getPipelineColor } from '../utils/chartColors'
import {
  buildPipelineMaxStage,
  buildStageRecallGrid,
  collectRecallKValues,
  recallCellKey,
} from '../utils/pipelineStages'
import { PipelineDisplayMeta, stageLabelFromManifest } from '../utils/stageLabels'
import { useChartZoom } from '../hooks/useChartZoom'
import ChartFrame from './ChartFrame'
import ChartZoomControls from './ChartZoomControls'
import ChartZoomSurface from './ChartZoomSurface'

interface Props {
  metrics: MetricsMap
  displayMeta?: PipelineDisplayMeta | null
}

export default function RecallFunnel({ metrics, displayMeta }: Props) {
  const [hiddenRecall, setHiddenRecall] = useState<Set<string>>(new Set())
  const [hiddenNdcg, setHiddenNdcg] = useState<Set<string>>(new Set())

  const recallKValues = useMemo(() => collectRecallKValues(metrics), [metrics])
  const defaultK = recallKValues.includes(10) ? 10 : recallKValues[recallKValues.length - 1] ?? 10
  const [selectedK, setSelectedK] = useState<number>(defaultK)

  useEffect(() => {
    setSelectedK(defaultK)
  }, [defaultK, metrics])

  const activeK = recallKValues.includes(selectedK) ? selectedK : defaultK

  const { domain: yDomain, fitToData, reset, zoomIn, zoomOut, handleWheel, handlePinchScale, isZoomed } = useChartZoom({
    initialDomain: [0, 1],
    clampZeroOne: false,
  })

  const maxStageByPipeline = useMemo(() => buildPipelineMaxStage(metrics), [metrics])
  const pipelineColorMap = useMemo(
    () => buildPipelineColorMap(collectPipelineIds(metrics)),
    [metrics],
  )

  const recallGrid = useMemo(
    () => buildStageRecallGrid(metrics, activeK, displayMeta),
    [metrics, activeK, displayMeta],
  )

  const stageNdcg = useMemo(() => {
    const values = new Map<string, number>()
    const ciMap = new Map<string, { ci_low: number | null; ci_high: number | null }>()
    for (const entry of Object.values(metrics)) {
      if (entry.metric_name !== 'ndcg' || entry.k !== 10 || entry.stage_index < 0) continue
      values.set(recallCellKey(entry.pipeline_id, entry.stage_index), entry.mean)
      ciMap.set(recallCellKey(entry.pipeline_id, entry.stage_index), {
        ci_low: entry.ci_low,
        ci_high: entry.ci_high,
      })
    }
    return { values, ci: ciMap }
  }, [metrics])

  const maxStageIndex = useMemo(() => {
    const fromRecall = recallGrid.maxStageIndex
    let max = fromRecall
    for (const key of stageNdcg.values.keys()) {
      const stageIndex = parseInt(key.split('|')[1] ?? '0', 10)
      max = Math.max(max, stageIndex)
    }
    return max
  }, [recallGrid.maxStageIndex, stageNdcg.values])

  const pipelineIds = recallGrid.pipelineIds

  const omittedAblationCount = useMemo(() => {
    if (!displayMeta?.duplicate_ablation_stages?.length) return 0
    return displayMeta.duplicate_ablation_stages.length
  }, [displayMeta])

  const toggleRecall = (pipelineId: string) => setHiddenRecall((prev) => {
    const next = new Set(prev)
    next.has(pipelineId) ? next.delete(pipelineId) : next.add(pipelineId)
    return next
  })
  const toggleNdcg = (pipelineId: string) => setHiddenNdcg((prev) => {
    const next = new Set(prev)
    next.has(pipelineId) ? next.delete(pipelineId) : next.add(pipelineId)
    return next
  })

  const buildChartRows = useMemo(() => {
    return (
      valueMap: Map<string, number>,
      ciMap?: Map<string, { ci_low: number | null; ci_high: number | null }>,
    ) => {
      const rows: Record<string, string | number | [number, number]>[] = []
      for (let stageIndex = 0; stageIndex <= maxStageIndex; stageIndex += 1) {
        const row: Record<string, string | number | [number, number]> = { stage: `Stage ${stageIndex}` }
        let hasAny = false
        for (const pipelineId of pipelineIds) {
          if ((maxStageByPipeline[pipelineId] ?? 0) < stageIndex) continue
          const key = recallCellKey(pipelineId, stageIndex)
          const v = valueMap.get(key)
          if (v === undefined) continue
          row[pipelineId] = v
          const c = ciMap?.get(key)
          if (c?.ci_low != null && c?.ci_high != null) {
            row[`${pipelineId}_err`] = [v - c.ci_low, c.ci_high - v]
          }
          hasAny = true
        }
        if (hasAny) rows.push(row)
      }
      return rows
    }
  }, [maxStageIndex, pipelineIds, maxStageByPipeline])

  const recallChartData = useMemo(
    () => buildChartRows(recallGrid.values, recallGrid.ci),
    [buildChartRows, recallGrid.values, recallGrid.ci],
  )
  const ndcgChartData = useMemo(
    () => buildChartRows(stageNdcg.values, stageNdcg.ci),
    [buildChartRows, stageNdcg.values, stageNdcg.ci],
  )

  if (recallKValues.length === 0 && stageNdcg.values.size === 0) {
    return <p className="text-sm text-gray-400 dark:text-slate-500">No stage data.</p>
  }

  const hasMultipleStages = maxStageIndex > 0

  const visibleRecallValues = recallChartData.flatMap((row) =>
    pipelineIds
      .filter((pid) => !hiddenRecall.has(pid) && row[pid] != null)
      .map((pid) => row[pid] as number),
  )
  const visibleNdcgValues = ndcgChartData.flatMap((row) =>
    pipelineIds
      .filter((pid) => !hiddenNdcg.has(pid) && row[pid] != null)
      .map((pid) => row[pid] as number),
  )
  const recallDataMin = visibleRecallValues.length > 0 ? Math.min(...visibleRecallValues) : 0
  const recallDataMax = visibleRecallValues.length > 0 ? Math.max(...visibleRecallValues) : 1
  const ndcgDataMin = visibleNdcgValues.length > 0 ? Math.min(...visibleNdcgValues) : 0
  const ndcgDataMax = visibleNdcgValues.length > 0 ? Math.max(...visibleNdcgValues) : 1

  const makeLegendFormatter = (hiddenSet: Set<string>) =>
    (value: string, entry: any) => {
      const pid = String(entry.dataKey ?? value)
      return (
        <span style={{
          opacity: hiddenSet.has(pid) ? 0.35 : 1,
          cursor: 'pointer',
          textDecoration: hiddenSet.has(pid) ? 'line-through' : 'none',
        }}>
          {pid}
        </span>
      )
    }

  const RecallTooltip = ({ active, payload, label }: any) => {
      if (!active || !payload?.length || !label) return null
      const stageIndex = parseInt(String(label).replace('Stage ', ''), 10)
      return (
        <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded shadow p-2 text-xs">
          <p className="font-semibold mb-1">{label}</p>
          {payload.map((p: any) => {
            const pipelineId = String(p.dataKey)
            const stageName = stageLabelFromManifest(displayMeta, pipelineId, stageIndex)
            const stageLabel = stageIndex === 0 ? 'all retrieved' : 'stage input'
            return (
              <p key={p.dataKey} style={{ color: p.color }}>
                {`Recall@${activeK} (${stageLabel}) ${stageName}: ${fmtQuality(p.value)}`}
              </p>
            )
          })}
        </div>
      )
  }

  const NdcgTooltip = ({ active, payload, label }: any) => {
      if (!active || !payload?.length || !label) return null
      const stageIndex = parseInt(String(label).replace('Stage ', ''), 10)
      return (
        <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-700 rounded shadow p-2 text-xs">
          <p className="font-semibold mb-1">{label}</p>
          {payload.map((p: any) => {
            const pipelineId = String(p.dataKey)
            const stageName = stageLabelFromManifest(displayMeta, pipelineId, stageIndex)
            return (
              <p key={p.dataKey} style={{ color: p.color }}>
                {`NDCG@10 ${stageName}: ${fmtQuality(p.value)}`}
              </p>
            )
          })}
        </div>
      )
  }

  const kSelector = recallKValues.length > 1 ? (
    <div className="flex flex-col gap-1 shrink-0 pr-2">
      <span className="text-[10px] font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wide mb-0.5">Recall@K</span>
      {recallKValues.map((k) => (
        <button
          key={k}
          type="button"
          onClick={() => setSelectedK(k)}
          className={`text-xs border rounded px-2 py-1 text-left font-mono ${
            activeK === k
              ? 'bg-indigo-50 text-indigo-700 border-indigo-300 font-semibold'
              : 'text-gray-600 dark:text-slate-300 border-gray-200 dark:border-slate-700 hover:border-indigo-200 hover:text-indigo-600'
          }`}
        >
          @{k}
        </button>
      ))}
    </div>
  ) : null

  return (
    <div className="space-y-6">
      {omittedAblationCount > 0 && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
          {omittedAblationCount} ablation-prefix stage row(s) omitted — identical to a shorter standalone pipeline (from run manifest lineage, not inferred).
        </p>
      )}
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs text-gray-500 dark:text-slate-400">
          Grouped by pipeline stage: each stage row shows only pipelines that include that stage. <strong>Stage 0</strong> recall is scored over all retrieved candidates. <strong>Stage 1+</strong> recall is scored over the subset passed in from the prior stage — a later stage can only find relevant docs that were already in its input, so apparent recall drops are expected and do not mean regression. Check NDCG@10 to measure re-ranking quality.
          <MetricTooltip text={METRIC_GLOSSARY.stage} />
        </p>
        <ChartZoomControls
          domain={yDomain}
          isZoomed={isZoomed}
          onFit={() => fitToData(Math.min(recallDataMin, ndcgDataMin), Math.max(recallDataMax, ndcgDataMax))}
          onReset={reset}
          onZoomIn={zoomIn}
          onZoomOut={zoomOut}
        />
      </div>

      <div className="flex gap-2 items-start">
        {kSelector}
        <div className="flex-1 min-w-0 space-y-6">
          {recallKValues.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-600 dark:text-slate-300 mb-1">
                Recall@{activeK} on Stage Input
                {!recallKValues.includes(10) && <span className="ml-1 text-gray-400 dark:text-slate-500 font-normal">(K=10 unavailable; using K={activeK})</span>}
              </p>
              {hasMultipleStages && (
                <div className="mb-2 px-3 py-2 bg-blue-50 border border-blue-200 rounded text-xs text-blue-800">
                  <span className="font-semibold">Reading this chart:</span> Stage 0 recall is scored over all retrieved documents. Stage 1+ recall is bounded by the candidates passed in from the prior stage — a reranker cannot recall documents it never received. Lower recall at Stage 1+ is expected, not a failure.
                </div>
              )}
              <ChartZoomSurface onWheel={handleWheel} onPinchScale={handlePinchScale}>
                <ChartFrame height={220}>
                  <BarChart data={recallChartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="stage" tick={{ fontSize: 11 }} />
                    <YAxis tickFormatter={(v) => v.toFixed(2)} tick={{ fontSize: 12 }} domain={[yDomain[0], yDomain[1]]} />
                    <Tooltip content={<RecallTooltip />} />
                    <Legend
                      wrapperStyle={{ fontSize: 11 }}
                      onClick={(data) => toggleRecall(data.dataKey as string)}
                      formatter={makeLegendFormatter(hiddenRecall)}
                    />
                    {pipelineIds.map((pid) => (
                      <Bar
                        key={pid}
                        dataKey={pid}
                        name={pid}
                        hide={hiddenRecall.has(pid)}
                        fill={getPipelineColor(pid, pipelineColorMap)}
                        radius={[3, 3, 0, 0]}
                      >
                        <ErrorBar dataKey={`${pid}_err`} width={4} strokeWidth={1.5} stroke={getPipelineColor(pid, pipelineColorMap)} />
                      </Bar>
                    ))}
                  </BarChart>
                </ChartFrame>
              </ChartZoomSurface>
            </div>
          )}

          {stageNdcg.values.size > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-600 dark:text-slate-300 mb-1">NDCG@10 per Stage</p>
              <ChartZoomSurface onWheel={handleWheel} onPinchScale={handlePinchScale}>
                <ChartFrame height={220}>
                  <BarChart data={ndcgChartData} margin={{ top: 4, right: 20, bottom: 4, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="stage" tick={{ fontSize: 11 }} />
                    <YAxis tickFormatter={(v) => v.toFixed(2)} tick={{ fontSize: 12 }} domain={[yDomain[0], yDomain[1]]} />
                    <Tooltip content={<NdcgTooltip />} />
                    <Legend
                      wrapperStyle={{ fontSize: 11 }}
                      onClick={(data) => toggleNdcg(data.dataKey as string)}
                      formatter={makeLegendFormatter(hiddenNdcg)}
                    />
                    {pipelineIds.map((pid) => (
                      <Bar
                        key={`ndcg-${pid}`}
                        dataKey={pid}
                        name={pid}
                        hide={hiddenNdcg.has(pid)}
                        fill={getPipelineColor(pid, pipelineColorMap)}
                        fillOpacity={0.75}
                        radius={[3, 3, 0, 0]}
                      >
                        <ErrorBar dataKey={`${pid}_err`} width={4} strokeWidth={1.5} stroke={getPipelineColor(pid, pipelineColorMap)} />
                      </Bar>
                    ))}
                  </BarChart>
                </ChartFrame>
              </ChartZoomSurface>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
