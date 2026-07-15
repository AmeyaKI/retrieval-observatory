import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test } from 'vitest'
import Sparkline from './Sparkline'

describe('Sparkline', () => {
  test('renders nothing for fewer than two points', () => {
    expect(renderToStaticMarkup(<Sparkline data={[1]} />)).toBe('')
    expect(renderToStaticMarkup(<Sparkline data={[]} />)).toBe('')
  })

  test('renders a chart container for numeric data', () => {
    const html = renderToStaticMarkup(<Sparkline data={[1, 3, 2, 5, 4]} />)
    expect(html).toContain('recharts-responsive-container')
  })

  test('accepts {value} object data', () => {
    const html = renderToStaticMarkup(
      <Sparkline data={[{ value: 1 }, { value: 2 }, { value: 3 }]} />,
    )
    expect(html).toContain('recharts-responsive-container')
  })
})
