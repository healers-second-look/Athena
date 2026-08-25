import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import ChatLanding from './ChatLanding.jsx'

describe('ChatLanding page', () => {
  it('renders brand, hero section, and CTA button', () => {
    render(
      <BrowserRouter>
        <ChatLanding />
      </BrowserRouter>,
    )

    expect(screen.getAllByText('Athena')[0]).toBeInTheDocument()
    expect(screen.getByText('Clinical Evidence, Synthesized')).toBeInTheDocument()
    expect(screen.getByText(/AI-powered research assistant grounded in real clinical evidence/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Start a New Chat/i })).toBeInTheDocument()
  })

  it('renders all three core feature cards', () => {
    render(
      <BrowserRouter>
        <ChatLanding />
      </BrowserRouter>,
    )

    expect(screen.getByText('Multi-Model Support')).toBeInTheDocument()
    expect(screen.getByText('Knowledge Graph Context')).toBeInTheDocument()
    expect(screen.getByText('Evidence Grading')).toBeInTheDocument()
  })
})
