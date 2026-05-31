import { Bar, BarChart, CartesianGrid, Cell, ErrorBar, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useEffect, useState } from 'react'
import { ClassifierCalibrationResponse, fetchClassifierCalibration } from '../api'

const CLASS_COLORS: Record<string, string> = {
  easy: '#22c55e',
  medium: '#3b82f6',
  hard: '#ef4444',
}

export default function ClassifierCalibration({ runId }: { runId: string }) {
  const [data, setData] = useState<ClassifierCalibrationResponse | null>(null)

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

  const chartData = data.classes
    .filter((c) => c.n > 0 && c.mean_recall10 != null)
    .map((c) => ({
      name: c.class,
      mean: c.mean_recall10!,
      err: [c.mean_recall10! - (c.ci_low ?? c.mean_recall10!), (c.ci_high ?? c.mean_recall10!) - c.mean_recall10!],
      n: c.n,
      agreement: c.agreement_rate,
    }))

  return (
    <div className="md:col-span-3 border border-gray-200 rounded p-3 bg-white">
      <div className="text-xs uppercase tracking-wide text-gray-500 mb-2">
        Classifier Calibration — Mean Recall@10 by Predicted Difficulty
      </div>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} width={32} />
            <Tooltip
              formatter={(value: number) => value.toFixed(3)}
              labelFormatter={(label) => `Predicted: ${label}`}
            />
            <Bar dataKey="mean" radius={[4, 4, 0, 0]}>
              {chartData.map((entry) => (
                <Cell key={entry.name} fill={CLASS_COLORS[entry.name] ?? '#94a3b8'} />
              ))}
              <ErrorBar dataKey="err" direction="y" width={4} strokeWidth={2} stroke="#64748b" />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-gray-600">
        {data.classes.filter((c) => c.n > 0).map((c) => (
          <span key={c.class}>
            <span className="font-medium capitalize">{c.class}</span>: n={c.n}
            {c.agreement_rate != null && `, agreement=${(c.agreement_rate * 100).toFixed(0)}%`}
          </span>
        ))}
      </div>
    </div>
  )
}
