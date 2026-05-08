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
  sort_by: 'price',
  sort_order: 'asc',
  limit: 50,
}

export default function RecommendView() {
  const [filters, setFilters] = useState(initialFilters)
  const [brands, setBrands] = useState([])
  const [selectedBrands, setSelectedBrands] = useState([])
  const [osList, setOsList] = useState([])
  const [results, setResults] = useState([])
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
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <form className="card" onSubmit={submit}>
        <div className="form-grid">
          <label>
            Max price (EUR)
            <input type="number" min="0" step="10" value={filters.max_price_eur} onChange={(e) => update('max_price_eur', e.target.value)} />
          </label>
          <label>
            Brands (multi-select)
            <select multiple size="4" value={selectedBrands} onChange={(e) => setSelectedBrands(Array.from(e.target.selectedOptions, (o) => o.value))}>
              {brands.map((b) => (<option key={b}>{b}</option>))}
            </select>
          </label>
          <label>
            OS
            <select value={filters.os_name} onChange={(e) => update('os_name', e.target.value)}>
              <option value="">Any</option>
              {osList.map((o) => (<option key={o}>{o}</option>))}
            </select>
          </label>
          <label>
            Min RAM (GB)
            <input type="number" min="0" value={filters.min_ram_gb} onChange={(e) => update('min_ram_gb', e.target.value)} />
          </label>
          <label>
            Min storage (GB)
            <input type="number" min="0" value={filters.min_storage_gb} onChange={(e) => update('min_storage_gb', e.target.value)} />
          </label>
          <label>
            Min battery (mAh)
            <input type="number" min="0" step="100" value={filters.min_battery_mah} onChange={(e) => update('min_battery_mah', e.target.value)} />
          </label>
          <label>
            Min display (inch)
            <input type="number" min="0" step="0.1" value={filters.min_display_inch} onChange={(e) => update('min_display_inch', e.target.value)} />
          </label>
          <label>
            Max display (inch)
            <input type="number" min="0" step="0.1" value={filters.max_display_inch} onChange={(e) => update('max_display_inch', e.target.value)} />
          </label>
          <label style={{ flexDirection: 'row', alignItems: 'center', gap: '0.5rem' }}>
            <input type="checkbox" checked={filters.require_5g} onChange={(e) => update('require_5g', e.target.checked)} />
            Require 5G
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
          <p style={{ marginTop: 0 }}>{results.length} result{results.length === 1 ? '' : 's'}</p>
          <table>
            <thead>
              <tr>
                <th>Brand</th><th>Model</th><th>Year</th><th>Price (€)</th>
                <th>RAM</th><th>Storage</th><th>Battery</th><th>Display</th>
                <th>OS</th><th>Chipset</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.device_id}>
                  <td>{r.brand}</td>
                  <td>{r.model}</td>
                  <td>{r.year}</td>
                  <td>{r.price_eur ?? '—'}</td>
                  <td>{r.ram_gb ?? '—'}</td>
                  <td>{r.storage_gb ?? '—'}</td>
                  <td>{r.battery_mah ?? '—'}</td>
                  <td>{r.display_inch ?? '—'}″</td>
                  <td>{r.os ?? '—'}</td>
                  <td>{r.chipset ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
