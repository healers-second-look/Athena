import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import Join, { ENROLL_SESSION_KEY, normalizeInviteCode } from './Join.jsx'

const enrollCode = vi.fn()
const enrollResume = vi.fn()
const getStudyToken = vi.fn(() => '')

vi.mock('../api/studyClient.js', () => ({
  enrollCode: (...args) => enrollCode(...args),
  enrollResume: (...args) => enrollResume(...args),
  getStudyToken: () => getStudyToken(),
  setStudyToken: vi.fn(),
}))

describe('normalizeInviteCode', () => {
  it('formats compact codes', () => {
    expect(normalizeInviteCode('ath-abcd-ef')).toBe('ATH-ABCD-EF')
    expect(normalizeInviteCode('ATHABCD EF')).toBe('ATH-ABCD-EF')
  })
})

describe('Join', () => {
  beforeEach(() => {
    sessionStorage.clear()
    enrollCode.mockReset()
    getStudyToken.mockReturnValue('')
  })

  it('stores enrollment state and navigates on valid code', async () => {
    enrollCode.mockResolvedValue({
      enrollment_token: 'tok',
      consent_version: '0.1',
      consent_sha256: 'sha',
      consent_markdown: '# Consent',
      required_checkboxes: [{ id: 'read_understood', label: 'Read' }],
    })

    render(
      <MemoryRouter initialEntries={['/join']}>
        <Routes>
          <Route path="/join" element={<Join />} />
          <Route path="/join/consent" element={<p>Consent page</p>} />
        </Routes>
      </MemoryRouter>,
    )

    fireEvent.change(screen.getByLabelText(/invite code/i), { target: { value: 'ATH-ABCD-EF' } })
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))

    await waitFor(() => expect(enrollCode).toHaveBeenCalled())
    const stored = JSON.parse(sessionStorage.getItem(ENROLL_SESSION_KEY))
    expect(stored.enrollment_token).toBe('tok')
    await waitFor(() => expect(screen.getByText('Consent page')).toBeInTheDocument())
  })

  it('shows resume form on 409', async () => {
    const err = new Error('used')
    err.status = 409
    enrollCode.mockRejectedValue(err)

    render(
      <MemoryRouter>
        <Join />
      </MemoryRouter>,
    )

    fireEvent.change(screen.getByLabelText(/invite code/i), { target: { value: 'ATH-ABCD-EF' } })
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))

    await waitFor(() => expect(screen.getByText(/already used/i)).toBeInTheDocument())
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
  })
})