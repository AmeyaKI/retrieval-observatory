function num(v: number | null | undefined): number | null {
  if (v == null || Number.isNaN(v)) return null
  return v
}

export const fmtQuality = (v: number | null | undefined): string => {
  const n = num(v)
  return n == null ? '—' : n.toFixed(3)
}

// Callers append " ms". Sub-millisecond operators are real: rounding them to an integer showed
// a 0.3 ms P50 as "0 ms". Matches the CLI's inspect timings ("<0.1 ms", one decimal).
export const fmtLatencyMs = (v: number | null | undefined): string => {
  const n = num(v)
  if (n == null) return '—'
  if (n < 0.1) return '<0.1'
  if (n < 10) return n.toFixed(1)
  return Math.round(n).toLocaleString()
}

export const fmtPValue = (v: number | null | undefined): string => {
  const n = num(v)
  return n == null ? '—' : n.toFixed(3)
}

export const fmtPct = (v: number | null | undefined): string => {
  const n = num(v)
  return n == null ? '—' : `${n.toFixed(1)}%`
}

export const fmtCost = (v: number | null | undefined): string => {
  const n = num(v)
  return n == null ? '—' : `$${n.toFixed(2)}`
}
