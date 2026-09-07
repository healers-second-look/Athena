import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from './App.jsx'

describe('App routing (Issue #123)', () => {
  it('redirects root / to the primary case dashboard rather than chat', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )

    // Should render the case dashboard (diff / change review primary entry point)
    expect(await screen.findByRole('link', { name: /Research chat/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Research queue/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Patient timeline/i })).toBeInTheDocument()
  })

  it('keeps /chat reachable as a secondary research surface', async () => {
    render(
      <MemoryRouter initialEntries={['/chat']}>
        <App />
      </MemoryRouter>,
    )

    expect(screen.getByText('Clinical Evidence, Synthesized')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Start a New Chat/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Case Review/i })).toBeInTheDocument()
  })
})
