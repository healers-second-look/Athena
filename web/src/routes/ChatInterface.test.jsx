import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/chatClient.js', () => ({
  createSession: vi.fn(),
  listSessions: vi.fn(),
  getSession: vi.fn(),
  updateSession: vi.fn(),
  deleteSession: vi.fn(),
  sendTurn: vi.fn(),
  getModels: vi.fn(),
  getAttachments: vi.fn(),
  getContexts: vi.fn(),
  getContextGraph: vi.fn(),
}))

import ChatInterface from './ChatInterface.jsx'
import {
  getAttachments,
  getContexts,
  getModels,
  getSession,
  listSessions,
} from '../api/chatClient.js'

const SESSION_ID = 'sess-1'

const MODELS = [
  { id: 'mock-outline', label: 'Athena Outline (offline)', available: true },
  { id: 'mock-terse', label: 'Athena Terse (offline)', available: true },
]
const ATTACHMENTS = [
  { id: 'citation-guard', label: 'Citation guard', kind: 'plugin', description: '' },
]

function assistantTurn(extra) {
  return {
    id: 'm2',
    role: 'assistant',
    content: 'an answer',
    sources: [],
    notes: [],
    entities: {},
    context_lines: [],
    ...extra,
  }
}

function session(history) {
  return {
    id: SESSION_ID,
    model_id: 'mock-outline',
    attachment_ids: [],
    context_id: null,
    history,
  }
}

function renderChat() {
  return render(
    <MemoryRouter initialEntries={[`/chat/${SESSION_ID}`]}>
      <Routes>
        <Route path="/chat/:id" element={<ChatInterface />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  listSessions.mockResolvedValue([])
  getModels.mockResolvedValue(MODELS)
  getAttachments.mockResolvedValue(ATTACHMENTS)
  getContexts.mockResolvedValue([])
  getSession.mockResolvedValue(session([]))
})

describe('an unreachable backend is reported, not papered over', () => {
  it('says the catalogs could not be loaded', async () => {
    getModels.mockRejectedValue(new Error('Failed to fetch'))
    getAttachments.mockRejectedValue(new Error('Failed to fetch'))
    getContexts.mockRejectedValue(new Error('Failed to fetch'))

    renderChat()
    expect(await screen.findByText(/Session options unavailable/i)).toBeInTheDocument()
    expect(screen.getByText(/it is a connection failure/i)).toBeInTheDocument()
  })

  it('does not substitute a hardcoded model list that drifts from the registry', async () => {
    // The old fallback rendered a working-looking picker while the backend
    // was down, so the user configured a session against options that were
    // not really there and only found out on send.
    getModels.mockRejectedValue(new Error('Failed to fetch'))
    getAttachments.mockRejectedValue(new Error('Failed to fetch'))
    getContexts.mockRejectedValue(new Error('Failed to fetch'))

    renderChat()
    await screen.findByText(/Session options unavailable/i)
    expect(screen.queryByRole('option', { name: /Athena Outline/i })).toBeNull()
  })

  it('shows no outage banner when the catalogs load', async () => {
    renderChat()
    await waitFor(() => expect(getModels).toHaveBeenCalled())
    expect(screen.queryByText(/Session options unavailable/i)).toBeNull()
  })
})

describe('Phase 6 — a failed evidence search is not a finding of no evidence', () => {
  it('labels an outage instead of reporting an empty result', async () => {
    getSession.mockResolvedValue(
      session([
        { id: 'm1', role: 'user', content: 'EGFR T790M?' },
        assistantTurn({
          retrieval_failed: true,
          retrieval_error: 'FalkorDB unreachable: connection refused',
        }),
      ]),
    )

    renderChat()
    expect(await screen.findByText(/Evidence search could not be run/i)).toBeInTheDocument()
    expect(screen.getByText(/FalkorDB unreachable/i)).toBeInTheDocument()
    expect(screen.getByText(/not.*a finding that no evidence exists/i)).toBeInTheDocument()
  })

  it('reports a genuinely empty search as a search that ran', async () => {
    getSession.mockResolvedValue(
      session([
        { id: 'm1', role: 'user', content: 'EGFR T790M?' },
        assistantTurn({ retrieval_failed: false }),
      ]),
    )

    renderChat()
    expect(await screen.findByText(/matched no sources for this turn/i)).toBeInTheDocument()
    expect(screen.queryByText(/could not be run/i)).toBeNull()
  })
})
