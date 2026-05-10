import { useEffect, useState } from 'react'
import Plot from 'react-plotly.js'

import { humanizeColumnName } from '../utils/format.js'

const PLOTLY_LAYOUT = {
  paper_bgcolor: '#161a21',
  plot_bgcolor: '#161a21',
  font: { color: '#e6e8eb' },
  margin: { t: 40, r: 20, b: 50, l: 60 },
  hovermode: 'closest',
}

const PLOTLY_CONFIG = { displaylogo: false, responsive: true }

function useEndpoint(path) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    fetch(path)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then(setData)
      .catch((e) => setError(String(e)))
  }, [path])
  return { data, error }
}

function ChartCard({ title, subtitle, children }) {
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>{title}</h3>
      {subtitle && <p style={{ marginTop: '-0.5rem', color: '#9aa0a6', fontSize: '0.9em' }}>{subtitle}</p>}
      {children}
    </div>
  )
}

function fmt(n, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits })
}

function HistogramGrid({ data }) {
  // data: { columnName: [v1, v2, ...] }
  const cols = Object.keys(data)
  const cells = cols.map((col) => (
    <Plot
      key={col}
      data={[{ type: 'histogram', x: data[col], marker: { color: '#6aa9ff' }, opacity: 0.85 }]}
      layout={{ ...PLOTLY_LAYOUT, height: 220, title: { text: humanizeColumnName(col), font: { size: 13 } }, margin: { t: 30, r: 10, b: 30, l: 40 } }}
      config={PLOTLY_CONFIG}
      style={{ width: '100%' }}
    />
  ))
  return <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem' }}>{cells}</div>
}

function RegressionTable({ data }) {
  if (!data) return null
  if (data.error) {
    return <div style={{ color: '#ff7e7e' }}>Could not fit model: {data.error}</div>
  }
  if (!Array.isArray(data.coefficients)) {
    // Defensive: API contract is { coefficients: [...] } but tests / partial
    // responses may not match. Render nothing rather than crash.
    return null
  }
  return (
    <div>
      <div style={{ color: '#9aa0a6', fontSize: '0.9em', marginBottom: '0.5rem' }}>{data.description}</div>
      <div style={{ display: 'flex', gap: '1.25rem', flexWrap: 'wrap', fontSize: '0.95em', marginBottom: '0.5rem' }}>
        <span><b>n:</b> {fmt(data.n, 0)}</span>
        <span><b>R²:</b> {fmt(data.r_squared, 3)}</span>
        <span><b>Adj R²:</b> {fmt(data.adj_r_squared, 3)}</span>
        <span><b>F:</b> {fmt(data.f_statistic, 2)} (p = {fmt(data.f_p_value, 4)})</span>
      </div>
      <table style={{ fontSize: '0.92em' }}>
        <thead>
          <tr><th>Variable</th><th>Coef</th><th>Std err</th><th>t</th><th>p-value</th></tr>
        </thead>
        <tbody>
          {data.coefficients.map((c) => (
            <tr key={c.name}>
              <td>{c.name}</td>
              <td>{fmt(c.coef, 4)}</td>
              <td>{fmt(c.std_err, 4)}</td>
              <td>{fmt(c.t, 3)}</td>
              <td style={{ color: c.p_value !== null && c.p_value < 0.05 ? '#9bd17a' : '#9aa0a6' }}>{fmt(c.p_value, 4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ResidualDiagnosticsPanel({ data }) {
  if (!data) return null
  if (data.error) {
    return <div style={{ color: '#ff7e7e' }}>Could not fit model: {data.error}</div>
  }
  // Defensive: required fields may be missing if the mock/response is partial.
  if (!Array.isArray(data.sample_residuals) || !Array.isArray(data.qq_plot) || !Array.isArray(data.vif)) {
    return null
  }
  const bp = data.breusch_pagan || {}
  const jb = data.jarque_bera || {}
  return (
    <div>
      <div style={{ display: 'flex', gap: '1.25rem', flexWrap: 'wrap', fontSize: '0.95em', marginBottom: '0.75rem' }}>
        <span><b>n:</b> {fmt(data.n, 0)}</span>
        <span><b>R²:</b> {fmt(data.r_squared, 3)}</span>
        <span><b>Mean residual:</b> {fmt(data.mean_residual, 3)}</span>
        <span><b>Std residual:</b> {fmt(data.std_residual, 1)}</span>
        <span><b>Outliers (|z|&gt;3):</b> {data.n_outliers_z3}</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
        <Plot
          data={[{
            type: 'scattergl', mode: 'markers',
            x: data.sample_residuals.map((p) => p.fitted),
            y: data.sample_residuals.map((p) => p.residual),
            marker: { size: 4, color: '#6aa9ff', opacity: 0.5 },
            hovertemplate: 'fitted: %{x:.0f}<br>residual: %{y:.0f}<extra></extra>',
          }, {
            type: 'scatter', mode: 'lines',
            x: [Math.min(...data.sample_residuals.map((p) => p.fitted)), Math.max(...data.sample_residuals.map((p) => p.fitted))],
            y: [0, 0],
            line: { color: '#ff7e7e', dash: 'dash', width: 1 }, showlegend: false,
          }]}
          layout={{
            ...PLOTLY_LAYOUT, height: 320, showlegend: false,
            title: { text: 'Residuals vs fitted', font: { size: 13 } },
            xaxis: { title: 'fitted (€)' }, yaxis: { title: 'residual (€)' },
            margin: { t: 30, r: 10, b: 40, l: 50 },
          }}
          config={PLOTLY_CONFIG} style={{ width: '100%' }}
        />

        <Plot
          data={[{
            type: 'scattergl', mode: 'markers',
            x: data.qq_plot.map((p) => p.theoretical),
            y: data.qq_plot.map((p) => p.sample),
            marker: { size: 4, color: '#5fcd8c', opacity: 0.6 },
            hovertemplate: 'theoretical: %{x:.2f}<br>sample: %{y:.2f}<extra></extra>',
          }, {
            type: 'scatter', mode: 'lines',
            x: [-4, 4], y: [-4, 4],
            line: { color: '#ff7e7e', dash: 'dash', width: 1 }, showlegend: false,
          }]}
          layout={{
            ...PLOTLY_LAYOUT, height: 320, showlegend: false,
            title: { text: 'Normal QQ plot of standardized residuals', font: { size: 13 } },
            xaxis: { title: 'theoretical quantile' }, yaxis: { title: 'sample quantile' },
            margin: { t: 30, r: 10, b: 40, l: 50 },
          }}
          config={PLOTLY_CONFIG} style={{ width: '100%' }}
        />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginTop: '0.75rem' }}>
        <table style={{ fontSize: '0.92em' }}>
          <thead>
            <tr><th colSpan="2">Diagnostic tests</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>Breusch-Pagan (heteroscedasticity)</td>
              <td>p = {fmt(bp.p_value, 4)} {bp.p_value !== null && bp.p_value < 0.05 && <span style={{ color: '#ff7e7e' }}> ← reject homoscedasticity</span>}</td>
            </tr>
            <tr>
              <td>Jarque-Bera (residual normality)</td>
              <td>p = {fmt(jb.p_value, 4)} (skew {fmt(jb.skew, 2)}, kurtosis {fmt(jb.kurtosis, 2)})</td>
            </tr>
          </tbody>
        </table>

        <table style={{ fontSize: '0.9em' }}>
          <thead>
            <tr><th>Predictor</th><th>VIF</th></tr>
          </thead>
          <tbody>
            {data.vif.slice(0, 10).map((v) => (
              <tr key={v.predictor}>
                <td>{v.predictor}</td>
                <td style={{ color: v.vif !== null && v.vif > 10 ? '#ff7e7e' : v.vif !== null && v.vif > 5 ? '#e0c060' : 'inherit' }}>{fmt(v.vif, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function FeatureSelectionPanel({ data }) {
  if (!data) return null
  if (data.error && (!data.history || data.history.length === 0)) {
    return <div style={{ color: '#ff7e7e' }}>Stepwise failed: {data.error}</div>
  }
  if (!Array.isArray(data.history)) return null
  const { history = [], final_features = [], final_formula, final_summary } = data
  return (
    <div>
      <p style={{ marginTop: 0 }}>
        <b>Best model after stepwise:</b> <code style={{ fontSize: '0.9em' }}>{final_formula}</code>
        <br />
        Adj R² = <b>{fmt(final_summary?.adj_r_squared, 3)}</b>, R² = {fmt(final_summary?.r_squared, 3)}, n = {fmt(final_summary?.n, 0)}.
      </p>

      <table style={{ fontSize: '0.9em' }}>
        <thead>
          <tr><th>Step</th><th>Added</th><th>Adj R²</th><th>AIC</th><th>BIC</th></tr>
        </thead>
        <tbody>
          {history.map((row) => (
            <tr key={row.step}>
              <td>{row.step}</td>
              <td><code>{row.added}</code></td>
              <td>{fmt(row.adj_r_squared, 4)}</td>
              <td>{fmt(row.aic, 0)}</td>
              <td>{fmt(row.bic, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginTop: '0.5rem', fontSize: '0.9em', color: '#9aa0a6' }}>
        Selected features (in order added): {final_features.map((f) => <code key={f} style={{ marginRight: '0.4rem' }}>{f}</code>)}
      </div>
    </div>
  )
}

function HypothesisTestPanel({ data }) {
  if (!data) return null
  const { name, description, test, p_value, conclusion, anova, groups } = data
  return (
    <div style={{ borderTop: '1px solid #2a2f38', paddingTop: '0.75rem', marginTop: '0.75rem' }}>
      <strong>{name}</strong>
      <div style={{ color: '#9aa0a6', fontSize: '0.9em', margin: '0.25rem 0' }}>{description}</div>
      <div style={{ display: 'flex', gap: '1.25rem', flexWrap: 'wrap', fontSize: '0.95em' }}>
        <span><b>Test:</b> {test}</span>
        <span><b>p-value:</b> {p_value === null ? '—' : fmt(p_value, 4)}</span>
        <span><b>Conclusion:</b> <span style={{ color: p_value !== null && p_value < 0.05 ? '#ff7e7e' : '#9bd17a' }}>{conclusion}</span></span>
      </div>
      {anova && anova.length > 0 && (
        <table style={{ marginTop: '0.5rem', fontSize: '0.9em' }}>
          <thead>
            <tr><th>Factor</th><th>df</th><th>F</th><th>p</th></tr>
          </thead>
          <tbody>
            {anova.map((row) => (
              <tr key={row.factor}>
                <td>{row.factor}</td>
                <td>{fmt(row.df, 0)}</td>
                <td>{fmt(row.F, 3)}</td>
                <td>{fmt(row.p_value, 4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {groups && groups.length > 0 && (
        <Plot
          data={groups.map((g) => {
            const labelKey = ['os_name', 'sim_type', 'brand', 'size'].find((k) => k in g) || 'group'
            const labelParts = []
            if (g.brand) labelParts.push(g.brand)
            if (g.os_name) labelParts.push(g.os_name)
            if (g.sim_type) labelParts.push(g.sim_type)
            if (g.size) labelParts.push(g.size)
            const label = labelParts.join(' / ') || g[labelKey] || 'group'
            return { type: 'box', name: label, y: g.values, boxpoints: 'suspectedoutliers' }
          })}
          layout={{ ...PLOTLY_LAYOUT, height: 320, margin: { t: 20, r: 10, b: 50, l: 50 }, showlegend: false }}
          config={PLOTLY_CONFIG}
          style={{ width: '100%' }}
        />
      )}
    </div>
  )
}

export default function AnalyticsView() {
  // Section 1 — existing R-style summaries
  const brand = useEndpoint('/api/analytics/brand-summary')
  const annual = useEndpoint('/api/analytics/annual-launches')
  const chipset = useEndpoint('/api/analytics/chipset-popularity')
  const ram = useEndpoint('/api/analytics/ram-distribution')
  const scatter = useEndpoint('/api/analytics/price-vs-battery')

  // Section 2 — distributions, rankings, trends (Q1-Q8)
  const network = useEndpoint('/api/analytics/network-technology')
  const simType = useEndpoint('/api/analytics/sim-type-distribution')
  const androidVer = useEndpoint('/api/analytics/top-android-versions')
  const topExpensive = useEndpoint('/api/analytics/top-expensive-phones')
  const ppiTrend = useEndpoint('/api/analytics/ppi-trend')
  const corr = useEndpoint('/api/analytics/correlation-matrix')
  const quant = useEndpoint('/api/analytics/quantitative-distributions')

  // Section 3 — inferential stats (Estimation + HT1-HT6)
  const priceCi = useEndpoint('/api/analytics/price-ci-2023')
  const ht1 = useEndpoint('/api/analytics/ht-price-by-sim-and-size')
  const ht2 = useEndpoint('/api/analytics/ht-ppi-by-size')
  const ht3 = useEndpoint('/api/analytics/ht-weight-android-vs-ios')
  const ht4 = useEndpoint('/api/analytics/ht-battery-by-brand-and-size')
  const ht5 = useEndpoint('/api/analytics/ht-price-by-brand-and-size')
  const ht6 = useEndpoint('/api/analytics/ht-weight-by-size')
  const ht7 = useEndpoint('/api/analytics/ht-battery-by-cpu')
  const ht8 = useEndpoint('/api/analytics/ht-price-by-chipset')
  const ht9 = useEndpoint('/api/analytics/ht-price-by-main-camera')

  // Section 4 — OLS regression models (notebook cells 18, 74)
  const olsSpecs = useEndpoint('/api/analytics/price-regression-specs')
  const olsOs = useEndpoint('/api/analytics/price-regression-os')
  const olsFull = useEndpoint('/api/analytics/price-regression-full')

  // Section 5 — residuals + feature selection
  const residuals = useEndpoint('/api/analytics/price-residuals?model=full')
  const featureSel = useEndpoint('/api/analytics/price-feature-selection')

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Catalogue overview</h2>
      <ChartCard title="Top brands by catalogue size (avg price colored)">
        {brand.data && (
          <Plot
            data={[{
              type: 'bar',
              x: brand.data.map((d) => d.brand),
              y: brand.data.map((d) => d.device_count),
              marker: {
                color: brand.data.map((d) => d.avg_price_eur),
                colorscale: 'Viridis',
                colorbar: { title: 'avg €' },
              },
              hovertemplate: '%{x}<br>devices: %{y}<br>avg €%{marker.color:.0f}<extra></extra>',
            }]}
            layout={{ ...PLOTLY_LAYOUT, height: 420, xaxis: { tickangle: -40 } }}
            config={PLOTLY_CONFIG}
            style={{ width: '100%' }}
          />
        )}
      </ChartCard>

      <ChartCard title="Annual launches and average specs">
        {annual.data && (
          <Plot
            data={[
              { type: 'bar', name: 'launches', x: annual.data.map((d) => d.year), y: annual.data.map((d) => d.launches), yaxis: 'y' },
              { type: 'scatter', mode: 'lines+markers', name: 'avg price (€)', x: annual.data.map((d) => d.year), y: annual.data.map((d) => d.avg_price_eur), yaxis: 'y2' },
              { type: 'scatter', mode: 'lines+markers', name: 'avg battery (mAh)', x: annual.data.map((d) => d.year), y: annual.data.map((d) => d.avg_battery_mah), yaxis: 'y3', visible: 'legendonly' },
            ]}
            layout={{
              ...PLOTLY_LAYOUT, height: 460,
              yaxis: { title: 'launches' },
              yaxis2: { title: 'avg €', overlaying: 'y', side: 'right' },
              yaxis3: { title: 'mAh', overlaying: 'y', side: 'right', position: 0.92, anchor: 'free' },
              legend: { orientation: 'h', y: -0.2 },
            }}
            config={PLOTLY_CONFIG}
            style={{ width: '100%' }}
          />
        )}
      </ChartCard>

      <ChartCard title="Price vs battery (each point = one device)">
        {scatter.data && (
          <Plot
            data={[{
              type: 'scattergl',
              mode: 'markers',
              x: scatter.data.map((d) => d.battery_mah),
              y: scatter.data.map((d) => d.price_eur),
              text: scatter.data.map((d) => `${d.brand} (${d.year})`),
              marker: {
                size: 6,
                color: scatter.data.map((d) => d.year),
                colorscale: 'Plasma',
                colorbar: { title: 'year' },
                opacity: 0.7,
              },
              hovertemplate: '%{text}<br>battery: %{x} mAh<br>price: €%{y}<extra></extra>',
            }]}
            layout={{ ...PLOTLY_LAYOUT, height: 460, xaxis: { title: 'battery (mAh)' }, yaxis: { title: 'price (€)' } }}
            config={PLOTLY_CONFIG}
            style={{ width: '100%' }}
          />
        )}
      </ChartCard>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
        <ChartCard title="Top chipset manufacturers">
          {chipset.data && (
            <Plot
              data={[{
                type: 'pie',
                labels: chipset.data.map((d) => d.chipset_manufacturer),
                values: chipset.data.map((d) => d.device_count),
                hole: 0.4,
                textinfo: 'label+percent',
              }]}
              layout={{ ...PLOTLY_LAYOUT, height: 380, showlegend: false }}
              config={PLOTLY_CONFIG}
              style={{ width: '100%' }}
            />
          )}
        </ChartCard>

        <ChartCard title="RAM distribution">
          {ram.data && (
            <Plot
              data={[{
                type: 'bar',
                x: ram.data.map((d) => `${d.ram_gb} GB`),
                y: ram.data.map((d) => d.device_count),
                marker: { color: '#6aa9ff' },
              }]}
              layout={{ ...PLOTLY_LAYOUT, height: 380 }}
              config={PLOTLY_CONFIG}
              style={{ width: '100%' }}
            />
          )}
        </ChartCard>
      </div>

      <h2>Distributions and rankings</h2>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
        <ChartCard title="Network generations supported"
                   subtitle="A device can support multiple — values do not sum to 100%.">
          {network.data && (
            <Plot
              data={[{
                type: 'bar',
                x: network.data.map((d) => d.generation),
                y: network.data.map((d) => d.pct),
                text: network.data.map((d) => `${d.device_count} (${d.pct}%)`),
                textposition: 'outside',
                marker: { color: ['#7c8ea3', '#6aa9ff', '#5fcd8c', '#ff7e7e'] },
              }]}
              layout={{ ...PLOTLY_LAYOUT, height: 360, yaxis: { title: '% of phones', range: [0, 105] } }}
              config={PLOTLY_CONFIG}
              style={{ width: '100%' }}
            />
          )}
        </ChartCard>

        <ChartCard title="SIM-type distribution">
          {simType.data && (
            <Plot
              data={[{
                type: 'pie',
                labels: simType.data.map((d) => d.sim_type),
                values: simType.data.map((d) => d.device_count),
                hole: 0.4,
                textinfo: 'label+percent',
              }]}
              layout={{ ...PLOTLY_LAYOUT, height: 360, showlegend: false }}
              config={PLOTLY_CONFIG}
              style={{ width: '100%' }}
            />
          )}
        </ChartCard>
      </div>

      <ChartCard title="Top 10 Android versions in the catalogue">
        {androidVer.data && (
          <Plot
            data={[{
              type: 'bar',
              x: androidVer.data.map((d) => d.os_version),
              y: androidVer.data.map((d) => d.device_count),
              marker: { color: '#5fcd8c' },
            }]}
            layout={{ ...PLOTLY_LAYOUT, height: 340, xaxis: { title: 'Android version' }, yaxis: { title: 'devices' } }}
            config={PLOTLY_CONFIG}
            style={{ width: '100%' }}
          />
        )}
      </ChartCard>

      <ChartCard title="PPI density trend (Samsung / Xiaomi / Apple)">
        {ppiTrend.data && (() => {
          const brands = [...new Set(ppiTrend.data.map((d) => d.brand))]
          return (
            <Plot
              data={brands.map((b) => {
                const rows = ppiTrend.data.filter((d) => d.brand === b)
                return {
                  type: 'scatter',
                  mode: 'lines+markers',
                  name: b,
                  x: rows.map((r) => r.year),
                  y: rows.map((r) => r.avg_ppi),
                }
              })}
              layout={{ ...PLOTLY_LAYOUT, height: 380, xaxis: { title: 'year' }, yaxis: { title: 'avg PPI density' } }}
              config={PLOTLY_CONFIG}
              style={{ width: '100%' }}
            />
          )
        })()}
      </ChartCard>

      <ChartCard title="50 most expensive phones">
        {topExpensive.data && (
          <div style={{ maxHeight: 340, overflowY: 'auto' }}>
            <table>
              <thead>
                <tr><th>Brand</th><th>Model</th><th>Year</th><th>Price (€)</th><th>OS</th></tr>
              </thead>
              <tbody>
                {topExpensive.data.map((row, i) => (
                  <tr key={i}>
                    <td>{row.brand}</td>
                    <td>{row.model}</td>
                    <td>{row.year}</td>
                    <td>{fmt(row.price_eur, 0)}</td>
                    <td>{row.os_name ? `${row.os_name}${row.os_version ? ' ' + row.os_version : ''}` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ChartCard>

      <ChartCard title="Correlation matrix (Pearson, phone-only)">
        {corr.data && corr.data.matrix && (
          <Plot
            data={[{
              type: 'heatmap',
              z: corr.data.matrix,
              x: (corr.data.columns || []).map(humanizeColumnName),
              y: (corr.data.columns || []).map(humanizeColumnName),
              zmin: -1, zmax: 1,
              colorscale: 'RdBu', reversescale: true,
              hovertemplate: '%{x} ↔ %{y}<br>r = %{z:.2f}<extra></extra>',
            }]}
            layout={{ ...PLOTLY_LAYOUT, height: 520, xaxis: { tickangle: -40 } }}
            config={PLOTLY_CONFIG}
            style={{ width: '100%' }}
          />
        )}
      </ChartCard>

      <ChartCard title="Distributions of quantitative columns (phone-only)"
                 subtitle="Histograms over all phones.">
        {quant.data && <HistogramGrid data={quant.data} />}
      </ChartCard>

      <h2>Inferential statistics</h2>

      <ChartCard title="2023 average price by brand — 98% confidence interval"
                 subtitle="Apple / Samsung / Huawei / Xiaomi / Nokia. α = 0.02, t-distribution.">
        {priceCi.data && (
          <Plot
            data={[{
              type: 'bar',
              x: priceCi.data.map((d) => d.brand),
              y: priceCi.data.map((d) => d.mean ?? 0),
              error_y: {
                type: 'data',
                symmetric: false,
                array: priceCi.data.map((d) => (d.upper ?? 0) - (d.mean ?? 0)),
                arrayminus: priceCi.data.map((d) => (d.mean ?? 0) - (d.lower ?? 0)),
              },
              marker: { color: '#6aa9ff' },
              text: priceCi.data.map((d) => d.n != null && d.n > 0 ? `n=${d.n}` : 'n=0'),
              textposition: 'outside',
            }]}
            layout={{ ...PLOTLY_LAYOUT, height: 400, yaxis: { title: 'price (€)' } }}
            config={PLOTLY_CONFIG}
            style={{ width: '100%' }}
          />
        )}
      </ChartCard>

      <ChartCard title="Hypothesis tests"
                 subtitle="Each test reports the test statistic, p-value, and a conclusion at α = 0.05.">
        <HypothesisTestPanel data={ht1.data} />
        <HypothesisTestPanel data={ht2.data} />
        <HypothesisTestPanel data={ht3.data} />
        <HypothesisTestPanel data={ht4.data} />
        <HypothesisTestPanel data={ht5.data} />
        <HypothesisTestPanel data={ht6.data} />
        <HypothesisTestPanel data={ht7.data} />
        <HypothesisTestPanel data={ht8.data} />
        <HypothesisTestPanel data={ht9.data} />
      </ChartCard>

      <h2>Regression models</h2>

      <ChartCard title="Price ~ physical specs (OLS)"
                 subtitle="Multivariate regression of price on six numeric specs. Significant coefficients (p &lt; 0.05) shown in green.">
        <RegressionTable data={olsSpecs.data} />
      </ChartCard>

      <ChartCard title="Price ~ OS (OLS, one-hot)"
                 subtitle="Per-OS price intercept relative to the reference OS. Tells you which OS commands a premium.">
        <RegressionTable data={olsOs.data} />
      </ChartCard>

      <ChartCard title="Price ~ all predictors (full OLS)"
                 subtitle="Brand + chipset + year + RAM + storage + physical specs. Best R² of the three regressions, but watch for multicollinearity — brand and chipset overlap strongly (Apple-brand ↔ Apple-chipset).">
        <RegressionTable data={olsFull.data} />
      </ChartCard>

      <h2>Diagnostics and feature selection</h2>

      <ChartCard title="Residual diagnostics (full OLS)"
                 subtitle="Residuals-vs-fitted reveals non-linearity and heteroscedasticity; the QQ plot shows whether residuals are normal. VIFs &gt; 10 (red) indicate concerning multicollinearity; 5–10 (yellow) is borderline.">
        <ResidualDiagnosticsPanel data={residuals.data} />
      </ChartCard>

      <ChartCard title="Forward stepwise feature selection"
                 subtitle="At each step, adds the predictor that gives the biggest gain in adjusted R². Stops when no candidate improves it. Excluded features are redundant given everything already in.">
        <FeatureSelectionPanel data={featureSel.data} />
      </ChartCard>
    </div>
  )
}
