import { useState } from 'react'
import RecommendView from './views/RecommendView.jsx'
import AnalyticsView from './views/AnalyticsView.jsx'
import AskView from './views/AskView.jsx'

const TABS = [
  { id: 'recommend', label: 'Recommend' },
  { id: 'analytics-phone', label: 'Phone Analytics' },
  { id: 'analytics-watch', label: 'Watch Analytics' },
  { id: 'analytics-tablet', label: 'Tablet Analytics' },
  { id: 'ask', label: 'Ask' },
]

export default function App() {
  const [tab, setTab] = useState('recommend')

  return (
    <div className="app">
      <header className="masthead">
        <div>
          <div className="masthead__runner">
            <span>GSMArena</span>
            <span>Star schema · MariaDB 10.11</span>
            <span>22 brands · 7k+ devices</span>
          </div>
          <h1 className="masthead__title">
            The Smartphone <em>Catalogue</em>
          </h1>
        </div>
        <div className="masthead__issue">
          <span>Vol. 02</span>
          <strong>№ 22</strong>
          <span>CIS 761 / Spring</span>
        </div>
      </header>
      <p className="masthead__deck">
        A typed query surface, a printed analytics gazette, and a natural-language
        oracle — three readings of the same star schema, served from a single
        read-only connection.
      </p>

      <nav className="tabs" aria-label="Catalogue sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            aria-pressed={tab === t.id}
            className={`tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'recommend' && <RecommendView />}
      {/* `key` forces a remount when switching form factor so all useEndpoint
          calls re-fire with the new param instead of reusing stale state. */}
      {tab === 'analytics-phone' && <AnalyticsView key="phone" formFactor="phone" />}
      {tab === 'analytics-watch' && <AnalyticsView key="watch" formFactor="watch" />}
      {tab === 'analytics-tablet' && <AnalyticsView key="tablet" formFactor="tablet" />}
      {tab === 'ask' && <AskView />}
    </div>
  )
}
