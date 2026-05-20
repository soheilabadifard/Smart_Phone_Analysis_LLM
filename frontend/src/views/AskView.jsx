import { useState } from 'react'

import { humanizeColumnName } from '../utils/format.js'

export { humanizeColumnName }

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

function ErrorPanel({ error }) {
  if (error.kind === 'plain') {
    return <div className="error">{error.message}</div>
  }
  // pipeline_failure: render the structured attempt history.
  return (
    <div className="card" style={{ borderTop: `2px solid var(--vermilion)`, paddingTop: '1.2rem' }}>
      <h3 style={{ color: 'var(--vermilion-dk)' }}>Ask pipeline gave up</h3>
      <p style={{ fontFamily: 'var(--font-display)', fontStyle: 'italic', color: 'var(--ink)' }}>{error.message}</p>
      {error.lastError && (
        <p style={{ color: 'var(--vermilion-dk)', fontFamily: 'var(--font-mono)', fontSize: '0.84rem' }}>
          Last error: <code>{error.lastError}</code>
        </p>
      )}
      <details>
        <summary>
          Show {error.attempts.length} attempt{error.attempts.length === 1 ? '' : 's'}
        </summary>
        {error.attempts.map((a, i) => (
          <div key={i} style={{ marginTop: '0.85rem' }}>
            <div style={{ color: 'var(--ink-mute)', fontSize: '0.72rem', fontFamily: 'var(--font-mono)', letterSpacing: '0.14em', textTransform: 'uppercase' }}>
              Attempt {(i + 1).toString().padStart(2, '0')}
              <span className={`kind-badge kind-badge--${a.kind === 'review' ? 'review' : 'execution'}`}>
                {a.kind}
              </span>
            </div>
            <pre className="sql" style={{ opacity: 0.85 }}>{a.sql}</pre>
            {a.error && <div className="error" style={{ marginTop: '0.3rem' }}>{a.error}</div>}
            {a.judgment && (
              <div style={{ marginTop: '0.4rem', color: 'var(--indigo)', fontStyle: 'italic', fontSize: '0.9rem', fontFamily: 'var(--font-display)' }}>
                LLM judgment: {a.judgment}
              </div>
            )}
          </div>
        ))}
      </details>
    </div>
  )
}


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

const PHASE_LABELS = {
  generating_sql: 'Generating SQL…',
  retrying_sql:   'Retrying after an error…',
  refining_sql:   'Refining SQL…',
  reviewing:      'Reviewing result…',
  explaining:     'Writing explanation…',
}

const PIPELINE_STAGES = [
  { key: 'generating', label: 'Generating SQL', match: ['generating_sql', 'retrying_sql', 'refining_sql'] },
  { key: 'executing',  label: 'Executing SQL', match: ['executing_sql', '__executing__'] },
  { key: 'reviewing',  label: 'Reviewing',     match: ['reviewing'] },
  { key: 'explaining', label: 'Explaining',    match: ['explaining'] },
]

const SQL_GENERATING_PHASES = new Set(['generating_sql', 'retrying_sql', 'refining_sql'])

function extractSqlFromPartial(partial) {
  if (!partial) return ''
  const m = partial.match(/```(?:sql)?\s*([\s\S]*?)```/i)
  if (m) return m[1].trim()
  const openOnly = partial.match(/```(?:sql)?\s*([\s\S]*)$/i)
  if (openOnly) return openOnly[1].trim()
  return partial.trim()
}

function stageIndexFor(phase) {
  return PIPELINE_STAGES.findIndex((s) => s.match.includes(phase))
}

function PipelineProgress({ answer, finalised }) {
  let phase
  if (finalised) phase = null
  else if (answer?.phase) phase = answer.phase
  else phase = 'generating_sql'
  const activeIdx = phase ? stageIndexFor(phase) : -1
  return (
    <div className="pipeline">
      {PIPELINE_STAGES.map((stage, i) => {
        let status
        if (finalised) status = 'done'
        else if (activeIdx === -1) status = 'pending'
        else if (i < activeIdx) status = 'done'
        else if (i === activeIdx) status = 'active'
        else status = 'pending'
        const icon = status === 'done' ? '✓' : status === 'active' ? '◐' : '○'
        return (
          <span key={stage.key} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.45rem' }}>
            <span
              className="pipeline__pill"
              data-testid={`pipeline-stage-${stage.key}`}
              data-status={status}
            >
              <span
                className="pipeline__icon"
                style={{ animation: status === 'active' ? 'blink 1s step-end infinite' : 'none' }}
              >{icon}</span>
              {stage.label}
            </span>
            {i < PIPELINE_STAGES.length - 1 && (
              <span className="pipeline__sep">/</span>
            )}
          </span>
        )
      })}
    </div>
  )
}

function applyEvent(prev, ev) {
  const base = prev || {
    question: '', sql: '', columns: [], rows: [], attempts: [],
    raw_llm_response: '', explanation: null, truncated: false,
    phase: null, partialSql: '', partialExplanation: '',
  }
  switch (ev.type) {
    case 'phase': {
      const wasGenerating = SQL_GENERATING_PHASES.has(base.phase)
      const goingToGenerate = SQL_GENERATING_PHASES.has(ev.phase)
      let next = { ...base, phase: ev.phase }
      if (wasGenerating && !goingToGenerate) {
        const finalised = extractSqlFromPartial(base.partialSql)
        if (finalised) next.sql = finalised
        next.partialSql = ''
      }
      if (goingToGenerate) {
        next.partialSql = ''
        next.sql = ''
      }
      if (ev.phase === 'explaining') {
        next.partialExplanation = ''
      }
      return next
    }
    case 'sql_token':
      if (ev.phase === 'explaining') {
        return { ...base, partialExplanation: (base.partialExplanation || '') + ev.content }
      }
      return { ...base, partialSql: (base.partialSql || '') + ev.content }
    case 'attempt':
      return { ...base, attempts: [...base.attempts, ev.attempt] }
    case 'executed':
      return {
        ...base,
        sql: ev.sql,
        columns: ev.columns,
        rows: ev.rows,
        truncated: !!ev.truncated,
        partialSql: '',
        phase: '__executing__',
      }
    case 'result':
      return {
        question: ev.question, sql: ev.sql,
        columns: ev.columns, rows: ev.rows,
        attempts: ev.attempts || base.attempts,
        raw_llm_response: ev.raw_llm_response,
        explanation: ev.explanation,
        truncated: !!ev.truncated,
        phase: null, partialSql: '', partialExplanation: '',
      }
    default:
      return null
  }
}


async function* readNdjson(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.trim()) yield JSON.parse(line)
    }
  }
  if (buffer.trim()) yield JSON.parse(buffer)
}


export default function AskView() {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [sessionId, setSessionId] = useState(null)
  const [streaming, setStreaming] = useState(false)

  const submit = async (e) => {
    e?.preventDefault()
    if (!question.trim()) return
    setLoading(true)
    setError(null)
    setAnswer(null)
    setStreaming(false)

    const body = JSON.stringify({ question, session_id: sessionId })
    const headers = { 'Content-Type': 'application/json' }

    try {
      const res = await fetch('/api/ask/stream', { method: 'POST', headers, body })

      if (res.ok && res.body && typeof res.body.getReader === 'function') {
        setStreaming(true)
        let partial = null
        for await (const ev of readNdjson(res)) {
          if (ev.type === 'session') {
            setSessionId(ev.session_id)
            continue
          }
          if (ev.type === 'error') {
            setError({
              kind: 'pipeline_failure',
              message: ev.message,
              lastError: ev.last_error || null,
              attempts: ev.attempts || [],
            })
            continue
          }
          const next = applyEvent(partial, ev)
          if (next) {
            partial = next
            setAnswer(next)
          }
        }
        setStreaming(false)
        return
      }

      const text = await res.text()
      let parsed
      try {
        parsed = JSON.parse(text)
      } catch (parseErr) {
        throw new Error(
          `Backend returned a response that wasn't JSON (${parseErr.message}). ` +
          `First 200 chars: ${text.slice(0, 200)}`
        )
      }
      if (!res.ok) {
        const detail = parsed?.detail ?? parsed
        if (detail && typeof detail === 'object' && Array.isArray(detail.attempts)) {
          setError({
            kind: 'pipeline_failure',
            message: detail.message || 'The Ask pipeline failed.',
            lastError: detail.last_error || null,
            attempts: detail.attempts,
          })
          if (detail.session_id) setSessionId(detail.session_id)
        } else {
          setError({ kind: 'plain', message: typeof detail === 'string' ? detail : text })
        }
        return
      }
      setAnswer(parsed)
      if (parsed.session_id) setSessionId(parsed.session_id)
    } catch (err) {
      setError({ kind: 'plain', message: String(err) })
    } finally {
      setLoading(false)
      setStreaming(false)
    }
  }

  const resetSession = async () => {
    if (!sessionId) return
    try {
      await fetch(`/api/ask/session/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
    } catch (err) {
      // best-effort; clear locally regardless
    }
    setSessionId(null)
    setAnswer(null)
    setError(null)
  }

  return (
    <div>
      <SectionHeader
        no="07"
        kicker="Natural-language oracle · NL → SQL → result"
        title="Ask the catalogue"
      />

      <form className="card" onSubmit={submit} style={{ borderTop: 'none', paddingTop: 0 }}>
        <label>
          Pose a question in plain English
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. Which Xiaomi phones in 2023 cost under 400 EUR?"
            style={{
              fontSize: '1.15rem',
              padding: '0.85rem 0.1rem',
              fontFamily: 'var(--font-display)',
              fontStyle: 'italic',
              fontWeight: 400,
              letterSpacing: '-0.012em',
              borderBottom: '2px solid var(--ink)',
              marginTop: '0.5rem',
            }}
          />
        </label>
        <div style={{ marginTop: '0.9rem', display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              type="button"
              className="chip"
              onClick={() => setQuestion(s)}
            >
              {s}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.9rem', marginTop: '1rem', flexWrap: 'wrap' }}>
          <button className="primary" type="submit" disabled={loading}>
            {loading
              ? (answer?.phase && PHASE_LABELS[answer.phase]
                 ? PHASE_LABELS[answer.phase]
                 : (streaming ? 'Connecting…' : 'Thinking…'))
              : (sessionId ? 'Ask (continues conversation)' : 'Ask')}
          </button>
          {sessionId && (
            <button
              type="button"
              className="ghost"
              onClick={resetSession}
            >
              Reset conversation
            </button>
          )}
          {sessionId && (
            <span style={{ color: 'var(--ink-mute)', fontSize: '0.74rem', fontFamily: 'var(--font-mono)', letterSpacing: '0.05em' }}>
              session: {sessionId.slice(0, 8)}…
            </span>
          )}
        </div>
      </form>

      {error && <ErrorPanel error={error} />}

      {(loading || answer) && (
        <PipelineProgress answer={answer} finalised={!loading && !!answer} />
      )}

      {answer && (
        <>
          <div className="card">
            <h3>
              Generated SQL
              {loading && answer.phase && PHASE_LABELS[answer.phase] && (
                <span style={{ fontSize: '0.78rem', color: 'var(--indigo)', fontFamily: 'var(--font-mono)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
                  · {PHASE_LABELS[answer.phase]}
                </span>
              )}
              {answer.attempts && answer.attempts.length > 1 && (
                <span style={{ fontSize: '0.74rem', color: 'var(--ochre)', fontFamily: 'var(--font-mono)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
                  · {answer.attempts.length} attempts ({summariseAttempts(answer.attempts)})
                </span>
              )}
            </h3>
            <pre className="sql">
              {answer.sql || answer.partialSql || ''}
              {!answer.sql && answer.partialSql !== undefined && answer.partialSql !== '' && (
                <span style={{ animation: 'blink 1s step-end infinite', color: 'var(--vermilion)' }}>▌</span>
              )}
            </pre>
            {answer.attempts && answer.attempts.length > 1 && (
              <details style={{ marginTop: '0.6rem' }}>
                <summary>
                  Show {answer.attempts.length - 1} earlier attempt{answer.attempts.length - 1 === 1 ? '' : 's'}
                </summary>
                {answer.attempts.slice(0, -1).map((a, i) => (
                  <div key={i} style={{ marginTop: '0.85rem' }}>
                    <div style={{ color: 'var(--ink-mute)', fontSize: '0.72rem', fontFamily: 'var(--font-mono)', letterSpacing: '0.14em', textTransform: 'uppercase' }}>
                      Attempt {(i + 1).toString().padStart(2, '0')}
                      <span className={`kind-badge kind-badge--${a.kind === 'review' ? 'review' : 'execution'}`}>
                        {a.kind === 'review' ? 'review' : 'execution'}
                      </span>
                    </div>
                    <pre className="sql" style={{ opacity: 0.85 }}>{a.sql}</pre>
                    {a.error && <div className="error" style={{ marginTop: '0.3rem' }}>{a.error}</div>}
                    {a.judgment && (
                      <div style={{ marginTop: '0.4rem', color: 'var(--indigo)', fontStyle: 'italic', fontSize: '0.9rem', fontFamily: 'var(--font-display)' }}>
                        LLM judgment: {a.judgment}
                      </div>
                    )}
                  </div>
                ))}
              </details>
            )}
          </div>
          <div className="card">
            <h3>
              Result
              <span style={{ color: 'var(--ink-mute)', fontFamily: 'var(--font-mono)', fontSize: '0.78rem', letterSpacing: '0.12em', textTransform: 'uppercase' }}>
                · {answer.rows.length} row{answer.rows.length === 1 ? '' : 's'}
              </span>
              {answer.truncated && (
                <span style={{ fontSize: '0.74rem', color: 'var(--ochre)', fontFamily: 'var(--font-mono)', letterSpacing: '0.1em', textTransform: 'uppercase' }}>
                  · truncated to row cap
                </span>
              )}
            </h3>
            {(answer.explanation || answer.partialExplanation) && (
              <div className="callout-explanation">
                {answer.explanation || answer.partialExplanation}
                {!answer.explanation && answer.partialExplanation && (
                  <span style={{ animation: 'blink 1s step-end infinite' }}>▌</span>
                )}
              </div>
            )}
            {answer.rows.length === 0 ? (
              <p style={{ color: 'var(--ink-mute)', fontStyle: 'italic', fontFamily: 'var(--font-display)', fontSize: '1rem' }}>No rows.</p>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>{answer.columns.map((c) => (<th key={c}>{humanizeColumnName(c)}</th>))}</tr>
                  </thead>
                  <tbody>
                    {answer.rows.map((row, i) => (
                      <tr key={i}>
                        {answer.columns.map((c) => (
                          <td key={c} style={{ fontFamily: typeof row[c] === 'number' ? 'var(--font-mono)' : 'inherit' }}>
                            {row[c] === null ? '—' : String(row[c])}
                          </td>
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
