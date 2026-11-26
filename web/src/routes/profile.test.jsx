import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import Profile from './Profile.jsx'
import { ENROLL_SESSION_KEY } from './Join.jsx'

const enrollProfile = vi.fn()
const setStudyToken = vi.fn()

vi.mock('../api/studyClient.js', () => ({
  enrollProfile: (...args) => enrollProfile(...args),
  setStudyToken: (...args) => setStudyToken(...args),
}))

function fillValidForm() {
  fireEvent.change(screen.getByLabelText(/^Full name/i), { target: { value: 'Dr Smith' } })
  fireEvent.change(screen.getByLabelText(/^Email/i), { target: { value: 'doc@example.org' } })
  fireEvent.change(screen.getByLabelText(/registration/i), { target: { value: 'REG1' } })
  fireEvent.change(screen.getByLabelText(/^Specialty/i), { target: { value: 'medical_oncology' } })
  fireEvent.change(screen.getByLabelText(/Years in oncology/i), { target: { value: '5' } })
  fireEvent.change(screen.getByLabelText(/^Institution/i), { target: { value: 'Hospital' } })
  fireEvent.change(screen.getByLabelText(/Familiarity/i), { target: { value: '3' } })
}

describe('Profile', () => {
  beforeEach(() => {
    sessionStorage.setItem(ENROLL_SESSION_KEY, JSON.stringify({ enrollment_token: 'enroll-tok' }))
    enrollProfile.mockReset()
    setStudyToken.mockReset()
    enrollProfile.mockResolvedValue({ token: 'session-tok', participant_id: 'P001' })
  })

  it('validates and stores token on success', async () => {
    render(
      <MemoryRouter initialEntries={['/join/profile']}>
        <Routes>
          <Route path="/join/profile" element={<Profile />} />
          <Route path="/study" element={<p>Study home</p>} />
        </Routes>
      </MemoryRouter>,
    )

    const submit = screen.getByRole('button', { name: /finish enrollment/i })
    expect(submit).toBeDisabled()
    fillValidForm()
    expect(submit).toBeEnabled()
    fireEvent.click(submit)

    await waitFor(() => expect(enrollProfile).toHaveBeenCalled())
    expect(setStudyToken).toHaveBeenCalledWith('session-tok')
    await waitFor(() => expect(screen.getByText('Study home')).toBeInTheDocument())
  })
})