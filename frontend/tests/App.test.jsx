import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import App from '../src/App.jsx'

describe('App tab navigation', () => {
  it('renders the three tabs', async () => {
    render(<App />)
    // findBy* waits for pending state updates to flush, avoiding act() warnings
    // from RecommendView's mount-time fetch.
    expect(await screen.findByRole('button', { name: /recommend/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /analytics/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^ask$/i })).toBeInTheDocument()
  })

  it('starts on Recommend tab', async () => {
    render(<App />)
    const recommendTab = await screen.findByRole('button', { name: /recommend/i })
    expect(recommendTab.className).toMatch(/active/)
  })

  it('switches to Analytics tab on click', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: /analytics/i }))
    const analyticsTab = screen.getByRole('button', { name: /analytics/i })
    expect(analyticsTab.className).toMatch(/active/)
  })

  it('switches to Ask tab on click', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: /^ask$/i }))
    expect(screen.getByPlaceholderText(/Xiaomi/i)).toBeInTheDocument()
  })
})
