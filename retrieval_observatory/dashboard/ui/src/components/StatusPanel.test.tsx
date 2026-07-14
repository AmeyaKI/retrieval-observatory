import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test } from 'vitest'
import StatusPanel, { StatusKind } from './StatusPanel'

describe('StatusPanel', () => {
  test.each<StatusKind>(['loading', 'empty', 'partial', 'error', 'invalid', 'unavailable'])(
    'renders an explicit, non-color %s state',
    (kind) => {
      const html = renderToStaticMarkup(<StatusPanel kind={kind} message={`${kind} details`} />)
      expect(html).toContain(`data-state="${kind}"`)
      expect(html).toContain(`${kind} details`)
      expect(html).toMatch(/role="(status|alert)"/)
      expect(html).toContain('aria-hidden="true"')
    },
  )

  test('uses alert semantics for decision-blocking states', () => {
    expect(renderToStaticMarkup(<StatusPanel kind="error" message="failed" />)).toContain('role="alert"')
    expect(renderToStaticMarkup(<StatusPanel kind="invalid" message="blocked" />)).toContain('role="alert"')
  })
})
