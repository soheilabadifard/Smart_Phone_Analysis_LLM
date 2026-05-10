import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import AskView from '../src/views/AskView.jsx'

describe('AskView', () => {
  it('renders the input + suggestion pills', () => {
    render(<AskView />)
    expect(screen.getByPlaceholderText(/Xiaomi/i)).toBeInTheDocument()
    expect(screen.getByText(/highest average phone price/i)).toBeInTheDocument()
  })

  it('submits a question and renders the SQL + result table', async () => {
    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          question: 'list brands',
          sql: 'SELECT brand FROM Device_Name',
          columns: ['brand'],
          rows: [{ brand: 'Apple' }, { brand: 'Samsung' }],
          attempts: [{ sql: 'SELECT brand FROM Device_Name', error: null, succeeded: true }],
          raw_llm_response: '```sql\nSELECT brand FROM Device_Name\n```',
        }),
    }))

    const user = userEvent.setup()
    render(<AskView />)
    await user.type(screen.getByPlaceholderText(/Xiaomi/i), 'list brands')
    await user.click(screen.getByRole('button', { name: /^ask$/i }))

    await waitFor(() => screen.getByText(/Generated SQL/i))
    expect(screen.getByText(/SELECT brand FROM Device_Name/i)).toBeInTheDocument()
    expect(screen.getByText('Apple')).toBeInTheDocument()
    expect(screen.getByText('Samsung')).toBeInTheDocument()
  })

  it('shows the self-correction badge after retries', async () => {
    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          question: 'q',
          sql: 'SELECT 1 AS one',
          columns: ['one'],
          rows: [{ one: 1 }],
          attempts: [
            { sql: 'DROP TABLE Device', error: 'Refused unsafe SQL', succeeded: false, kind: 'execution' },
            { sql: 'SELECT 1 AS one', error: null, succeeded: true, kind: 'execution' },
          ],
          raw_llm_response: '',
        }),
    }))

    const user = userEvent.setup()
    render(<AskView />)
    await user.type(screen.getByPlaceholderText(/Xiaomi/i), 'q')
    await user.click(screen.getByRole('button', { name: /^ask$/i }))

    await waitFor(() => screen.getByText(/2 attempts \(2 executions\)/))
    expect(screen.getByText(/Show 1 earlier attempt/)).toBeInTheDocument()
  })

  it('shows review judgment when verification approves', async () => {
    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          question: 'q',
          sql: 'SELECT brand FROM Device_Name LIMIT 1',
          columns: ['brand'],
          rows: [{ brand: 'Apple' }],
          attempts: [
            { sql: 'SELECT brand FROM Device_Name LIMIT 1', succeeded: true, kind: 'execution' },
            { sql: 'SELECT brand FROM Device_Name LIMIT 1', succeeded: true, kind: 'review', judgment: 'OK' },
          ],
          raw_llm_response: 'OK',
        }),
    }))

    const user = userEvent.setup()
    render(<AskView />)
    await user.type(screen.getByPlaceholderText(/Xiaomi/i), 'q')
    await user.click(screen.getByRole('button', { name: /^ask$/i }))

    await waitFor(() => screen.getByText(/2 attempts \(1 execution, 1 review\)/))
    // Open the details to see the judgment
    await user.click(screen.getByText(/Show 1 earlier attempt/))
  })

  it('shows error banner on backend failure', async () => {
    global.fetch = vi.fn(async () => ({
      ok: false,
      status: 400,
      text: async () => '{"detail":"bad"}',
      json: async () => ({ detail: 'bad' }),
    }))

    const user = userEvent.setup()
    render(<AskView />)
    await user.type(screen.getByPlaceholderText(/Xiaomi/i), 'oh no')
    await user.click(screen.getByRole('button', { name: /^ask$/i }))

    await waitFor(() => {
      expect(screen.getByText(/bad/)).toBeInTheDocument()
    })
  })
})
