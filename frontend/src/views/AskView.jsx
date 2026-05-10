import { useState } from 'react'

function summariseAttempts(attempts) {
  const exec = attempts.filter((a) => a.kind !== 'review').length
  const review = attempts.filter((a) => a.kind === 'review').length
  const parts = []
  if (exec > 0) parts.push(`${exec} execution${exec === 1 ? '' : 's'}`)
  if (review > 0) parts.push(`${review} review${review === 1 ? '' : 's'}`)
  return parts.join(', ')
}

const SUGGESTIONS = [
  'Which 5 brands have the highest average phone price?',
  'List Samsung phones from 2023 with at least 8 GB RAM, sorted by battery.',
  'How has average RAM changed year over year since 2015?',
  'Which chipset manufacturer dominates phones priced under 300 EUR?',
]

export default function AskView() {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e?.preventDefault()
    if (!question.trim()) return
    setLoading(true)
    setError(null)
    setAnswer(null)
    try {
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })
      const text = await res.text()
      if (!res.ok) throw new Error(text)
      setAnswer(JSON.parse(text))
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <form className="card" onSubmit={submit}>
        <label>
          Ask a question about the smartphone database
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. Which Xiaomi phones in 2023 cost under 400 EUR?"
            style={{ fontSize: '1rem', padding: '0.7rem' }}
          />
        </label>
        <div style={{ marginTop: '0.6rem', display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setQuestion(s)}
              style={{
                background: '#1d2229', border: '1px solid #2a2f37', color: '#9aa3ad',
                padding: '0.3rem 0.6rem', borderRadius: 999, cursor: 'pointer', fontSize: '0.8rem',
              }}
            >
              {s}
            </button>
          ))}
        </div>
        <button className="primary" type="submit" disabled={loading}>
          {loading ? 'Thinking…' : 'Ask'}
        </button>
      </form>

      {error && <div className="error">{error}</div>}

      {answer && (
        <>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>
              Generated SQL
              {answer.attempts && answer.attempts.length > 1 && (
                <span style={{ marginLeft: '0.6rem', fontSize: '0.8rem', color: '#f0c674' }}>
                  · {answer.attempts.length} attempts ({summariseAttempts(answer.attempts)})
                </span>
              )}
            </h3>
            <pre className="sql">{answer.sql}</pre>
            {answer.attempts && answer.attempts.length > 1 && (
              <details style={{ marginTop: '0.6rem' }}>
                <summary style={{ cursor: 'pointer', color: '#9aa3ad' }}>
                  Show {answer.attempts.length - 1} earlier attempt{answer.attempts.length - 1 === 1 ? '' : 's'}
                </summary>
                {answer.attempts.slice(0, -1).map((a, i) => (
                  <div key={i} style={{ marginTop: '0.6rem' }}>
                    <div style={{ color: '#9aa3ad', fontSize: '0.8rem' }}>
                      Attempt {i + 1}
                      <span style={{ marginLeft: '0.4rem', padding: '0.05rem 0.4rem', borderRadius: 4,
                                     background: a.kind === 'review' ? '#2a3a4a' : '#3a2a2a',
                                     color: a.kind === 'review' ? '#9bd1ff' : '#ffb3b3' }}>
                        {a.kind === 'review' ? 'review' : 'execution'}
                      </span>
                    </div>
                    <pre className="sql" style={{ opacity: 0.7 }}>{a.sql}</pre>
                    {a.error && <div className="error" style={{ marginTop: '0.3rem' }}>{a.error}</div>}
                    {a.judgment && (
                      <div style={{ marginTop: '0.3rem', color: '#9bd1ff', fontStyle: 'italic', fontSize: '0.85rem' }}>
                        LLM judgment: {a.judgment}
                      </div>
                    )}
                  </div>
                ))}
              </details>
            )}
          </div>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Result · {answer.rows.length} row{answer.rows.length === 1 ? '' : 's'}</h3>
            {answer.explanation && (
              <div style={{
                background: '#1d2531', border: '1px solid #2a3a4a',
                borderLeft: '3px solid #6aa9ff', borderRadius: 4,
                padding: '0.7rem 0.9rem', marginBottom: '0.8rem',
                color: '#cfdaeb', fontSize: '0.95rem', lineHeight: 1.45,
              }}>
                <div style={{ color: '#9bd1ff', fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.3rem' }}>
                  LLM explanation
                </div>
                {answer.explanation}
              </div>
            )}
            {answer.rows.length === 0 ? (
              <p style={{ color: '#9aa3ad' }}>No rows.</p>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>{answer.columns.map((c) => (<th key={c}>{c}</th>))}</tr>
                  </thead>
                  <tbody>
                    {answer.rows.map((row, i) => (
                      <tr key={i}>
                        {answer.columns.map((c) => (
                          <td key={c}>{row[c] === null ? '—' : String(row[c])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
