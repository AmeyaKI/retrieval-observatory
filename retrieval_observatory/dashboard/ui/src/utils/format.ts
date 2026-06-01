function num(v: number | null | undefined): number | null {
  if (v == null || Number.isNaN(v)) return null
  return v
}

export const fmtQuality = (v: number | null | undefined): string => {
  const n = num(v)
  return n == null ? '—' : n.toFixed(3)
}

export const fmtLatencyMs = (v: number | null | undefined): string => {
  const n = num(v)
  return n == null ? '—' : Math.round(n).toLocaleString()
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
