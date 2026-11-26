import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import EnrolledStudyRunner from './EnrolledStudyRunner.jsx'

const postEvents = vi.fn().mockResolvedValue({ ok: true })

vi.mock('../api/studyClient.js', () => ({
  getMe: () =>
    Promise.resolve({
      participant_id: 'P01',
      unreviewed: true,
      completed_case_ids: [],
      items: [
        { case_id: 'c1', arm: 'usual_care' },
        { case_id: 'c2', arm: 'athena_full' },
      ],
    }),
  postEvents: (...args) => postEvents(...args),
}))

// The case screen itself is covered in StudyCase.test.jsx; here it only needs to finish.
vi.mock('./StudyCase.jsx', () => ({
  default: ({ item, onDone }) => (
    <button type="button" onClick={onDone}>
      finish {item.case_id}
    </button>
  ),
}))

async function completeSus() {
  const items = document.querySelectorAll('.study-sus-item')
  expect(items).toHaveLength(10)
  items.forEach((item) => fireEvent.click(item.querySelectorAll('input[type="radio"]')[2]))
  fireEvent.click(screen.getByRole('button', { name: /continue/i }))
}

describe('EnrolledStudyRunner', () => {
  it('pauses between blocks and says the study is complete at the end', async () => {
    render(
      <MemoryRouter>
        <EnrolledStudyRunner />
      </MemoryRouter>,
    )

    fireEvent.click(await screen.findByRole('button', { name: 'finish c1' }))
    expect(screen.getByText(/my usual tools frequently/)).toBeInTheDocument()
    await completeSus()

    expect(await screen.findByRole('heading', { name: 'First block complete' })).toBeInTheDocument()
    expect(screen.getByText(/with Athena/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /take a break/i })).toHaveAttribute('href', '/study')
    fireEvent.click(screen.getByRole('button', { name: /start next block/i }))

    fireEvent.click(await screen.findByRole('button', { name: 'finish c2' }))
    expect(screen.getByText(/use Athena frequently/)).toBeInTheDocument()
    await completeSus()

    expect(await screen.findByRole('heading', { name: 'Study complete' })).toBeInTheDocument()
    expect(screen.queryByText(/Block complete/)).toBeNull()
  })
})
