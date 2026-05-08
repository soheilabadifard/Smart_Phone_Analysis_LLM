import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

beforeEach(() => {
  // Default fetch stub — returns an empty 200 response so views that fetch
  // on mount (e.g. RecommendView) don't blow up with "Failed to parse URL"
  // when a test renders them without explicitly mocking fetch.
  // Individual tests can override by reassigning `global.fetch`.
  global.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => [],
    text: async () => '[]',
  }))
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// Mock react-plotly.js globally — Plotly is heavy and not what we're testing
vi.mock('react-plotly.js', () => ({
  default: ({ data, layout }) => {
    const traceCount = Array.isArray(data) ? data.length : 0
    return (
      <div
        data-testid="mock-plot"
        data-trace-count={traceCount}
        data-layout-height={layout?.height ?? ''}
      />
    )
  },
}))
