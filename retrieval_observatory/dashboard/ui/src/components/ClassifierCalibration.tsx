import { Bar, BarChart, CartesianGrid, Cell, ErrorBar, Tooltip, XAxis, YAxis } from 'recharts'
import { useEffect, useState } from 'react'
import { ClassifierCalibrationResponse, fetchClassifierCalibration } from '../api'
import { fmtQuality } from '../utils/format'
import ChartFrame from './ChartFrame'

const CLASS_COLORS: Record<string, string> = {
  easy: '#22c55e',
  medium: '#3b82f6',
  hard: '#ef4444',
}

const ALL_CLASSES = ['easy', 'medium', 'hard'] as const

function buildChartRows(
  classes: ClassifierCalibrationResponse['classes'],
): Array<{ name: string; mean: number | null; err: [number, number]; n: number; agreement: number | null; empty: boolean }> {
  return ALL_CLASSES.map((cls) => {
    const c = classes.find((row) => row.class === cls)
    if (!c || c.n === 0 || c.mean_recall10 == null) {
      return { name: cls, mean: 0, err: [0, 0] as [number, number], n: 0, agreement: null, empty: true }
    }
    return {
      name: cls,
      mean: c.mean_recall10,
      err: [
        c.mean_recall10 - (c.ci_low ?? c.mean_recall10),
        (c.ci_high ?? c.mean_recall10) - c.mean_recall10,
      ] as [number, number],
      n: c.n,
      agreement: c.agreement_rate,
      empty: false,
    }
  })
}

export default function ClassifierCalibration({ runId }: { runId: string }) {
  const [data, setData] = useState<ClassifierCalibrationResponse | null>(null)
  const [view, setView] = useState<'predicted' | 'actual'>('predicted')

  useEffect(() => {
    fetchClassifierCalibration(runId).then(setData).catch(() => setData(null))
  }, [runId])

  if (!data) return null

  if (!data.has_predictions) {
    return (
      <div className="md:col-span-3 border border-gray-200 rounded p-3 bg-white">
        <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">Classifier Calibration</div>
        <p className="text-xs text-gray-400">
          Run a benchmark with a trained difficulty model to see predicted-class Recall@10 validation.
        </p>
      </div>
    )
  }

  const sourceClasses = view === 'predicted' ? data.classes : (data.actual_classes ?? [])
  const chartData = buildChartRows(sourceClasses)

  return (
    <div className="md:col-span-3 border border-gray-200 rounded p-3 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <div className="text-xs uppercase tracking-wide text-gray-500">
          Classifier Calibration — Mean Recall@10 by {view === 'predicted' ? 'Predicted' : 'Actual'} Difficulty
        </div>
        <div className="flex rounded border border-gray-200 overflow-hidden text-xs">
          <button
            type="button"
            onClick={() => setView('predicted')}
            className={`px-2 py-1 ${view === 'predicted' ? 'bg-indigo-50 text-indigo-700 font-medium' : 'text-gray-600 hover:bg-gray-50'}`}
          >
            By predicted
          </button>
          <button
            type="button"
            onClick={() => setView('actual')}
            className={`px-2 py-1 border-l border-gray-200 ${view === 'actual' ? 'bg-indigo-50 text-indigo-700 font-medium' : 'text-gray-600 hover:bg-gray-50'}`}
          >
            By actual
          </button>
        </div>
      </div>

      {data.all_same_prediction && view === 'predicted' && (
        <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1.5 mb-2">
          Model predicts a single class for all queries — likely undertrained. Train on a larger run with easy queries present, then re-run the benchmark.
        </p>
      )}

      <ChartFrame height={192}>
        <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="name" tick={{ fontSize: 11 }} />
          <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} width={32} />
          <Tooltip
            formatter={(value: number, _name, props: { payload?: { empty?: boolean; n?: number } }) =>
              props.payload?.empty ? 'n=0' : fmtQuality(value)
            }
            labelFormatter={(label) => `${view === 'predicted' ? 'Predicted' : 'Actual'}: ${label}`}
          />
          <Bar dataKey="mean" radius={[4, 4, 0, 0]}>
            {chartData.map((entry) => (
              <Cell
                key={entry.name}
                fill={entry.empty ? '#e2e8f0' : (CLASS_COLORS[entry.name] ?? '#94a3b8')}
                fillOpacity={entry.empty ? 0.5 : 1}
              />
            ))}
            <ErrorBar dataKey="err" direction="y" width={4} strokeWidth={2} stroke="#64748b" />
          </Bar>
        </BarChart>
      </ChartFrame>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-gray-600">
        {ALL_CLASSES.map((cls) => {
          const c = sourceClasses.find((row) => row.class === cls)
          return (
            <span key={cls}>
              <span className="font-medium capitalize">{cls}</span>: n={c?.n ?? 0}
              {view === 'predicted' && c?.agreement_rate != null && c.n > 0 && `, agreement=${(c.agreement_rate * 100).toFixed(0)}%`}
            </span>
          )
        })}
      </div>
    </div>
  )
}
