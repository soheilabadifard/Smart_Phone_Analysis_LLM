import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import RecommendView from '../src/views/RecommendView.jsx'

const samplePhone = {
  device_id: 1,
  brand: 'Apple',
  model: 'iPhone 15',
  year: 2023,
  form_factor: 'phone',
  price_eur: 799,
  ram_gb: 6,
  storage_gb: 128,
  battery_mah: 3349,
  display_inch: 6.1,
  os: 'iOS',
  chipset: 'Apple',
  network: 'GSM / HSPA / LTE / 5G',
}

function mockFetch(routes) {
  return vi.fn(async (url, init) => {
    for (const [pattern, payload] of Object.entries(routes)) {
      if (url.includes(pattern)) {
        return {
          ok: true,
          status: 200,
          json: async () => payload,
          text: async () => JSON.stringify(payload),
        }
      }
    }
    throw new Error(`Unmocked fetch: ${url}`)
  })
}

describe('RecommendView', () => {
  beforeEach(() => {
    global.fetch = mockFetch({
      '/api/recommend/brands': ['Apple', 'Samsung'],
      '/api/recommend/os': ['iOS', 'Android'],
      '/api/recommend': [samplePhone],
    })
  })

  it('loads brands and OS options on mount', async () => {
    render(<RecommendView />)
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'Apple' })).toBeInTheDocument()
    })
    expect(screen.getByRole('option', { name: 'iOS' })).toBeInTheDocument()
  })

  it('submits filter form and renders results table', async () => {
    const user = userEvent.setup()
    render(<RecommendView />)

    await waitFor(() => screen.getByRole('option', { name: 'Apple' }))
    await user.click(screen.getByRole('button', { name: /find phones/i }))

    await waitFor(() => {
      expect(screen.getByText('iPhone 15')).toBeInTheDocument()
    })
    // "Apple" appears both in the brand <option> and the result <td>; the
    // model name is unique to the result row, so we assert it directly.
    expect(screen.getByRole('cell', { name: 'iPhone 15' })).toBeInTheDocument()
    expect(screen.getByText(/1 result/)).toBeInTheDocument()
  })

  it('shows error banner on backend failure', async () => {
    global.fetch = vi.fn(async (url) => {
      if (url.includes('/api/recommend/brands')) {
        return { ok: true, status: 200, json: async () => [] }
      }
      if (url.includes('/api/recommend/os')) {
        return { ok: true, status: 200, json: async () => [] }
      }
      return {
        ok: false,
        status: 500,
        text: async () => 'boom',
        json: async () => ({}),
      }
    })

    const user = userEvent.setup()
    render(<RecommendView />)
    await user.click(screen.getByRole('button', { name: /find phones/i }))

    await waitFor(() => {
      expect(screen.getByText(/boom/i)).toBeInTheDocument()
    })
  })
})
