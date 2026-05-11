import { useState } from 'react'

import { humanizeColumnName } from '../utils/format.js'

export { humanizeColumnName }

function ErrorPanel({ error }) {
  if (error.kind === 'plain') {
    return <div className="error">{error.message}</div>
  }
  // pipeline_failure: render the structured attempt history.
  return (
    <div className="card" style={{ borderLeft: '3px solid #e07070' }}>
      <h3 style={{ marginTop: 0, color: '#ffb3b3' }}>Ask pipeline gave up</h3>
      <p style={{ marginTop: 0 }}>{error.message}</p>
      {error.lastError && (
        <p style={{ color: '#ffb3b3', fontSize: '0.9rem' }}>
          Last error: <code>{error.lastError}</code>
        </p>
      )}
      <details>
        <summary style={{ cursor: 'pointer', color: '#9aa3ad' }}>
          Show {error.attempts.length} attempt{error.attempts.length === 1 ? '' : 's'}
        </summary>
        {error.attempts.map((a, i) => (
          <div key={i} style={{ marginTop: '0.6rem' }}>
            <div style={{ color: '#9aa3ad', fontSize: '0.8rem' }}>
              Attempt {i + 1}
              <span style={{ marginLeft: '0.4rem', padding: '0.05rem 0.4rem', borderRadius: 4,
                             background: a.kind === 'review' ? '#2a3a4a' : '#3a2a2a',
                             color: a.kind === 'review' ? '#9bd1ff' : '#ffb3b3' }}>
                {a.kind}
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

// The four canonical pipeline stages we show in the progress strip. The
// 'executing' stage matches `executing_sql` (emitted by the backend right
// after _streamed_chat returns) and `__executing__` (synthesised on the
// frontend from the `executed` event as a no-event-gap fallback).
const PIPELINE_STAGES = [
  { key: 'generating', label: 'Generating SQL', match: ['generating_sql', 'retrying_sql', 'refining_sql'] },
  { key: 'executing',  label: 'Executing SQL', match: ['executing_sql', '__executing__'] },
  { key: 'reviewing',  label: 'Reviewing',     match: ['reviewing'] },
  { key: 'explaining', label: 'Explaining',    match: ['explaining'] },
]

const SQL_GENERATING_PHASES = new Set(['generating_sql', 'retrying_sql', 'refining_sql'])

// Pull the SQL out of a fenced ```sql … ``` block. Falls back to the raw
// text (stripped) so a partially-arrived block still resolves to something
// useful when the phase advances mid-emit.
function extractSqlFromPartial(partial) {
  if (!partial) return ''
  const m = partial.match(/```(?:sql)?\s*([\s\S]*?)```/i)
  if (m) return m[1].trim()
  // Open fence without close — strip the opening fence prefix if present
  const openOnly = partial.match(/```(?:sql)?\s*([\s\S]*)$/i)
  if (openOnly) return openOnly[1].trim()
  return partial.trim()
}

function stageIndexFor(phase) {
  return PIPELINE_STAGES.findIndex((s) => s.match.includes(phase))
}

function PipelineProgress({ answer, finalised }) {
  // Resolve the active phase:
  //   - finalised → no active stage (everything below renders as done)
  //   - answer has a phase → that one
  //   - mid-fetch but no events yet → assume 'generating_sql' so the strip
  //     doesn't appear inert in the first second after submission.
  let phase
  if (finalised) phase = null
  else if (answer?.phase) phase = answer.phase
  else phase = 'generating_sql'
  const activeIdx = phase ? stageIndexFor(phase) : -1
  return (
    <div className="card" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.6rem 0.9rem' }}>
      {PIPELINE_STAGES.map((stage, i) => {
        let status
        if (finalised) {
          status = 'done'
        } else if (activeIdx === -1) {
          status = 'pending'
        } else if (i < activeIdx) {
          status = 'done'
        } else if (i === activeIdx) {
          status = 'active'
        } else {
          status = 'pending'
        }
        const color = status === 'done' ? '#62c699'
                    : status === 'active' ? '#9bd1ff' : '#5a6168'
        const bg = status === 'active' ? '#1d2531' : 'transparent'
        const icon = status === 'done' ? '✓' : status === 'active' ? '⟳' : '·'
        return (
          <span key={stage.key} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <span
              data-testid={`pipeline-stage-${stage.key}`}
              data-status={status}
              style={{
                color, background: bg, fontSize: '0.85rem',
                padding: '0.25rem 0.6rem', borderRadius: 999,
                border: `1px solid ${status === 'active' ? '#2a3a4a' : 'transparent'}`,
              }}
            >
              <span style={{
                display: 'inline-block', marginRight: '0.35rem',
                animation: status === 'active' ? 'blink 1s step-end infinite' : 'none',
              }}>{icon}</span>
              {stage.label}
            </span>
            {i < PIPELINE_STAGES.length - 1 && (
              <span style={{ color: '#3a3f47', fontSize: '0.75rem' }}>›</span>
            )}
          </span>
        )
      })}
    </div>
  )
}

// Process one NDJSON event from /api/ask/stream against the partial-answer
// state. Returns the next answer state, or null if the event isn't relevant.
function applyEvent(prev, ev) {
  const base = prev || {
    question: '', sql: '', columns: [], rows: [], attempts: [],
    raw_llm_response: '', explanation: null, truncated: false,
    phase: null, partialSql: '', partialExplanation: '',
  }
  switch (ev.type) {
    case 'phase': {
      // Entering a new pipeline phase. Two transitions need special care:
      //   - From an SQL-streaming phase into anything else (typically
      //     `executing_sql`): the partial buffer holds the full ```sql…```
      //     block, so we lift it into `answer.sql` here. This is what makes
      //     the caret disappear the moment generation ends, even if the
      //     downstream DB call hasn't fired yet.
      //   - Into an SQL-streaming phase: reset both buffers so old tokens
      //     don't bleed into a fresh attempt.
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
      // Accumulate model tokens into the right buffer based on phase.
      if (ev.phase === 'explaining') {
        return { ...base, partialExplanation: (base.partialExplanation || '') + ev.content }
      }
      return { ...base, partialSql: (base.partialSql || '') + ev.content }
    case 'attempt':
      return { ...base, attempts: [...base.attempts, ev.attempt] }
    case 'executed':
      // Render rows immediately so the user sees the result before the
      // review/explanation turns finish. Set a synthetic phase so the
      // pipeline-progress strip advances past 'Generating SQL' into
      // 'Executing SQL' until the next real phase event arrives.
      return {
        ...base,
        sql: ev.sql,
        columns: ev.columns,
        rows: ev.rows,
        truncated: !!ev.truncated,
        partialSql: '',  // SQL is now finalised; clear the streaming buffer
        phase: '__executing__',
      }
    case 'result':
      // Replace state with the final accepted answer (carries explanation).
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

      // Streaming path: incremental NDJSON events.
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

      // Fallback: legacy non-streaming response (or test mocks without body).
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', marginTop: '0.6rem' }}>
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
              onClick={resetSession}
              style={{
                background: 'transparent', border: '1px solid #444', color: '#9aa3ad',
                padding: '0.3rem 0.7rem', borderRadius: 4, cursor: 'pointer', fontSize: '0.85rem',
              }}
            >
              Reset conversation
            </button>
          )}
          {sessionId && (
            <span style={{ color: '#6a737d', fontSize: '0.75rem', fontFamily: 'monospace' }}>
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
            <h3 style={{ marginTop: 0 }}>
              Generated SQL
              {loading && answer.phase && PHASE_LABELS[answer.phase] && (
                <span style={{ marginLeft: '0.6rem', fontSize: '0.8rem', color: '#9bd1ff' }}>
                  · {PHASE_LABELS[answer.phase]}
                </span>
              )}
              {answer.attempts && answer.attempts.length > 1 && (
                <span style={{ marginLeft: '0.6rem', fontSize: '0.8rem', color: '#f0c674' }}>
                  · {answer.attempts.length} attempts ({summariseAttempts(answer.attempts)})
                </span>
              )}
            </h3>
            {/* Prefer the finalised `sql` once we've got it; otherwise show
                the tokens streaming in with a blinking caret. */}
            <pre className="sql">
              {answer.sql || answer.partialSql || ''}
              {!answer.sql && answer.partialSql !== undefined && answer.partialSql !== '' && (
                <span style={{ animation: 'blink 1s step-end infinite' }}>▌</span>
              )}
            </pre>
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
            <h3 style={{ marginTop: 0 }}>
              Result · {answer.rows.length} row{answer.rows.length === 1 ? '' : 's'}
              {answer.truncated && (
                <span style={{ marginLeft: '0.6rem', fontSize: '0.78rem', color: '#f0c674' }}>
                  · truncated to row cap
                </span>
              )}
            </h3>
            {(answer.explanation || answer.partialExplanation) && (
              <div style={{
                background: '#1d2531', border: '1px solid #2a3a4a',
                borderLeft: '3px solid #6aa9ff', borderRadius: 4,
                padding: '0.7rem 0.9rem', marginBottom: '0.8rem',
                color: '#cfdaeb', fontSize: '0.95rem', lineHeight: 1.45,
              }}>
                <div style={{ color: '#9bd1ff', fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.3rem' }}>
                  LLM explanation
                </div>
                {answer.explanation || answer.partialExplanation}
                {!answer.explanation && answer.partialExplanation && (
                  <span style={{ animation: 'blink 1s step-end infinite' }}>▌</span>
                )}
              </div>
            )}
            {answer.rows.length === 0 ? (
              <p style={{ color: '#9aa3ad' }}>No rows.</p>
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
