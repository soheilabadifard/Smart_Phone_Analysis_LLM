import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import AnalyticsView from '../src/views/AnalyticsView.jsx'

const RESPONSES = {
  'brand-summary': [{ brand: 'Apple', device_count: 5, avg_price_eur: 800, first_year: 2020, last_year: 2024 }],
  'annual-launches': [{ year: 2023, launches: 10, avg_price_eur: 600, avg_battery_mah: 4500, avg_ram_gb: 8, avg_storage_gb: 128 }],
  'chipset-popularity': [{ chipset_manufacturer: 'Qualcomm', device_count: 100 }],
  'ram-distribution': [{ ram_gb: 8, device_count: 50 }],
  'price-vs-battery': [{ brand: 'Apple', price_eur: 799, battery_mah: 3349, ram_gb: 6, year: 2023 }],
  'network-technology': [
    { generation: '2G', device_count: 7000, pct: 95 },
    { generation: '3G', device_count: 6500, pct: 88 },
    { generation: '4G', device_count: 5500, pct: 75 },
    { generation: '5G', device_count: 1500, pct: 20 },
  ],
  'sim-type-distribution': [{ sim_type: 'nano', device_count: 5000 }, { sim_type: 'micro', device_count: 1000 }],
  'top-android-versions': [{ os_version: '13', device_count: 478 }, { os_version: '12', device_count: 571 }],
  'top-expensive-phones': [{ brand: 'Apple', model: 'iPhone X Pro', year: 2024, price_eur: 1599, os_name: 'iOS', os_version: '18' }],
  'ppi-trend': [
    { brand: 'Apple', year: 2020, avg_ppi: 460, device_count: 5 },
    { brand: 'Samsung', year: 2020, avg_ppi: 510, device_count: 8 },
  ],
  'correlation-matrix': { columns: ['weight', 'price_eur'], matrix: [[1.0, 0.4], [0.4, 1.0]] },
  'quantitative-distributions': { weight: [170, 180, 190], price_eur: [500, 700, 900] },
  'price-ci-2023': [
    { brand: 'Apple', n: 12, mean: 1200, std: 200, lower: 1100, upper: 1300, alpha: 0.02 },
    { brand: 'Samsung', n: 30, mean: 800, std: 150, lower: 750, upper: 850, alpha: 0.02 },
    { brand: 'Huawei', n: 0, mean: null, std: null, lower: null, upper: null, alpha: 0.02 },
    { brand: 'Xiaomi', n: 25, mean: 350, std: 100, lower: 320, upper: 380, alpha: 0.02 },
    { brand: 'Nokia', n: 8, mean: 250, std: 60, lower: 220, upper: 280, alpha: 0.02 },
  ],
  'ht-price-by-sim-and-size': {
    name: 'Price differs by SIM type and device size?',
    description: 'Two-way ANOVA',
    test: 'two-way ANOVA',
    p_value: 0.001,
    alpha: 0.05,
    conclusion: 'reject H0 at α=0.05',
    anova: [{ factor: 'C(sim_type)', sum_sq: 1000, df: 2, F: 5.0, p_value: 0.01 }],
    groups: [{ sim_type: 'nano', size: 'small', n: 100, mean: 500, std: 100, median: 480, values: [450, 500, 520] }],
  },
  'ht-ppi-by-size': {
    name: 'PPI differs between small and large devices?',
    description: 't-test',
    test: 'Welch t-test',
    p_value: 0.04,
    alpha: 0.05,
    conclusion: 'reject H0 at α=0.05',
    groups: [{ size: 'small', n: 100, mean: 400, std: 50, median: 405, values: [400, 410] }, { size: 'large', n: 50, mean: 300, std: 40, median: 295, values: [300, 295] }],
  },
  'ht-weight-android-vs-ios': {
    name: 'Weight Android vs iOS',
    description: 't-test',
    test: 'Welch t-test',
    p_value: 0.2,
    alpha: 0.05,
    conclusion: 'fail to reject H0 at α=0.05',
    groups: [{ os_name: 'Android', n: 100, mean: 180, std: 20, median: 178, values: [180] }, { os_name: 'iOS', n: 50, mean: 175, std: 15, median: 174, values: [175] }],
  },
  'ht-battery-by-brand-and-size': {
    name: 'Battery by brand × size',
    description: 'ANOVA',
    test: 'two-way ANOVA',
    p_value: 0.005,
    alpha: 0.05,
    conclusion: 'reject H0 at α=0.05',
    anova: [{ factor: 'C(brand)', sum_sq: 5000, df: 2, F: 8.0, p_value: 0.005 }],
    groups: [{ brand: 'Samsung', size: 'small', n: 50, mean: 4000, std: 500, median: 4000, values: [4000] }],
  },
  'ht-price-by-brand-and-size': {
    name: 'Price by brand × size',
    description: 'ANOVA',
    test: 'two-way ANOVA',
    p_value: 0.0001,
    alpha: 0.05,
    conclusion: 'reject H0 at α=0.05',
    anova: [{ factor: 'C(brand)', sum_sq: 10000, df: 2, F: 15.0, p_value: 0.0001 }],
    groups: [{ brand: 'Apple', size: 'small', n: 30, mean: 1000, std: 100, median: 999, values: [1000] }],
  },
  'ht-weight-by-size': {
    name: 'Weight by size',
    description: 'Mann-Whitney U',
    test: 'Mann-Whitney U',
    p_value: 0.0,
    alpha: 0.05,
    conclusion: 'reject H0 at α=0.05',
    groups: [{ size: 'small', n: 100, mean: 180, std: 20, median: 178, values: [180] }, { size: 'large', n: 50, mean: 500, std: 100, median: 490, values: [500] }],
  },
  'ht-battery-by-cpu': {
    name: 'Battery by CPU cores', description: 'one-way ANOVA', test: 'one-way ANOVA',
    p_value: 0.0, alpha: 0.05, conclusion: 'reject H0 at α=0.05',
    anova: [{ factor: 'C(cpu_core_count)', sum_sq: 1e9, df: 5, F: 100, p_value: 0 }],
    groups: [{ cpu_core_count: 8, n: 200, mean: 4500, std: 500, median: 4500, values: [4500] }],
  },
  'ht-price-by-chipset': {
    name: 'Price by chipset', description: 'one-way ANOVA', test: 'one-way ANOVA',
    p_value: 0.0, alpha: 0.05, conclusion: 'reject H0 at α=0.05',
    anova: [{ factor: 'C(chipset_manufacturer)', sum_sq: 1e7, df: 5, F: 80, p_value: 0 }],
    groups: [{ chipset_manufacturer: 'Apple', n: 100, mean: 1000, std: 200, median: 999, values: [1000] }],
  },
  'ht-price-by-main-camera': {
    name: 'Price by camera count', description: 'one-way ANOVA', test: 'one-way ANOVA',
    p_value: 0.0, alpha: 0.05, conclusion: 'reject H0 at α=0.05',
    anova: [{ factor: 'C(main_cameras_num)', sum_sq: 1e7, df: 4, F: 90, p_value: 0 }],
    groups: [{ main_cameras_num: 3, n: 100, mean: 800, std: 200, median: 790, values: [800] }],
  },
  'price-regression-specs': {
    name: 'Price ~ physical specs (multivariate OLS)',
    description: 'OLS on six numeric specs',
    n: 5886, r_squared: 0.406, adj_r_squared: 0.405,
    f_statistic: 669.0, f_p_value: 0,
    coefficients: [
      { name: 'Intercept', coef: -100.5, std_err: 50.2, t: -2.0, p_value: 0.04 },
      { name: 'battery_mah', coef: 0.05, std_err: 0.005, t: 10.0, p_value: 0.001 },
    ],
  },
  'price-regression-os': {
    name: 'Price ~ OS (categorical OLS)',
    description: 'Per-OS price intercept',
    n: 6057, r_squared: 0.119, adj_r_squared: 0.118,
    f_statistic: 67.7, f_p_value: 1.4e-155,
    coefficients: [
      { name: 'Intercept', coef: 200.0, std_err: 10.0, t: 20.0, p_value: 0 },
      { name: 'C(os_name)[T.iOS]', coef: 700.0, std_err: 25.0, t: 28.0, p_value: 0 },
    ],
  },
}

function payloadFor(url) {
  for (const key of Object.keys(RESPONSES)) {
    if (url.includes(key)) return RESPONSES[key]
  }
  return []
}

describe('AnalyticsView', () => {
  beforeEach(() => {
    global.fetch = vi.fn(async (url) => ({
      ok: true,
      status: 200,
      json: async () => payloadFor(url),
    }))
  })

  it('renders all chart cards once fetches resolve', async () => {
    render(<AnalyticsView />)
    await waitFor(() => {
      // Plotly mock is rendered for each <Plot> instance — section 1 (5) +
      // section 2 distributions/rankings (6 chart blocks but the histogram
      // grid is 12 internal Plot instances) + section 3 (CI bar + 6 HT box
      // plots). At minimum the section titles render — that's the contract.
      expect(screen.getAllByTestId('mock-plot').length).toBeGreaterThan(10)
    })
  })

  it('renders titles for all three sections', async () => {
    render(<AnalyticsView />)
    await waitFor(() => screen.getByText(/Top brands by catalogue size/i))

    // Section 1
    expect(screen.getByText(/Annual launches/i)).toBeInTheDocument()
    expect(screen.getByText(/Price vs battery/i)).toBeInTheDocument()
    expect(screen.getByText(/Top chipset manufacturers/i)).toBeInTheDocument()
    expect(screen.getByText(/RAM distribution/i)).toBeInTheDocument()

    // Section 2
    expect(screen.getByText(/Network generations/i)).toBeInTheDocument()
    expect(screen.getByText(/SIM-type distribution/i)).toBeInTheDocument()
    expect(screen.getByText(/Top 10 Android versions/i)).toBeInTheDocument()
    expect(screen.getByText(/PPI density trend/i)).toBeInTheDocument()
    expect(screen.getByText(/50 most expensive/i)).toBeInTheDocument()
    expect(screen.getByText(/Correlation matrix/i)).toBeInTheDocument()
    expect(screen.getByText(/quantitative columns/i)).toBeInTheDocument()

    // Section 3
    expect(screen.getByText(/2023 average price by brand/i)).toBeInTheDocument()
    expect(screen.getByText(/Hypothesis tests/i)).toBeInTheDocument()

    // Section 4
    expect(screen.getByText(/Regression models/i)).toBeInTheDocument()
    expect(screen.getByText(/Price ~ physical specs/i)).toBeInTheDocument()
    expect(screen.getByText(/Price ~ OS/i)).toBeInTheDocument()
  })

  it('renders OLS regression tables with R² and coefficient rows', async () => {
    render(<AnalyticsView />)
    // R² value from price-regression-specs mock
    await waitFor(() => screen.getByText(/0\.406/i))
    // The OS dummy term from price-regression-os
    expect(screen.getByText(/C\(os_name\)\[T\.iOS\]/i)).toBeInTheDocument()
  })

  it('renders hypothesis-test panels with conclusion text', async () => {
    render(<AnalyticsView />)
    await waitFor(() => screen.getByText(/Price differs by SIM type/i))
    // Each test should render its own name from the response. Use getAllByText
    // because conclusion text 'reject H0 at α=0.05' appears across multiple
    // panels.
    const rejects = screen.getAllByText(/reject H0/i)
    expect(rejects.length).toBeGreaterThan(0)
  })

  it('renders top-expensive table rows', async () => {
    render(<AnalyticsView />)
    await waitFor(() => screen.getByText(/iPhone X Pro/i))
    expect(screen.getByText(/iPhone X Pro/i)).toBeInTheDocument()
  })
})
