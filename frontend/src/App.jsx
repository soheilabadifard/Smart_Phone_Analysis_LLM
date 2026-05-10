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
      <h1 style={{ marginTop: 0 }}>Smartphone Platform</h1>
      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
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
