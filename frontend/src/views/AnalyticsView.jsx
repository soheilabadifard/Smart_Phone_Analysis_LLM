import { useEffect, useState } from 'react'
import Plot from 'react-plotly.js'

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

function ChartCard({ title, children }) {
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>{title}</h3>
      {children}
    </div>
  )
}

export default function AnalyticsView() {
  const brand = useEndpoint('/api/analytics/brand-summary')
  const annual = useEndpoint('/api/analytics/annual-launches')
  const chipset = useEndpoint('/api/analytics/chipset-popularity')
  const ram = useEndpoint('/api/analytics/ram-distribution')
  const scatter = useEndpoint('/api/analytics/price-vs-battery')

  return (
    <div>
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
    </div>
  )
}
