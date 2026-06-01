import type { ReactElement } from 'react'
import { ResponsiveContainer } from 'recharts'

interface Props {
  height: number
  children: ReactElement
}

/** Fixed-height chart shell — avoids Recharts ResponsiveContainer 0-size / resize loops. */
export default function ChartFrame({ height, children }: Props) {
  return (
    <div style={{ width: '100%', height, minHeight: height, minWidth: 0 }}>
      <ResponsiveContainer width="100%" height="100%" debounce={50}>
        {children}
      </ResponsiveContainer>
    </div>
  )
}
