import { describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import RecommendView from '../src/views/RecommendView.jsx'
import AskView from '../src/views/AskView.jsx'
import AnalyticsView from '../src/views/AnalyticsView.jsx'

// ---------------------------------------------------------------------------
// Loading states
// ---------------------------------------------------------------------------

describe('Loading state', () => {
  it('Recommend submit button shows "Searching…" during fetch', async () => {
    let resolveResults
    global.fetch = vi.fn(async (url) => {
      if (url.includes('/api/recommend/brands') || url.includes('/api/recommend/os')) {
        return { ok: true, status: 200, json: async () => [] }
      }
      // Hold the recommend POST open
      return new Promise((resolve) => {
        resolveResults = () =>
          resolve({
            ok: true,
            status: 200,
            json: async () => [],
            text: async () => '[]',
          })
      })
    })

    const user = userEvent.setup()
    render(<RecommendView />)
    await user.click(screen.getByRole('button', { name: /find phones/i }))

    // While the fetch hangs, button should show "Searching…" and be disabled
    const button = await screen.findByRole('button', { name: /searching/i })
    expect(button).toBeDisabled()

    await act(async () => {
      resolveResults()
    })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /find phones/i })).toBeInTheDocument()
    })
  })

  it('Ask submit button shows "Thinking…" during fetch', async () => {
    let resolveAnswer
    global.fetch = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveAnswer = () =>
            resolve({
              ok: true,
              status: 200,
              text: async () =>
                JSON.stringify({
                  question: 'q',
                  sql: 'SELECT 1',
                  columns: ['x'],
                  rows: [{ x: 1 }],
                  attempts: [{ sql: 'SELECT 1', error: null, succeeded: true }],
                  raw_llm_response: '',
                }),
            })
        }),
    )

    const user = userEvent.setup()
    render(<AskView />)
    await user.type(screen.getByPlaceholderText(/Xiaomi/i), 'q')
    await user.click(screen.getByRole('button', { name: /^ask$/i }))

    const button = await screen.findByRole('button', { name: /thinking/i })
    expect(button).toBeDisabled()

    await act(async () => {
      resolveAnswer()
    })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^ask$/i })).toBeInTheDocument()
    })
  })
})


// ---------------------------------------------------------------------------
// Empty / zero-result states
// ---------------------------------------------------------------------------

describe('Empty result states', () => {
  it('Ask renders "No rows." when result is empty', async () => {
    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          question: 'no matches',
          sql: 'SELECT 1 WHERE 0',
          columns: [],
          rows: [],
          attempts: [{ sql: 'SELECT 1 WHERE 0', error: null, succeeded: true }],
          raw_llm_response: '',
        }),
    }))

    const user = userEvent.setup()
    render(<AskView />)
    await user.type(screen.getByPlaceholderText(/Xiaomi/i), 'no matches')
    await user.click(screen.getByRole('button', { name: /^ask$/i }))

    await waitFor(() => {
      expect(screen.getByText(/no rows\./i)).toBeInTheDocument()
    })
  })

  it('Recommend with zero results does not render the result table', async () => {
    global.fetch = vi.fn(async (url) => {
      if (url.includes('/api/recommend/brands') || url.includes('/api/recommend/os')) {
        return { ok: true, status: 200, json: async () => [] }
      }
      return { ok: true, status: 200, json: async () => [] }
    })

    const user = userEvent.setup()
    render(<RecommendView />)
    await user.click(screen.getByRole('button', { name: /find phones/i }))

    // No `1 result` / `2 results` indicator and no <table> in document
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /find phones/i })).not.toBeDisabled()
    })
    expect(screen.queryByText(/result(s)?$/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})


// ---------------------------------------------------------------------------
// Suggestion pills (Ask)
// ---------------------------------------------------------------------------

describe('Ask suggestions', () => {
  it('clicking a suggestion populates the input', async () => {
    const user = userEvent.setup()
    render(<AskView />)
    const pill = screen.getByText(/highest average phone price/i)
    await user.click(pill)
    const input = screen.getByPlaceholderText(/Xiaomi/i)
    expect(input).toHaveValue(
      expect.stringContaining('highest average phone price') === undefined
        ? 'Which 5 brands have the highest average phone price?'
        : input.value,
    )
    // Plain assertion as a fallback (toHaveValue with expect.stringContaining
    // is flaky across testing-library versions):
    expect(input.value).toMatch(/highest average phone price/i)
  })
})


// ---------------------------------------------------------------------------
// Analytics: Plotly trace counts (verifies the right chart shape)
// ---------------------------------------------------------------------------

describe('Analytics chart shapes', () => {
  it('annual launches chart renders 3 traces (bar + 2 lines)', async () => {
    global.fetch = vi.fn(async (url) => {
      const annualPayload = [
        { year: 2023, launches: 10, avg_price_eur: 600, avg_battery_mah: 4500, avg_ram_gb: 8, avg_storage_gb: 128 },
      ]
      const ramPayload = [{ ram_gb: 8, device_count: 50 }]
      const chipsetPayload = [{ chipset_manufacturer: 'Qualcomm', device_count: 100 }]
      const brandPayload = [
        { brand: 'Apple', device_count: 5, avg_price_eur: 800, first_year: 2020, last_year: 2024 },
      ]
      const scatterPayload = [
        { brand: 'Apple', price_eur: 799, battery_mah: 3349, ram_gb: 6, year: 2023 },
      ]

      if (url.includes('annual-launches')) return { ok: true, json: async () => annualPayload }
      if (url.includes('brand-summary')) return { ok: true, json: async () => brandPayload }
      if (url.includes('chipset-popularity')) return { ok: true, json: async () => chipsetPayload }
      if (url.includes('ram-distribution')) return { ok: true, json: async () => ramPayload }
      if (url.includes('price-vs-battery')) return { ok: true, json: async () => scatterPayload }
      return { ok: true, json: async () => [] }
    })

    render(<AnalyticsView />)
    const plots = await screen.findAllByTestId('mock-plot')
    expect(plots.length).toBe(5)

    // The annual-launches plot is the second card (after brand-summary)
    // and is built with 3 traces: launches bar + price line + battery line.
    const annualPlot = plots[1]
    expect(annualPlot).toHaveAttribute('data-trace-count', '3')
  })
})
