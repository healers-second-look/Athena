import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { enrollConsent } from '../api/studyClient.js'
import SimpleMarkdown from '../components/study/SimpleMarkdown.jsx'
import { ENROLL_SESSION_KEY } from './Join.jsx'

function loadEnrollment() {
  try {
    const raw = sessionStorage.getItem(ENROLL_SESSION_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export default function Consent() {
  const navigate = useNavigate()
  const enroll = loadEnrollment()
  const scrollRef = useRef(null)
  const [scrolled, setScrolled] = useState(false)
  const [answers, setAnswers] = useState({})
  const [screenRecording, setScreenRecording] = useState(false)
  const [signedName, setSignedName] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!enroll) navigate('/join', { replace: true })
  }, [enroll, navigate])

  const onScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 8
    if (atBottom) setScrolled(true)
  }, [])

  if (!enroll) return null

  const required = enroll.required_checkboxes || []
  const requiredOk = required.every((c) => answers[c.id] === true)
  const canAccept = scrolled && requiredOk && signedName.trim().length > 0

  const toggleRequired = (id, checked) => {
    if (!scrolled) return
    setAnswers((prev) => ({ ...prev, [id]: checked }))
  }

  const accept = async (e) => {
    e.preventDefault()
    if (!canAccept) return
    setBusy(true)
    setError(null)
    try {
      await enrollConsent({
        enrollment_token: enroll.enrollment_token,
        consent_version: enroll.consent_version,
        consent_sha256: enroll.consent_sha256,
        signed_name: signedName.trim(),
        answers: {
          ...Object.fromEntries(required.map((c) => [c.id, true])),
          screen_recording: screenRecording,
        },
      })
      navigate('/join/profile')
    } catch {
      setError('Consent could not be recorded. Reload and try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="wrap study-enroll">
      <h1>Informed consent</h1>
      <div
        ref={scrollRef}
        className="consent-scroll"
        onScroll={onScroll}
        tabIndex={0}
        data-testid="consent-scroll"
      >
        <SimpleMarkdown source={enroll.consent_markdown} />
      </div>
      {!scrolled ? <p className="small muted">Scroll to the end of the document to enable the checkboxes below.</p> : null}

      <form onSubmit={accept}>
        {required.map((c) => (
          <label key={c.id} htmlFor={`consent-${c.id}`} className="study-choice">
            <input
              id={`consent-${c.id}`}
              type="checkbox"
              disabled={!scrolled}
              checked={answers[c.id] === true}
              onChange={(e) => toggleRequired(c.id, e.target.checked)}
            />
            <span>{c.label}</span>
          </label>
        ))}
        <label htmlFor="consent-screen-recording" className="study-choice">
          <input
            id="consent-screen-recording"
            type="checkbox"
            disabled={!scrolled}
            checked={screenRecording}
            onChange={(e) => setScreenRecording(e.target.checked)}
          />
          <span>I agree to optional screen recording in the usual-care condition</span>
        </label>
        <label htmlFor="consent-signed-name">
          Type your full name to sign
          <input
            id="consent-signed-name"
            value={signedName}
            onChange={(e) => setSignedName(e.target.value)}
            disabled={!scrolled}
          />
        </label>
        <button type="submit" className="study-button" disabled={!canAccept || busy}>
          Accept
        </button>
      </form>
      {error ? (
        <p className="study-log-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}