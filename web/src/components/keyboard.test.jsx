import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ResearchQueue from '../routes/ResearchQueue.jsx'
import queue from '../../fixtures/queue.json'

vi.mock('../api/client.js', () => ({
  getQueue: vi.fn(),
  isFixtureBacked: () => true,
  DEMO_CASE_ID: '8c1d4e2a-0000-4000-8000-000000000a01',
}))
import { getQueue } from '../api/client.js'

const CASE_ID = '8c1d4e2a-0000-4000-8000-000000000a01'
const TOP = 'What resistance mechanisms are documented' // priority 4, sorts first

function renderQueue() {
  getQueue.mockResolvedValue(structuredClone(queue))
  return render(
    <MemoryRouter initialEntries={[`/cases/${CASE_ID}/queue`]}>
      <Routes>
        <Route path="/cases/:id/queue" element={<ResearchQueue />} />
      </Routes>
    </MemoryRouter>,
  )
}

// The rows. Found by class rather than role: they are deliberately plain
// list items (see ResearchQueue.jsx) because a listbox option may not contain
// interactive descendants, and these rows link to their findings.
const rows = () => [...document.querySelectorAll('li.q')]

// Focus the list the way Tab would, without encoding how many links happen to
// precede it in the document.
const focusList = (index = 0) => rows()[index].focus()

let alertSpy
beforeEach(() => {
  vi.clearAllMocks()
  alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {})
})
afterEach(() => alertSpy.mockRestore())

describe('the worklist is one tab stop, not one per question', () => {
  it('exposes exactly one focusable row at a time', async () => {
    renderQueue()
    await screen.findByText(new RegExp(TOP))
    const tabbable = rows().filter((el) => el.getAttribute('tabindex') === '0')
    expect(tabbable).toHaveLength(1)
    // Everything else stays programmatically focusable but out of the tab
    // sequence -- otherwise reaching the content below means tabbing through
    // every open question.
    expect(rows().length).toBeGreaterThan(1)
    rows()
      .filter((el) => el.getAttribute('tabindex') !== '0')
      .forEach((el) => expect(el).toHaveAttribute('tabindex', '-1'))
  })

  it('lands on the highest-priority question first', async () => {
    renderQueue()
    await screen.findByText(new RegExp(TOP))
    expect(rows()[0]).toHaveAttribute('tabindex', '0')
    expect(rows()[0].textContent).toMatch(new RegExp(TOP))
  })
})

describe('arrow keys move focus, and focus actually moves', () => {
  it('ArrowDown advances and takes DOM focus with it', async () => {
    const user = userEvent.setup()
    renderQueue()
    await screen.findByText(new RegExp(TOP))

    focusList()
    expect(rows()[0]).toHaveFocus()

    await user.keyboard('{ArrowDown}')
    expect(rows()[1]).toHaveFocus()
    // Moving the active index without moving real focus would announce
    // nothing to a screen reader.
    expect(rows()[1]).toHaveAttribute('tabindex', '0')
    expect(rows()[0]).toHaveAttribute('tabindex', '-1')
  })

  it('ArrowUp goes back, and does not wrap past the top', async () => {
    const user = userEvent.setup()
    renderQueue()
    await screen.findByText(new RegExp(TOP))
    focusList()

    await user.keyboard('{ArrowDown}{ArrowUp}{ArrowUp}')
    expect(rows()[0]).toHaveFocus()
  })

  it('End and Home reach both ends', async () => {
    const user = userEvent.setup()
    renderQueue()
    await screen.findByText(new RegExp(TOP))
    focusList()

    await user.keyboard('{End}')
    expect(rows()[rows().length - 1]).toHaveFocus()
    await user.keyboard('{Home}')
    expect(rows()[0]).toHaveFocus()
  })

  it('marks the active row for a screen reader', async () => {
    const user = userEvent.setup()
    renderQueue()
    await screen.findByText(new RegExp(TOP))
    focusList()
    await user.keyboard('{ArrowDown}')

    // Focusing the row is what announces it, so the row carries its own
    // description rather than relying on a reader stitching its children.
    expect(rows()[1].getAttribute('aria-label')).toContain('Priority')
    // Row 1 is the first priority-3 question, since the list is sorted by
    // priority descending. Read it off the row rather than hardcoding which
    // question that is, so a fixture reorder does not fail this for the
    // wrong reason.
    expect(rows()[1].getAttribute('aria-label')).toContain(
      rows()[1].querySelector('div:nth-of-type(2)').textContent,
    )
  })
})

describe('a decision cannot be recorded without a reason', () => {
  // The load-bearing test. #88: "A keyboard path that lets someone skip the
  // reason field would be worse than no keyboard path." Decision.reason is
  // NOT NULL in case/models.py, "required, even for investigating".

  async function arm(user, key = 'i') {
    renderQueue()
    await screen.findByText(new RegExp(TOP))
    focusList()
    await user.keyboard(key)
  }

  it('the action key opens a reason field instead of recording', async () => {
    const user = userEvent.setup()
    await arm(user)

    expect(screen.getByLabelText(/Reason \(required/i)).toBeInTheDocument()
    expect(alertSpy).not.toHaveBeenCalled()
  })

  it('focus moves into the reason field, so the next keystroke types', async () => {
    const user = userEvent.setup()
    await arm(user)
    expect(screen.getByLabelText(/Reason \(required/i)).toHaveFocus()
  })

  it('Enter on an empty reason records nothing', async () => {
    const user = userEvent.setup()
    await arm(user)

    await user.keyboard('{Enter}')
    expect(alertSpy).not.toHaveBeenCalled()
    expect(screen.getByLabelText(/Reason \(required/i)).toBeInTheDocument()
  })

  it('whitespace is not a reason', async () => {
    const user = userEvent.setup()
    await arm(user)

    await user.keyboard('   {Enter}')
    expect(alertSpy).not.toHaveBeenCalled()
  })

  it('the submit button is disabled until a reason exists', async () => {
    const user = userEvent.setup()
    await arm(user)
    const form = screen.getByLabelText(/Reason \(required/i).closest('form')

    const record = within(form).getByRole('button', { name: /Record/i })
    expect(record).toBeDisabled()
    await user.keyboard('resistance is plausible')
    expect(record).toBeEnabled()
  })

  it('a reason plus Enter records the decision, with the reason attached', async () => {
    const user = userEvent.setup()
    await arm(user)

    await user.keyboard('T790M is the likely mechanism{Enter}')
    expect(alertSpy).toHaveBeenCalledTimes(1)
    const payload = alertSpy.mock.calls[0][0]
    expect(payload).toMatch(/action=investigating/)
    expect(payload).toMatch(/reason=T790M is the likely mechanism/)
  })

  it.each([
    ['i', 'investigating'],
    ['d', 'deferred'],
    ['r', 'rejected'],
  ])('the %s key arms %s', async (key, action) => {
    // Each action id is case/models.py's DECISION_ACTIONS verbatim; a UI verb
    // that is not in that set would have to be translated somewhere.
    const user = userEvent.setup()
    await arm(user, key)
    await user.keyboard('a reason{Enter}')

    expect(alertSpy).toHaveBeenCalledTimes(1)
    expect(alertSpy.mock.calls[0][0]).toMatch(new RegExp(`action=${action}`))
  })
})

describe('the decision panel owns the keyboard while it is open', () => {
  it('typing a reason containing d or r does not navigate the list', async () => {
    const user = userEvent.setup()
    renderQueue()
    await screen.findByText(new RegExp(TOP))
    focusList()
    await user.keyboard('i')

    // "defer" and "resistance" both contain action keys.
    await user.keyboard('defer pending resistance testing')
    expect(screen.getByLabelText(/Reason \(required/i)).toHaveValue(
      'defer pending resistance testing',
    )
    expect(alertSpy).not.toHaveBeenCalled()
  })

  it('Escape cancels and returns focus to the question', async () => {
    const user = userEvent.setup()
    renderQueue()
    await screen.findByText(new RegExp(TOP))
    focusList()
    await user.keyboard('i')
    await user.keyboard('{Escape}')

    expect(screen.queryByLabelText(/Reason \(required/i)).toBeNull()
    // Dropping focus to <body> here is how a keyboard path quietly dead-ends:
    // the next arrow key would do nothing.
    expect(rows()[0]).toHaveFocus()
    expect(alertSpy).not.toHaveBeenCalled()
  })
})

describe('the keys are discoverable', () => {
  it('renders a legend naming each action key', async () => {
    renderQueue()
    await screen.findByText(new RegExp(TOP))
    const legend = document.querySelector('.kbd-legend')
    expect(legend).not.toBeNull()
    for (const key of ['i', 'd', 'r']) {
      expect(within(legend).getByText(key)).toBeInTheDocument()
    }
    expect(legend.textContent).toMatch(/every decision still needs a reason/i)
  })
})
