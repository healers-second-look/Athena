import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DegradeNotice from './DegradeNotice.jsx'
import EmptyState from './EmptyState.jsx'
import ResearchQueue from '../routes/ResearchQueue.jsx'
import queue from '../../fixtures/queue.json'
import degradedQueue from '../../fixtures/queue-degraded.json'

vi.mock('../api/client.js', () => ({
  getQueue: vi.fn(),
  isFixtureBacked: () => true,
  DEMO_CASE_ID: '8c1d4e2a-0000-4000-8000-000000000a01',
}))
import { getQueue } from '../api/client.js'

const CASE_ID = '8c1d4e2a-0000-4000-8000-000000000a01'
const TRIALS_QUESTION = 'Are there recruiting trials matching EGFR T790M?'
// The one open question with no findings whose lanes were all reached. It is
// the control: same empty finding list, different reason, different sentence.
const ANSWERED_EMPTY_QUESTION = 'What resistance mechanisms are documented'

const FAILURE = {
  type: 'failure',
  tier: '1',
  lane: 'trials',
  reason: 'ClinicalTrials.gov lookup failed: connection timed out.',
  retryable: true,
  last_known_at: '2026-02-14T09:00:00Z',
}

function renderQueue(fixture) {
  getQueue.mockResolvedValue(structuredClone(fixture))
  return render(
    <MemoryRouter initialEntries={[`/cases/${CASE_ID}/queue`]}>
      <Routes>
        <Route path="/cases/:id/queue" element={<ResearchQueue />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('DegradeNotice — a failed lookup, labelled as one', () => {
  it('names the lane and the reason', () => {
    render(<DegradeNotice failure={FAILURE} />)
    expect(screen.getByText(/trials lookup unavailable/i)).toBeInTheDocument()
    expect(screen.getByText(/connection timed out/i)).toBeInTheDocument()
  })

  it('dates stale data and says it is not live', () => {
    render(<DegradeNotice failure={FAILURE} />)
    expect(screen.getByText(/2026-02-14/)).toBeInTheDocument()
    expect(screen.getByText(/not a live result/i)).toBeInTheDocument()
  })

  it('says so when there is no cached result, rather than implying a fresh empty', () => {
    render(<DegradeNotice failure={{ ...FAILURE, last_known_at: null }} />)
    expect(screen.getByText(/No cached result is available/i)).toBeInTheDocument()
    expect(screen.queryByText(/not a live result/i)).toBeNull()
  })

  it('distinguishes retryable from terminal', () => {
    const { unmount } = render(<DegradeNotice failure={FAILURE} />)
    expect(screen.getByText(/may succeed on retry/i)).toBeInTheDocument()
    unmount()
    render(<DegradeNotice failure={{ ...FAILURE, retryable: false }} />)
    expect(screen.getByText(/will not succeed on retry/i)).toBeInTheDocument()
  })

  it('renders a failure with no lane rather than dropping it', () => {
    // docs/api-contracts.md: a failure object is always rendered. A missing
    // optional field is not grounds to discard the whole notice.
    render(<DegradeNotice failure={{ ...FAILURE, lane: null }} />)
    expect(screen.getByText(/^Lookup unavailable$/i)).toBeInTheDocument()
  })

  it('is announced, not merely coloured', () => {
    const { container } = render(<DegradeNotice failure={FAILURE} />)
    expect(container.querySelector('[role="status"]')).not.toBeNull()
  })
})

describe('EmptyState — an empty panel that says why', () => {
  let consoleError
  beforeEach(() => {
    // React logs the render error itself; the assertion is the throw.
    consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => consoleError.mockRestore())

  it.each([undefined, null, '', '   '])('refuses to render without a reason (%s)', (reason) => {
    expect(() => render(<EmptyState reason={reason} />)).toThrow(/requires a reason/i)
  })

  it('renders the reason it was given', () => {
    render(<EmptyState reason="No trials matched — 0 candidates passed the filter." />)
    expect(screen.getByText(/0 candidates passed the filter/)).toBeInTheDocument()
  })
})

describe('§88.1 — the queue distinguishes "found nothing" from "never looked"', () => {
  it('reports no degrade on a healthy run', async () => {
    renderQueue(queue)
    await screen.findByText(/Open questions/i)
    expect(screen.queryByText(/Coverage/i)).toBeNull()
    expect(screen.queryByText(/lookup unavailable/i)).toBeNull()
  })

  it('surfaces the failed lane above the questions', async () => {
    const { container } = renderQueue(degradedQueue)
    await screen.findByText(/Coverage/i)
    const headings = [...container.querySelectorAll('h2')].map((h) => h.textContent)
    expect(headings.indexOf('Coverage')).toBeLessThan(headings.indexOf('Open questions'))
  })

  it('labels the unanswered question as a failed lookup, not an empty result', async () => {
    renderQueue(degradedQueue)
    const question = await screen.findByText(TRIALS_QUESTION)
    const card = question.closest('.q')
    expect(card.querySelector('.degraded')).not.toBeNull()
    expect(card.textContent).toMatch(/connection timed out/i)
    // The sentence that would be a lie here.
    expect(card.textContent).not.toMatch(/returned nothing/i)
  })

  it('still says "reached and returned nothing" for a question whose lanes were fine', async () => {
    // Same empty finding list as the trials question above. Different cause,
    // and the two must not read the same — that is the entire defect.
    renderQueue(degradedQueue)
    const question = await screen.findByText(new RegExp(ANSWERED_EMPTY_QUESTION))
    const card = question.closest('.q')
    expect(card.querySelector('.degraded')).toBeNull()
    expect(card.textContent).toMatch(/returned nothing/i)
  })

  it('keeps the failed lane’s question on the worklist', async () => {
    renderQueue(degradedQueue)
    expect(await screen.findByText(TRIALS_QUESTION)).toBeInTheDocument()
  })

  it('leaves the rest of the page — all local — intact', async () => {
    renderQueue(degradedQueue)
    await screen.findByText(/Coverage/i)
    expect(screen.getByText(/2 suppressed as already answered/)).toBeInTheDocument()
    expect(screen.getAllByText(/Triggered by:/).length).toBeGreaterThan(0)
  })
})
