export const fmtQuality = (v: number): string => v.toFixed(3)
export const fmtLatencyMs = (v: number): string => Math.round(v).toLocaleString()
export const fmtPValue = (v: number): string => v.toFixed(3)
export const fmtPct = (v: number): string => `${v.toFixed(1)}%`
export const fmtCost = (v: number): string => `$${v.toFixed(2)}`
