import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import AnalyticsView from '../src/views/AnalyticsView.jsx'

describe('AnalyticsView', () => {
  beforeEach(() => {
    global.fetch = vi.fn(async (url) => {
      const payload = url.includes('brand-summary')
        ? [{ brand: 'Apple', device_count: 5, avg_price_eur: 800, first_year: 2020, last_year: 2024 }]
        : url.includes('annual-launches')
          ? [{ year: 2023, launches: 10, avg_price_eur: 600, avg_battery_mah: 4500, avg_ram_gb: 8, avg_storage_gb: 128 }]
          : url.includes('chipset-popularity')
            ? [{ chipset_manufacturer: 'Qualcomm', device_count: 100 }]
            : url.includes('ram-distribution')
              ? [{ ram_gb: 8, device_count: 50 }]
              : url.includes('price-vs-battery')
                ? [{ brand: 'Apple', price_eur: 799, battery_mah: 3349, ram_gb: 6, year: 2023 }]
                : []
      return { ok: true, status: 200, json: async () => payload }
    })
  })

  it('renders all five chart cards once fetches resolve', async () => {
    render(<AnalyticsView />)
    await waitFor(() => {
      expect(screen.getAllByTestId('mock-plot').length).toBe(5)
    })
  })

  it('renders chart titles', async () => {
    render(<AnalyticsView />)
    await waitFor(() => screen.getByText(/Top brands by catalogue size/i))
    expect(screen.getByText(/Annual launches/i)).toBeInTheDocument()
    expect(screen.getByText(/Price vs battery/i)).toBeInTheDocument()
    expect(screen.getByText(/Top chipset manufacturers/i)).toBeInTheDocument()
    expect(screen.getByText(/RAM distribution/i)).toBeInTheDocument()
  })
})
