import { describe, expect, it } from 'vitest'
import { fmtLatencyMs } from './format'

describe('fmtLatencyMs', () => {
  it('shows sub-millisecond latency instead of rounding it to 0', () => {
    expect(fmtLatencyMs(0.3)).toBe('0.3')
    expect(fmtLatencyMs(0.04)).toBe('<0.1')
    expect(fmtLatencyMs(0)).toBe('<0.1')
  })

  it('keeps one decimal under 10 ms and whole milliseconds above', () => {
    expect(fmtLatencyMs(7.25)).toBe('7.3')
    expect(fmtLatencyMs(12.6)).toBe('13')
    expect(fmtLatencyMs(1234.4)).toBe((1234).toLocaleString())
  })

  it('marks a missing value', () => {
    expect(fmtLatencyMs(null)).toBe('—')
    expect(fmtLatencyMs(undefined)).toBe('—')
    expect(fmtLatencyMs(Number.NaN)).toBe('—')
  })
})
