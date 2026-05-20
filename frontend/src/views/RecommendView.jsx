import { useEffect, useState } from 'react'

const initialFilters = {
  max_price_eur: '',
  os_name: '',
  min_ram_gb: '',
  min_storage_gb: '',
  min_battery_mah: '',
  min_display_inch: '',
  max_display_inch: '',
  require_5g: false,
  form_factor: 'phone',
  sort_by: 'price',
  sort_order: 'asc',
  limit: 50,
}

const FORM_FACTORS = [
  { value: 'phone', label: 'Phone' },
  { value: 'watch', label: 'Watch' },
  { value: 'tablet', label: 'Tablet' },
  { value: 'band', label: 'Band' },
  { value: 'other', label: 'Other' },
  { value: 'any', label: 'Any' },
]

export default function RecommendView() {
  const [filters, setFilters] = useState(initialFilters)
  const [brands, setBrands] = useState([])
  const [selectedBrands, setSelectedBrands] = useState([])
  const [osList, setOsList] = useState([])
  const [results, setResults] = useState([])
  const [submitted, setSubmitted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    Promise.all([
      fetch('/api/recommend/brands').then((r) => r.json()),
      fetch('/api/recommend/os').then((r) => r.json()),
    ]).then(([b, o]) => {
      setBrands(b)
      setOsList(o)
    })
  }, [])

  const update = (k, v) => setFilters((f) => ({ ...f, [k]: v }))

  const submit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const body = {}
      for (const [k, v] of Object.entries(filters)) {
        if (v === '' || v === null) continue
        body[k] = ['min_ram_gb', 'min_storage_gb', 'min_battery_mah', 'limit'].includes(k)
          ? parseInt(v, 10)
          : ['max_price_eur', 'min_display_inch', 'max_display_inch'].includes(k)
          ? parseFloat(v)
          : v
      }
      if (selectedBrands.length) body.brands = selectedBrands

      const res = await fetch('/api/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error(await res.text())
      setResults(await res.json())
      setSubmitted(true)
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <header className="section">
        <div className="section__no">01</div>
        <div>
          <span className="section__kicker">Filtered query · typed Pydantic → SQL</span>
          <h2 className="section__title" style={{ margin: 0, border: 'none', padding: 0 }}>
            Spec-sheet recommender
          </h2>
        </div>
      </header>

      <form className="card" onSubmit={submit} style={{ borderTop: 'none', paddingTop: 0 }}>
        <div className="form-grid">
          <label>
            Max price (EUR)
            <input type="number" min="0" step="10" value={filters.max_price_eur} onChange={(e) => update('max_price_eur', e.target.value)} placeholder="any" />
          </label>
          <label>
            Brands (multi)
            <select multiple size="4" value={selectedBrands} onChange={(e) => setSelectedBrands(Array.from(e.target.selectedOptions, (o) => o.value))}>
              {brands.map((b) => (<option key={b}>{b}</option>))}
            </select>
          </label>
          <label>
            Operating system
            <select value={filters.os_name} onChange={(e) => update('os_name', e.target.value)}>
              <option value="">Any</option>
              {osList.map((o) => (<option key={o}>{o}</option>))}
            </select>
          </label>
          <label>
            Min RAM (GB)
            <input type="number" min="0" value={filters.min_ram_gb} onChange={(e) => update('min_ram_gb', e.target.value)} placeholder="—" />
          </label>
          <label>
            Min storage (GB)
            <input type="number" min="0" value={filters.min_storage_gb} onChange={(e) => update('min_storage_gb', e.target.value)} placeholder="—" />
          </label>
          <label>
            Min battery (mAh)
            <input type="number" min="0" step="100" value={filters.min_battery_mah} onChange={(e) => update('min_battery_mah', e.target.value)} placeholder="—" />
          </label>
          <label>
            Min display (in)
            <input type="number" min="0" step="0.1" value={filters.min_display_inch} onChange={(e) => update('min_display_inch', e.target.value)} placeholder="—" />
          </label>
          <label>
            Max display (in)
            <input type="number" min="0" step="0.1" value={filters.max_display_inch} onChange={(e) => update('max_display_inch', e.target.value)} placeholder="—" />
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: '0.6rem', alignSelf: 'end', paddingBottom: '0.4rem' }}>
            <input type="checkbox" checked={filters.require_5g} onChange={(e) => update('require_5g', e.target.checked)} />
            <span>Require 5G</span>
          </label>
          <label>
            Form factor
            <select value={filters.form_factor} onChange={(e) => update('form_factor', e.target.value)}>
              {FORM_FACTORS.map((f) => (<option key={f.value} value={f.value}>{f.label}</option>))}
            </select>
          </label>
          <label>
            Sort by
            <select value={filters.sort_by} onChange={(e) => update('sort_by', e.target.value)}>
              <option value="price">Price</option>
              <option value="battery">Battery</option>
              <option value="ram">RAM</option>
              <option value="year">Year</option>
            </select>
          </label>
          <label>
            Order
            <select value={filters.sort_order} onChange={(e) => update('sort_order', e.target.value)}>
              <option value="asc">Ascending</option>
              <option value="desc">Descending</option>
            </select>
          </label>
        </div>
        <button className="primary" type="submit" disabled={loading}>
          {loading ? 'Searching…' : 'Find phones'}
        </button>
      </form>

      {error && <div className="error">{error}</div>}

      {results.length > 0 && (
        <div className="card">
          <h3>Catalogue results</h3>
          <p className="results-header">
            {`${results.length} result${results.length === 1 ? '' : 's'} matched`}
            <span style={{ color: 'var(--ink-faint)' }}> — sorted by {filters.sort_by}, {filters.sort_order}ending</span>
          </p>
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: '2.5rem' }}>No.</th>
                  <th>Brand</th><th>Model</th><th>Year</th><th>Type</th>
                  <th style={{ textAlign: 'right' }}>Price (€)</th>
                  <th style={{ textAlign: 'right' }}>RAM</th>
                  <th style={{ textAlign: 'right' }}>Storage</th>
                  <th style={{ textAlign: 'right' }}>Battery</th>
                  <th style={{ textAlign: 'right' }}>Display</th>
                  <th>OS</th><th>Chipset</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr key={r.device_id}>
                    <td style={{ color: 'var(--ink-faint)', fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                      {(i + 1).toString().padStart(2, '0')}
                    </td>
                    <td style={{ fontFamily: 'var(--font-display)', fontWeight: 600, letterSpacing: '-0.01em' }}>{r.brand}</td>
                    <td>{r.model}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem', color: 'var(--ink-soft)' }}>{r.year}</td>
                    <td style={{ textTransform: 'capitalize', color: 'var(--ink-soft)' }}>{r.form_factor}</td>
                    <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{r.price_eur ?? '—'}</td>
                    <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{r.ram_gb ?? '—'}</td>
                    <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{r.storage_gb ?? '—'}</td>
                    <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{r.battery_mah ?? '—'}</td>
                    <td style={{ textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{r.display_inch ? `${r.display_inch}″` : '—'}</td>
                    <td>{r.os ?? '—'}</td>
                    <td style={{ color: 'var(--ink-soft)' }}>{r.chipset ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {submitted && !loading && results.length === 0 && !error && (
        <div className="card" style={{ textAlign: 'center', padding: '2.5rem 0 2.8rem', color: 'var(--ink-mute)' }}>
          <p style={{ fontFamily: 'var(--font-display)', fontStyle: 'italic', fontSize: '1.1rem', margin: 0 }}>
            No devices matched these constraints. Try widening one of them.
          </p>
        </div>
      )}
    </div>
  )
}
