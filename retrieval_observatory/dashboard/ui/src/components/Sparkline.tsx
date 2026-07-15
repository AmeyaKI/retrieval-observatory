import { AreaChart, Area, ResponsiveContainer } from 'recharts'

interface Props {
  /** Trend values, oldest first. Accepts raw numbers or {value} objects. */
  data: number[] | { value: number }[]
  width?: number
  height?: number
  color?: string
  strokeWidth?: number
}

/**
 * Minimal inline trend indicator for KPI tiles — no axes, gridlines, tooltip, or legend.
 * Unlike ChartFrame (which uses a fixed-height block wrapper for full-size charts), this
 * sizes to a small inline footprint. Follows the same ResponsiveContainer conventions
 * (explicit pixel width/height + debounce) to avoid the 0-size/resize-loop issues
 * ChartFrame guards against.
 */
export default function Sparkline({ data, width = 80, height = 24, color, strokeWidth = 1.5 }: Props) {
  if (!data || data.length < 2) return null

  const points = (typeof data[0] === 'number' ? (data as number[]).map((value) => ({ value })) : (data as { value: number }[]))
  const strokeColor = color ?? 'rgb(var(--accent))'

  return (
    <div style={{ width, height, minWidth: width, minHeight: height }} aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%" debounce={50}>
        <AreaChart data={points} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
          <defs>
            <linearGradient id="sparkline-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={strokeColor} stopOpacity={0.25} />
              <stop offset="100%" stopColor={strokeColor} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="value"
            stroke={strokeColor}
            strokeWidth={strokeWidth}
            fill="url(#sparkline-fill)"
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
