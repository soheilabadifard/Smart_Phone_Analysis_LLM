import { useState } from 'react'
import RecommendView from './views/RecommendView.jsx'
import AnalyticsView from './views/AnalyticsView.jsx'
import AskView from './views/AskView.jsx'

const TABS = [
  { id: 'recommend', label: 'Recommend' },
  { id: 'analytics', label: 'Analytics' },
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
      {tab === 'analytics' && <AnalyticsView />}
      {tab === 'ask' && <AskView />}
    </div>
  )
}
