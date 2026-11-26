import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import Consent from './Consent.jsx'
import { ENROLL_SESSION_KEY } from './Join.jsx'

const enrollConsent = vi.fn()

vi.mock('../api/studyClient.js', () => ({
  enrollConsent: (...args) => enrollConsent(...args),
}))

const enrollPayload = {
  enrollment_token: 'enroll-tok',
  consent_version: '0.1',
  consent_sha256: 'abc',
  consent_markdown: '## Section\n\nParagraph one.\n\n- bullet',
  required_checkboxes: [
    { id: 'read_understood', label: 'I have read and understood.' },
    { id: 'voluntary_withdraw', label: 'Voluntary.' },
    { id: 'synthetic_not_advice', label: 'Synthetic.' },
    { id: 'data_use', label: 'Data.' },
  ],
}

function renderConsent() {
  return render(
    <MemoryRouter initialEntries={['/join/consent']}>
      <Routes>
        <Route path="/join/consent" element={<Consent />} />
        <Route path="/join/profile" element={<p>Profile page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('Consent', () => {
  beforeEach(() => {
    sessionStorage.setItem(ENROLL_SESSION_KEY, JSON.stringify(enrollPayload))
    enrollConsent.mockReset()
    enrollConsent.mockResolvedValue({ status: 'recorded' })
  })

  it('Accept disabled until scrolled, required boxes, and name', async () => {
    renderConsent()
    const accept = screen.getByRole('button', { name: /accept/i })
    expect(accept).toBeDisabled()

    const scroll = screen.getByTestId('consent-scroll')
    Object.defineProperty(scroll, 'clientHeight', { value: 100, configurable: true })
    Object.defineProperty(scroll, 'scrollHeight', { value: 100, configurable: true })
    fireEvent.scroll(scroll, { target: { scrollTop: 100 } })

    fireEvent.click(screen.getByLabelText(/I have read and understood/))
    fireEvent.click(screen.getByLabelText(/Voluntary/))
    fireEvent.click(screen.getByLabelText(/Synthetic/))
    fireEvent.click(screen.getByLabelText(/Data/))
    expect(accept).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: 'Dr A' } })
    expect(accept).toBeEnabled()
  })

  it('posts consent body; optional recording may be false', async () => {
    renderConsent()
    const scroll = screen.getByTestId('consent-scroll')
    Object.defineProperty(scroll, 'clientHeight', { value: 100, configurable: true })
    Object.defineProperty(scroll, 'scrollHeight', { value: 100, configurable: true })
    fireEvent.scroll(scroll, { target: { scrollTop: 100 } })

    fireEvent.click(screen.getByLabelText(/I have read and understood/))
    fireEvent.click(screen.getByLabelText(/Voluntary/))
    fireEvent.click(screen.getByLabelText(/Synthetic/))
    fireEvent.click(screen.getByLabelText(/Data/))
    fireEvent.change(screen.getByLabelText(/full name/i), { target: { value: 'Dr A' } })
    fireEvent.click(screen.getByRole('button', { name: /accept/i }))

    await waitFor(() => expect(enrollConsent).toHaveBeenCalled())
    expect(enrollConsent).toHaveBeenCalledWith(
      expect.objectContaining({
        enrollment_token: 'enroll-tok',
        signed_name: 'Dr A',
        answers: expect.objectContaining({
          read_understood: true,
          voluntary_withdraw: true,
          synthetic_not_advice: true,
          data_use: true,
          screen_recording: false,
        }),
      }),
    )
  })
})