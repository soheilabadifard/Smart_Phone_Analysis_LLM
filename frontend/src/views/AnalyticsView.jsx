import { useEffect, useState } from 'react'
import Plot from 'react-plotly.js'

import { humanizeColumnName } from '../utils/format.js'

// Catalogue palette — keep Plotly visually integrated with the page.
const C_PAPER       = '#efe7d6'
const C_PAPER_WARM  = '#e8dec9'
const C_INK         = '#181613'
const C_INK_SOFT    = '#4a4138'
const C_INK_MUTE    = '#7a6e5d'
const C_RULE_SOFT   = 'rgba(24, 22, 19, 0.16)'
const C_VERMILION   = '#c8331f'
const C_INDIGO      = '#2c3c63'
const C_MOSS        = '#4a6b2f'
const C_OCHRE       = '#b88517'

const PLOTLY_LAYOUT = {
  paper_bgcolor: C_PAPER,
  plot_bgcolor:  C_PAPER,
  font: {
    color: C_INK,
    family: '"Bricolage Grotesque", -apple-system, sans-serif',
    size: 12,
  },
  colorway: [C_VERMILION, C_INDIGO, C_MOSS, C_OCHRE, '#7a6e5d', '#9a3a5c'],
  margin: { t: 40, r: 20, b: 50, l: 60 },
  hovermode: 'closest',
  hoverlabel: {
    bgcolor: C_INK,
    bordercolor: C_INK,
    font: { color: C_PAPER, family: '"IBM Plex Mono", monospace', size: 11 },
  },
  xaxis: {
    gridcolor: C_RULE_SOFT,
    zerolinecolor: C_INK,
    linecolor: C_INK,
    tickcolor: C_INK,
    tickfont: { family: '"IBM Plex Mono", monospace', size: 10, color: C_INK_SOFT },
  },
  yaxis: {
    gridcolor: C_RULE_SOFT,
    zerolinecolor: C_INK,
    linecolor: C_INK,
    tickcolor: C_INK,
    tickfont: { family: '"IBM Plex Mono", monospace', size: 10, color: C_INK_SOFT },
  },
}

// Categorical palette for diverging series (e.g. pies, network bars).
const CAT_PALETTE = [C_VERMILION, C_INDIGO, C_MOSS, C_OCHRE, '#7a6e5d', '#9a3a5c', '#3a6e5c']

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
      <h3>{title}</h3>
      {subtitle && <p>{subtitle}</p>}
      {children}
    </div>
  )
}

function SectionHeader({ no, kicker, title }) {
  return (
    <header className="section">
      <div className="section__no">{no}</div>
      <div>
        <span className="section__kicker">{kicker}</span>
        <h2 className="section__title" style={{ margin: 0, border: 'none', padding: 0 }}>
          {title}
        </h2>
      </div>
    </header>
  )
}

function fmt(n, digits = 2) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits })
}

function ciTitleSuffix(rows) {
  const alpha = rows && rows.length > 0 ? rows[0].alpha : 0.05
  return `${Math.round((1 - alpha) * 100)}%`
}

function ciSubtitle(rows) {
  const alpha = rows && rows.length > 0 ? rows[0].alpha : 0.05
  return `α = ${alpha},`
}

function HistogramGrid({ data }) {
  const cols = Object.keys(data)
  const cells = cols.map((col) => (
    <Plot
      key={col}
      data={[{ type: 'histogram', x: data[col], marker: { color: C_INK, line: { color: C_VERMILION, width: 0.5 } }, opacity: 0.92 }]}
      layout={{
        ...PLOTLY_LAYOUT,
        height: 200,
        title: { text: humanizeColumnName(col), font: { size: 11, family: '"IBM Plex Mono", monospace', color: C_INK_MUTE } },
        margin: { t: 30, r: 8, b: 30, l: 38 },
      }}
      config={PLOTLY_CONFIG}
      style={{ width: '100%' }}
    />
  ))
  return <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem' }}>{cells}</div>
}

function RegressionTable({ data }) {
  if (!data) return null
  if (data.error) {
    return <div className="error">Could not fit model: {data.error}</div>
  }
  if (!Array.isArray(data.coefficients)) return null
  return (
    <div>
      <div style={{ color: C_INK_MUTE, fontSize: '0.9em', marginBottom: '0.5rem', fontFamily: 'var(--font-display)', fontStyle: 'italic' }}>
        {data.description}
      </div>
      <div className="stat-row">
        <span><b>n</b> {fmt(data.n, 0)}</span>
        <span><b>R²</b> {fmt(data.r_squared, 3)}</span>
        <span><b>Adj R²</b> {fmt(data.adj_r_squared, 3)}</span>
        <span><b>F</b> {fmt(data.f_statistic, 2)} <span style={{ color: C_INK_MUTE }}>(p = {fmt(data.f_p_value, 4)})</span></span>
      </div>
      {Array.isArray(data.dropped_predictors) && data.dropped_predictors.length > 0 && (
        <div style={{ color: C_OCHRE, fontSize: '0.82rem', marginBottom: '0.5rem', fontFamily: 'var(--font-mono)', letterSpacing: '0.04em' }}>
          ⌀ Dropped (no data for this form factor): {data.dropped_predictors.join(', ')}
        </div>
      )}
      <table style={{ fontSize: '0.9em' }}>
        <thead>
          <tr><th>Variable</th><th style={{ textAlign: 'right' }}>Coef</th><th style={{ textAlign: 'right' }}>Std err</th><th style={{ textAlign: 'right' }}>t</th><th style={{ textAlign: 'right' }}>p-value</th></tr>
        </thead>
        <tbody>
          {data.coefficients.map((c) => (
            <tr key={c.name}>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.82rem' }}>{c.name}</td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{fmt(c.coef, 4)}</td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', color: C_INK_MUTE }}>{fmt(c.std_err, 4)}</td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{fmt(c.t, 3)}</td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: c.p_value !== null && c.p_value < 0.05 ? 600 : 400, color: c.p_value !== null && c.p_value < 0.05 ? C_MOSS : C_INK_MUTE }}>
                {fmt(c.p_value, 4)}
              </td>
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
    return <div className="error">Could not fit model: {data.error}</div>
  }
  if (!Array.isArray(data.sample_residuals) || !Array.isArray(data.qq_plot) || !Array.isArray(data.vif)) {
    return null
  }
  const bp = data.breusch_pagan || {}
  const jb = data.jarque_bera || {}
  return (
    <div>
      <div className="stat-row">
        <span><b>n</b> {fmt(data.n, 0)}</span>
        <span><b>R²</b> {fmt(data.r_squared, 3)}</span>
        <span><b>Mean resid.</b> {fmt(data.mean_residual, 3)}</span>
        <span><b>Std resid.</b> {fmt(data.std_residual, 1)}</span>
        <span><b>Outliers |z|&gt;3</b> {data.n_outliers_z3}</span>
      </div>
      {Array.isArray(data.dropped_predictors) && data.dropped_predictors.length > 0 && (
        <div style={{ color: C_OCHRE, fontSize: '0.82rem', marginBottom: '0.5rem', fontFamily: 'var(--font-mono)' }}>
          ⌀ Dropped (no data for this form factor): {data.dropped_predictors.join(', ')}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
        <Plot
          data={[{
            type: 'scattergl', mode: 'markers',
            x: data.sample_residuals.map((p) => p.fitted),
            y: data.sample_residuals.map((p) => p.residual),
            marker: { size: 4, color: C_INK, opacity: 0.45 },
            hovertemplate: 'fitted: %{x:.0f}<br>residual: %{y:.0f}<extra></extra>',
          }, {
            type: 'scatter', mode: 'lines',
            x: [Math.min(...data.sample_residuals.map((p) => p.fitted)), Math.max(...data.sample_residuals.map((p) => p.fitted))],
            y: [0, 0],
            line: { color: C_VERMILION, dash: 'dash', width: 1.5 }, showlegend: false,
          }]}
          layout={{
            ...PLOTLY_LAYOUT, height: 320, showlegend: false,
            title: { text: 'Residuals vs fitted', font: { size: 12, family: '"IBM Plex Mono", monospace', color: C_INK_MUTE } },
            xaxis: { ...PLOTLY_LAYOUT.xaxis, title: { text: 'fitted (€)', font: { size: 11 } } },
            yaxis: { ...PLOTLY_LAYOUT.yaxis, title: { text: 'residual (€)', font: { size: 11 } } },
            margin: { t: 30, r: 10, b: 40, l: 50 },
          }}
          config={PLOTLY_CONFIG} style={{ width: '100%' }}
        />

        <Plot
          data={[{
            type: 'scattergl', mode: 'markers',
            x: data.qq_plot.map((p) => p.theoretical),
            y: data.qq_plot.map((p) => p.sample),
            marker: { size: 4, color: C_INDIGO, opacity: 0.6 },
            hovertemplate: 'theoretical: %{x:.2f}<br>sample: %{y:.2f}<extra></extra>',
          }, {
            type: 'scatter', mode: 'lines',
            x: [-4, 4], y: [-4, 4],
            line: { color: C_VERMILION, dash: 'dash', width: 1.5 }, showlegend: false,
          }]}
          layout={{
            ...PLOTLY_LAYOUT, height: 320, showlegend: false,
            title: { text: 'Normal QQ plot of standardized residuals', font: { size: 12, family: '"IBM Plex Mono", monospace', color: C_INK_MUTE } },
            xaxis: { ...PLOTLY_LAYOUT.xaxis, title: { text: 'theoretical quantile', font: { size: 11 } } },
            yaxis: { ...PLOTLY_LAYOUT.yaxis, title: { text: 'sample quantile', font: { size: 11 } } },
            margin: { t: 30, r: 10, b: 40, l: 50 },
          }}
          config={PLOTLY_CONFIG} style={{ width: '100%' }}
        />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginTop: '1rem' }}>
        <table style={{ fontSize: '0.9em' }}>
          <thead>
            <tr><th colSpan="2">Diagnostic tests</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>Breusch-Pagan (heteroscedasticity)</td>
              <td style={{ fontFamily: 'var(--font-mono)' }}>
                p = {fmt(bp.p_value, 4)}
                {bp.p_value !== null && bp.p_value < 0.05 && <span style={{ color: C_VERMILION, marginLeft: '0.3rem' }}>← reject H₀</span>}
              </td>
            </tr>
            <tr>
              <td>Jarque-Bera (residual normality)</td>
              <td style={{ fontFamily: 'var(--font-mono)' }}>p = {fmt(jb.p_value, 4)} <span style={{ color: C_INK_MUTE }}>(skew {fmt(jb.skew, 2)}, kurt. {fmt(jb.kurtosis, 2)})</span></td>
            </tr>
          </tbody>
        </table>

        <table style={{ fontSize: '0.88em' }}>
          <thead>
            <tr><th>Predictor</th><th style={{ textAlign: 'right' }}>VIF</th></tr>
          </thead>
          <tbody>
            {data.vif.slice(0, 10).map((v) => (
              <tr key={v.predictor}>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.82rem' }}>{v.predictor}</td>
                <td style={{
                  textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 500,
                  color: v.vif !== null && v.vif > 10 ? C_VERMILION : v.vif !== null && v.vif > 5 ? C_OCHRE : C_INK,
                }}>{fmt(v.vif, 2)}</td>
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
    return <div className="error">Stepwise failed: {data.error}</div>
  }
  if (!Array.isArray(data.history)) return null
  const { history = [], final_features = [], final_formula, final_summary } = data
  return (
    <div>
      <p style={{ marginTop: 0, fontFamily: 'var(--font-display)', fontStyle: 'italic', fontSize: '1rem' }}>
        Best model after stepwise: <code style={{ fontStyle: 'normal', fontSize: '0.85em' }}>{final_formula}</code>
        <br />
        Adj R² = <strong style={{ color: C_VERMILION }}>{fmt(final_summary?.adj_r_squared, 3)}</strong>, R² = {fmt(final_summary?.r_squared, 3)}, n = {fmt(final_summary?.n, 0)}.
      </p>

      <table style={{ fontSize: '0.9em' }}>
        <thead>
          <tr><th>Step</th><th>Added</th><th style={{ textAlign: 'right' }}>Adj R²</th><th style={{ textAlign: 'right' }}>AIC</th><th style={{ textAlign: 'right' }}>BIC</th></tr>
        </thead>
        <tbody>
          {history.map((row) => (
            <tr key={row.step}>
              <td style={{ fontFamily: 'var(--font-mono)', color: C_INK_MUTE }}>{row.step.toString().padStart(2, '0')}</td>
              <td><code>{row.added}</code></td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{fmt(row.adj_r_squared, 4)}</td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', color: C_INK_MUTE }}>{fmt(row.aic, 0)}</td>
              <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', color: C_INK_MUTE }}>{fmt(row.bic, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginTop: '0.75rem', fontSize: '0.86em', color: C_INK_MUTE, fontFamily: 'var(--font-mono)' }}>
        Selected: {final_features.map((f) => <code key={f} style={{ marginRight: '0.4rem' }}>{f}</code>)}
      </div>
    </div>
  )
}

function HypothesisTestPanel({ data }) {
  if (!data) return null
  const { name, description, test, p_value, conclusion, decision, anova, groups,
          null_hypothesis, alternative_hypothesis, alpha = 0.05 } = data
  const reject = p_value !== null && p_value !== undefined && p_value < alpha
  const decisionColor = p_value === null || p_value === undefined ? C_INK_MUTE
                      : reject ? C_VERMILION : C_INDIGO
  return (
    <div style={{ borderTop: '1px solid var(--rule-soft)', paddingTop: '1rem', marginTop: '1rem' }}>
      <strong style={{ fontFamily: 'var(--font-display)', fontSize: '1.04rem', fontWeight: 700, letterSpacing: '-0.012em' }}>{name}</strong>
      <div style={{ color: C_INK_MUTE, fontSize: '0.88em', margin: '0.25rem 0 0.6rem', fontFamily: 'var(--font-display)', fontStyle: 'italic' }}>{description}</div>
      {(null_hypothesis || alternative_hypothesis) && (
        <div style={{
          background: C_PAPER_WARM, padding: '0.65rem 0.9rem',
          margin: '0.5rem 0', fontSize: '0.92em', borderLeft: `2px solid ${C_INK}`,
          fontFamily: 'var(--font-display)', fontStyle: 'italic',
        }}>
          {null_hypothesis && <div><b style={{ fontStyle: 'normal' }}>H₀</b> &nbsp;{null_hypothesis}</div>}
          {alternative_hypothesis && <div><b style={{ fontStyle: 'normal' }}>H₁</b> &nbsp;{alternative_hypothesis}</div>}
        </div>
      )}
      <div className="stat-row" style={{ borderBottom: 'none', marginBottom: '0.4rem', paddingBottom: 0 }}>
        <span><b>Test</b> {test}</span>
        <span><b>p-value</b> {p_value === null || p_value === undefined ? '—' : fmt(p_value, 4)}</span>
        <span><b>α</b> {fmt(alpha, 2)}</span>
        <span>
          <b>Result</b>{' '}
          <span style={{ color: decisionColor, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', fontSize: '0.78rem' }}>
            {decision || conclusion}
          </span>
        </span>
      </div>
      {anova && anova.length > 0 && (
        <table style={{ marginTop: '0.5rem', fontSize: '0.88em' }}>
          <thead>
            <tr><th>Factor</th><th style={{ textAlign: 'right' }}>df</th><th style={{ textAlign: 'right' }}>F</th><th style={{ textAlign: 'right' }}>p</th></tr>
          </thead>
          <tbody>
            {anova.map((row) => (
              <tr key={row.factor}>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.82rem' }}>{row.factor}</td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{fmt(row.df, 0)}</td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{fmt(row.F, 3)}</td>
                <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', color: row.p_value < 0.05 ? C_MOSS : C_INK_MUTE }}>{fmt(row.p_value, 4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {groups && groups.length > 0 && (
        <Plot
          data={groups.map((g, i) => {
            const labelKey = ['os_name', 'sim_type', 'brand', 'size'].find((k) => k in g) || 'group'
            const labelParts = []
            if (g.brand) labelParts.push(g.brand)
            if (g.os_name) labelParts.push(g.os_name)
            if (g.sim_type) labelParts.push(g.sim_type)
            if (g.size) labelParts.push(g.size)
            const label = labelParts.join(' / ') || g[labelKey] || 'group'
            return {
              type: 'box', name: label, y: g.values,
              boxpoints: 'suspectedoutliers',
              marker: { color: CAT_PALETTE[i % CAT_PALETTE.length], size: 3, opacity: 0.6 },
              line: { width: 1.5 },
            }
          })}
          layout={{ ...PLOTLY_LAYOUT, height: 320, margin: { t: 20, r: 10, b: 50, l: 50 }, showlegend: false }}
          config={PLOTLY_CONFIG}
          style={{ width: '100%' }}
        />
      )}
    </div>
  )
}

export default function AnalyticsView({ formFactor = 'phone' }) {
  const q = `?form_factor=${encodeURIComponent(formFactor)}`

  const years = useEndpoint(`/api/analytics/available-years${q}`)
  const [priceCiYear, setPriceCiYear] = useState('')
  const [priceCiAlpha, setPriceCiAlpha] = useState(0.05)

  const brand = useEndpoint(`/api/analytics/brand-summary${q}`)
  const annual = useEndpoint(`/api/analytics/annual-launches${q}`)
  const chipset = useEndpoint(`/api/analytics/chipset-popularity${q}`)
  const ram = useEndpoint(`/api/analytics/ram-distribution${q}`)
  const scatter = useEndpoint(`/api/analytics/price-vs-battery${q}`)

  const network = useEndpoint(`/api/analytics/network-technology${q}`)
  const simType = useEndpoint(`/api/analytics/sim-type-distribution${q}`)
  const androidVer = useEndpoint(`/api/analytics/top-android-versions${q}`)
  const topExpensive = useEndpoint(`/api/analytics/top-expensive-phones${q}`)
  const ppiTrend = useEndpoint(`/api/analytics/ppi-trend${q}`)
  const corr = useEndpoint(`/api/analytics/correlation-matrix${q}`)
  const quant = useEndpoint(`/api/analytics/quantitative-distributions${q}`)

  const priceCiQs = `${q}${priceCiYear ? `&year=${encodeURIComponent(priceCiYear)}` : ''}&alpha=${priceCiAlpha}`
  const priceCi = useEndpoint(`/api/analytics/price-ci-by-brand${priceCiQs}`)
  const batteryCi = useEndpoint(`/api/analytics/battery-ci-by-brand${q}&alpha=${priceCiAlpha}`)
  const ht1 = useEndpoint(`/api/analytics/ht-price-by-sim-and-size${q}`)
  const ht2 = useEndpoint(`/api/analytics/ht-ppi-by-size${q}`)
  const ht3 = useEndpoint(`/api/analytics/ht-weight-android-vs-ios${q}`)
  const ht4 = useEndpoint(`/api/analytics/ht-battery-by-brand-and-size${q}`)
  const ht5 = useEndpoint(`/api/analytics/ht-price-by-brand-and-size${q}`)
  const ht6 = useEndpoint(`/api/analytics/ht-weight-by-size${q}`)
  const ht7 = useEndpoint(`/api/analytics/ht-battery-by-cpu${q}`)
  const ht8 = useEndpoint(`/api/analytics/ht-price-by-chipset${q}`)
  const ht9 = useEndpoint(`/api/analytics/ht-price-by-main-camera${q}`)

  const olsSpecs = useEndpoint(`/api/analytics/price-regression-specs${q}`)
  const olsOs = useEndpoint(`/api/analytics/price-regression-os${q}`)
  const olsFull = useEndpoint(`/api/analytics/price-regression-full${q}`)

  const residuals = useEndpoint(`/api/analytics/price-residuals?model=full&form_factor=${encodeURIComponent(formFactor)}`)
  const featureSel = useEndpoint(`/api/analytics/price-feature-selection${q}`)

  const factorLabel = formFactor === 'phone' ? 'phones'
                     : formFactor === 'watch' ? 'watches'
                     : formFactor === 'tablet' ? 'tablets'
                     : formFactor

  return (
    <div>
      <SectionHeader
        no="02"
        kicker={`Form factor scope · ${factorLabel}`}
        title="Catalogue overview"
      />

      <ChartCard title="Top brands by catalogue size (avg price colored)">
        {brand.data && (
          <Plot
            data={[{
              type: 'bar',
              x: brand.data.map((d) => d.brand),
              y: brand.data.map((d) => d.device_count),
              marker: {
                color: brand.data.map((d) => d.avg_price_eur),
                colorscale: [[0, C_PAPER_WARM], [0.4, C_OCHRE], [1, C_VERMILION]],
                line: { color: C_INK, width: 0.5 },
                colorbar: {
                  title: { text: 'avg €', font: { size: 11, family: '"IBM Plex Mono", monospace' } },
                  outlinecolor: C_INK,
                  tickfont: { family: '"IBM Plex Mono", monospace', size: 10 },
                },
              },
              hovertemplate: '%{x}<br>devices: %{y}<br>avg €%{marker.color:.0f}<extra></extra>',
            }]}
            layout={{ ...PLOTLY_LAYOUT, height: 420, xaxis: { ...PLOTLY_LAYOUT.xaxis, tickangle: -40 } }}
            config={PLOTLY_CONFIG}
            style={{ width: '100%' }}
          />
        )}
      </ChartCard>

      <ChartCard title="Annual launches and average specs">
        {annual.data && (
          <Plot
            data={[
              { type: 'bar', name: 'launches', x: annual.data.map((d) => d.year), y: annual.data.map((d) => d.launches), yaxis: 'y', marker: { color: C_INK, line: { color: C_VERMILION, width: 0.4 } } },
              { type: 'scatter', mode: 'lines+markers', name: 'avg price (€)', x: annual.data.map((d) => d.year), y: annual.data.map((d) => d.avg_price_eur), yaxis: 'y2', line: { color: C_VERMILION, width: 2.5 }, marker: { color: C_VERMILION, size: 7 } },
              { type: 'scatter', mode: 'lines+markers', name: 'avg battery (mAh)', x: annual.data.map((d) => d.year), y: annual.data.map((d) => d.avg_battery_mah), yaxis: 'y3', visible: 'legendonly', line: { color: C_MOSS, width: 2 }, marker: { color: C_MOSS, size: 6 } },
            ]}
            layout={{
              ...PLOTLY_LAYOUT, height: 460,
              yaxis: { ...PLOTLY_LAYOUT.yaxis, title: { text: 'launches' } },
              yaxis2: { ...PLOTLY_LAYOUT.yaxis, title: { text: 'avg €' }, overlaying: 'y', side: 'right', gridcolor: 'transparent' },
              yaxis3: { ...PLOTLY_LAYOUT.yaxis, title: { text: 'mAh' }, overlaying: 'y', side: 'right', position: 0.92, anchor: 'free', gridcolor: 'transparent' },
              legend: { orientation: 'h', y: -0.2, font: { family: '"IBM Plex Mono", monospace', size: 10 } },
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
                colorscale: [[0, C_INDIGO], [0.5, C_OCHRE], [1, C_VERMILION]],
                colorbar: {
                  title: { text: 'year', font: { size: 11, family: '"IBM Plex Mono", monospace' } },
                  outlinecolor: C_INK,
                  tickfont: { family: '"IBM Plex Mono", monospace', size: 10 },
                },
                opacity: 0.7,
                line: { width: 0 },
              },
              hovertemplate: '%{text}<br>battery: %{x} mAh<br>price: €%{y}<extra></extra>',
            }]}
            layout={{
              ...PLOTLY_LAYOUT, height: 460,
              xaxis: { ...PLOTLY_LAYOUT.xaxis, title: { text: 'battery (mAh)' } },
              yaxis: { ...PLOTLY_LAYOUT.yaxis, title: { text: 'price (€)' } },
            }}
            config={PLOTLY_CONFIG}
            style={{ width: '100%' }}
          />
        )}
      </ChartCard>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.4rem' }}>
        <ChartCard title="Top chipset manufacturers">
          {chipset.data && (
            <Plot
              data={[{
                type: 'pie',
                labels: chipset.data.map((d) => d.chipset_manufacturer),
                values: chipset.data.map((d) => d.device_count),
                hole: 0.55,
                marker: { colors: CAT_PALETTE, line: { color: C_PAPER, width: 2 } },
                textinfo: 'label+percent',
                textfont: { family: '"IBM Plex Mono", monospace', size: 10, color: C_INK },
                insidetextfont: { color: C_PAPER },
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
                marker: { color: C_INK, line: { color: C_VERMILION, width: 0.5 } },
              }]}
              layout={{ ...PLOTLY_LAYOUT, height: 380 }}
              config={PLOTLY_CONFIG}
              style={{ width: '100%' }}
            />
          )}
        </ChartCard>
      </div>

      <SectionHeader
        no="03"
        kicker="Distributions · rankings · trends"
        title="The catalogue, broken apart"
      />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.4rem' }}>
        <ChartCard
          title="Network generations supported"
          subtitle="A device can support multiple — values do not sum to 100%."
        >
          {network.data && (
            <Plot
              data={[{
                type: 'bar',
                x: network.data.map((d) => d.generation),
                y: network.data.map((d) => d.pct),
                text: network.data.map((d) => `${d.device_count} (${d.pct}%)`),
                textposition: 'outside',
                textfont: { family: '"IBM Plex Mono", monospace', size: 10, color: C_INK_SOFT },
                marker: { color: CAT_PALETTE.slice(0, network.data.length), line: { color: C_INK, width: 0.5 } },
              }]}
              layout={{ ...PLOTLY_LAYOUT, height: 360, yaxis: { ...PLOTLY_LAYOUT.yaxis, title: { text: '% of phones' }, range: [0, 105] } }}
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
                hole: 0.55,
                marker: { colors: CAT_PALETTE, line: { color: C_PAPER, width: 2 } },
                textinfo: 'label+percent',
                textfont: { family: '"IBM Plex Mono", monospace', size: 10, color: C_INK },
                insidetextfont: { color: C_PAPER },
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
              marker: { color: C_MOSS, line: { color: C_INK, width: 0.4 } },
            }]}
            layout={{
              ...PLOTLY_LAYOUT, height: 340,
              xaxis: { ...PLOTLY_LAYOUT.xaxis, title: { text: 'Android version' } },
              yaxis: { ...PLOTLY_LAYOUT.yaxis, title: { text: 'devices' } },
            }}
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
              data={brands.map((b, i) => {
                const rows = ppiTrend.data.filter((d) => d.brand === b)
                return {
                  type: 'scatter',
                  mode: 'lines+markers',
                  name: b,
                  x: rows.map((r) => r.year),
                  y: rows.map((r) => r.avg_ppi),
                  line: { color: CAT_PALETTE[i % CAT_PALETTE.length], width: 2.5 },
                  marker: { color: CAT_PALETTE[i % CAT_PALETTE.length], size: 7 },
                }
              })}
              layout={{
                ...PLOTLY_LAYOUT, height: 380,
                xaxis: { ...PLOTLY_LAYOUT.xaxis, title: { text: 'year' } },
                yaxis: { ...PLOTLY_LAYOUT.yaxis, title: { text: 'avg PPI density' } },
                legend: { font: { family: '"IBM Plex Mono", monospace', size: 11 } },
              }}
              config={PLOTLY_CONFIG}
              style={{ width: '100%' }}
            />
          )
        })()}
      </ChartCard>

      <ChartCard title="50 most expensive phones">
        {topExpensive.data && (
          <div style={{ maxHeight: 380, overflowY: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: '2rem' }}>No.</th>
                  <th>Brand</th><th>Model</th><th>Year</th>
                  <th style={{ textAlign: 'right' }}>Price (€)</th>
                  <th>OS</th>
                </tr>
              </thead>
              <tbody>
                {topExpensive.data.map((row, i) => (
                  <tr key={i}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: C_INK_MUTE }}>{(i + 1).toString().padStart(2, '0')}</td>
                    <td style={{ fontFamily: 'var(--font-display)', fontWeight: 600 }}>{row.brand}</td>
                    <td>{row.model}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: C_INK_SOFT }}>{row.year}</td>
                    <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 500 }}>{fmt(row.price_eur, 0)}</td>
                    <td style={{ color: C_INK_SOFT }}>{row.os_name ? `${row.os_name}${row.os_version ? ' ' + row.os_version : ''}` : '—'}</td>
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
              colorscale: [
                [0, C_INDIGO], [0.25, '#6e7a99'], [0.5, C_PAPER_WARM],
                [0.75, C_OCHRE], [1, C_VERMILION],
              ],
              hovertemplate: '%{x} ↔ %{y}<br>r = %{z:.2f}<extra></extra>',
              colorbar: {
                outlinecolor: C_INK,
                tickfont: { family: '"IBM Plex Mono", monospace', size: 10 },
              },
            }]}
            layout={{
              ...PLOTLY_LAYOUT, height: 520,
              xaxis: { ...PLOTLY_LAYOUT.xaxis, tickangle: -40, tickfont: { size: 9, family: '"IBM Plex Mono", monospace', color: C_INK_SOFT } },
              yaxis: { ...PLOTLY_LAYOUT.yaxis, tickfont: { size: 9, family: '"IBM Plex Mono", monospace', color: C_INK_SOFT } },
            }}
            config={PLOTLY_CONFIG}
            style={{ width: '100%' }}
          />
        )}
      </ChartCard>

      <ChartCard
        title="Distributions of quantitative columns (phone-only)"
        subtitle="Histograms over all phones."
      >
        {quant.data && <HistogramGrid data={quant.data} />}
      </ChartCard>

      <SectionHeader
        no="04"
        kicker="Estimation · hypothesis testing"
        title="Inferential statistics"
      />

      <div className="controls-strip">
        <strong>Confidence-interval controls</strong>
        <label>
          Year
          <select
            aria-label="Year for price CI"
            value={priceCiYear}
            onChange={(e) => setPriceCiYear(e.target.value)}
          >
            <option value="">latest populated</option>
            {years.data && years.data.map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </label>
        <label>
          α
          <select
            aria-label="Alpha for confidence intervals"
            value={priceCiAlpha}
            onChange={(e) => setPriceCiAlpha(Number(e.target.value))}
          >
            <option value={0.01}>0.01 (99% CI)</option>
            <option value={0.05}>0.05 (95% CI)</option>
            <option value={0.10}>0.10 (90% CI)</option>
          </select>
        </label>
        <span style={{ color: C_INK_MUTE, fontSize: '0.78rem', fontStyle: 'italic', fontFamily: 'var(--font-display)' }}>
          Both CI charts below re-fetch when these change.
        </span>
      </div>

      <ChartCard
        title={`Average price by brand — ${ciTitleSuffix(priceCi.data)} confidence interval${
          priceCi.data && priceCi.data[0]?.year != null ? ` (${priceCi.data[0].year})` : ''
        }`}
        subtitle={`Top-5 brands for the form factor. ${ciSubtitle(priceCi.data)} t-distribution.`}
      >
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
                color: C_INK,
                thickness: 1.5,
                width: 6,
              },
              marker: { color: C_VERMILION, line: { color: C_INK, width: 0.5 } },
              text: priceCi.data.map((d) => d.n != null && d.n > 0 ? `n=${d.n}` : 'n=0'),
              textposition: 'outside',
              textfont: { family: '"IBM Plex Mono", monospace', size: 10, color: C_INK_SOFT },
            }]}
            layout={{ ...PLOTLY_LAYOUT, height: 400, yaxis: { ...PLOTLY_LAYOUT.yaxis, title: { text: 'price (€)' } } }}
            config={PLOTLY_CONFIG}
            style={{ width: '100%' }}
          />
        )}
      </ChartCard>

      <ChartCard
        title={`Average battery capacity by brand — ${ciTitleSuffix(batteryCi.data)} confidence interval`}
        subtitle={`Top-5 brands for the form factor, all years pooled. ${ciSubtitle(batteryCi.data)} t-distribution.`}
      >
        {batteryCi.data && (
          <Plot
            data={[{
              type: 'bar',
              x: batteryCi.data.map((d) => d.brand),
              y: batteryCi.data.map((d) => d.mean ?? 0),
              error_y: {
                type: 'data',
                symmetric: false,
                array: batteryCi.data.map((d) => (d.upper ?? 0) - (d.mean ?? 0)),
                arrayminus: batteryCi.data.map((d) => (d.mean ?? 0) - (d.lower ?? 0)),
                color: C_INK,
                thickness: 1.5,
                width: 6,
              },
              marker: { color: C_MOSS, line: { color: C_INK, width: 0.5 } },
              text: batteryCi.data.map((d) => d.n != null && d.n > 0 ? `n=${d.n}` : 'n=0'),
              textposition: 'outside',
              textfont: { family: '"IBM Plex Mono", monospace', size: 10, color: C_INK_SOFT },
            }]}
            layout={{ ...PLOTLY_LAYOUT, height: 400, yaxis: { ...PLOTLY_LAYOUT.yaxis, title: { text: 'battery (mAh)' } } }}
            config={PLOTLY_CONFIG}
            style={{ width: '100%' }}
          />
        )}
      </ChartCard>

      <ChartCard
        title="Hypothesis tests"
        subtitle="Each test reports the test statistic, p-value, and a conclusion at α = 0.05."
      >
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

      <SectionHeader
        no="05"
        kicker="Multivariate OLS · three specifications"
        title="Regression models"
      />

      <ChartCard
        title="Price ~ physical specs (OLS)"
        subtitle="Multivariate regression of price on six numeric specs. Significant coefficients (p < 0.05) shown in moss."
      >
        <RegressionTable data={olsSpecs.data} />
      </ChartCard>

      <ChartCard
        title="Price ~ OS (OLS, one-hot)"
        subtitle="Per-OS price intercept relative to the reference OS. Tells you which OS commands a premium."
      >
        <RegressionTable data={olsOs.data} />
      </ChartCard>

      <ChartCard
        title="Price ~ all predictors (full OLS)"
        subtitle="Brand + chipset + year + RAM + storage + physical specs. Best R² of the three regressions, but watch for multicollinearity — brand and chipset overlap strongly (Apple-brand ↔ Apple-chipset)."
      >
        <RegressionTable data={olsFull.data} />
      </ChartCard>

      <SectionHeader
        no="06"
        kicker="Residual analysis · stepwise selection"
        title="Diagnostics and feature selection"
      />

      <ChartCard
        title="Residual diagnostics (full OLS)"
        subtitle="Residuals-vs-fitted reveals non-linearity and heteroscedasticity; the QQ plot shows whether residuals are normal. VIFs > 10 (vermilion) indicate concerning multicollinearity; 5–10 (ochre) is borderline."
      >
        <ResidualDiagnosticsPanel data={residuals.data} />
      </ChartCard>

      <ChartCard
        title="Forward stepwise feature selection"
        subtitle="At each step, adds the predictor that gives the biggest gain in adjusted R². Stops when no candidate improves it. Excluded features are redundant given everything already in."
      >
        <FeatureSelectionPanel data={featureSel.data} />
      </ChartCard>
    </div>
  )
}
