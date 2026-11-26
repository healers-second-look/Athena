import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { enrollCode, enrollResume, getStudyToken, setStudyToken } from '../api/studyClient.js'

const ENROLL_SESSION_KEY = 'athena.study.enroll'

export function normalizeInviteCode(raw) {
  const compact = raw.replace(/[\s-]/g, '').toUpperCase()
  if (compact.length === 9) {
    return `ATH-${compact.slice(3, 7)}-${compact.slice(7, 9)}`
  }
  return raw.replace(/\s/g, '').toUpperCase()
}

export default function Join() {
  const navigate = useNavigate()
  const [code, setCode] = useState('')
  const [email, setEmail] = useState('')
  const [resumeMode, setResumeMode] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (getStudyToken()) navigate('/study', { replace: true })
  }, [navigate])

  const onCodeChange = (e) => setCode(normalizeInviteCode(e.target.value))

  const submitCode = async (e) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const data = await enrollCode(code.trim())
      sessionStorage.setItem(
        ENROLL_SESSION_KEY,
        JSON.stringify({
          enrollment_token: data.enrollment_token,
          consent_version: data.consent_version,
          consent_sha256: data.consent_sha256,
          consent_markdown: data.consent_markdown,
          required_checkboxes: data.required_checkboxes,
        }),
      )
      navigate('/join/consent')
    } catch (err) {
      if (err.status === 409) setResumeMode(true)
      else if (err.status === 429) setError('Too many attempts. Try again later.')
      else setError('We could not verify that invite code. Check it and try again.')
    } finally {
      setBusy(false)
    }
  }

  const submitResume = async (e) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const data = await enrollResume({ code: code.trim(), email: email.trim() })
      setStudyToken(data.token)
      navigate('/study')
    } catch (err) {
      if (err.status === 429) setError('Too many attempts. Try again later.')
      else setError('We could not resume with those details. Check your code and email.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="wrap study-enroll">
      <h1>Athena clinical study</h1>
      <p className="muted">
        Two sessions of about 60 minutes each, working through synthetic oncology cases only.
      </p>
      <p className="muted">
        You will complete the same clinical tasks using your usual tools in one block and the Athena
        system in another.
      </p>
      <p className="muted">Your invite code was provided by the study team.</p>

      {!resumeMode ? (
        <form onSubmit={submitCode}>
          <label>
            Invite code
            <input
              autoComplete="off"
              value={code}
              onChange={onCodeChange}
              placeholder="ATH-XXXX-XX"
              required
            />
          </label>
          <button type="submit" className="study-button" disabled={busy || !code.trim()}>
            Continue
          </button>
        </form>
      ) : (
        <form onSubmit={submitResume}>
          <p className="small muted">This invite was already used. Enter the same code and your registered email to resume.</p>
          <label>
            Invite code
            <input value={code} onChange={onCodeChange} required />
          </label>
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <button type="submit" className="study-button" disabled={busy || !code.trim() || !email.trim()}>
            Resume
          </button>
          <button type="button" className="study-button study-button--ghost" onClick={() => setResumeMode(false)}>
            Use a different code
          </button>
        </form>
      )}

      {error ? (
        <p className="study-log-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}

export { ENROLL_SESSION_KEY }