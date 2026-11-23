import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { enrollProfile, setStudyToken } from '../api/studyClient.js'
import { ENROLL_SESSION_KEY } from './Join.jsx'

const SPECIALTIES = [
  { value: 'medical_oncology', label: 'Medical oncology' },
  { value: 'surgical_oncology', label: 'Surgical oncology' },
  { value: 'radiation_oncology', label: 'Radiation oncology' },
  { value: 'oncology_resident', label: 'Oncology resident' },
  { value: 'other', label: 'Other' },
]

function loadEnrollment() {
  try {
    const raw = sessionStorage.getItem(ENROLL_SESSION_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export default function Profile() {
  const navigate = useNavigate()
  const enroll = loadEnrollment()
  const [form, setForm] = useState({
    full_name: '',
    email: '',
    phone: '',
    registration_number: '',
    specialty: '',
    years_in_oncology: '',
    institution: '',
    has_uptodate: false,
    has_nccn: false,
    ai_familiarity: '',
  })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!enroll?.enrollment_token) navigate('/join', { replace: true })
  }, [enroll, navigate])

  if (!enroll?.enrollment_token) return null

  const set = (key, value) => setForm((prev) => ({ ...prev, [key]: value }))

  const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())
  const years = Number(form.years_in_oncology)
  const yearsOk = Number.isInteger(years) && years >= 0 && years <= 60
  const ai = Number(form.ai_familiarity)
  const aiOk = Number.isInteger(ai) && ai >= 1 && ai <= 5
  const valid =
    form.full_name.trim() &&
    emailOk &&
    form.registration_number.trim() &&
    form.specialty &&
    yearsOk &&
    form.institution.trim() &&
    aiOk

  const submit = async (e) => {
    e.preventDefault()
    if (!valid) return
    setBusy(true)
    setError(null)
    try {
      const data = await enrollProfile({
        enrollment_token: enroll.enrollment_token,
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim() || null,
        registration_number: form.registration_number.trim(),
        specialty: form.specialty,
        years_in_oncology: years,
        institution: form.institution.trim(),
        has_uptodate: form.has_uptodate,
        has_nccn: form.has_nccn,
        ai_familiarity: ai,
      })
      setStudyToken(data.token)
      sessionStorage.removeItem(ENROLL_SESSION_KEY)
      navigate('/study')
    } catch {
      setError('Profile could not be saved. Check your answers and try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="wrap study-enroll">
      <h1>Your profile</h1>
      <p className="small muted">These details help us describe the participant group. They are stored securely on the study server.</p>
      <form className="study-profile-form" onSubmit={submit}>
        <label>
          Full name
          <input value={form.full_name} onChange={(e) => set('full_name', e.target.value)} required />
        </label>
        <label>
          Email
          <input type="email" value={form.email} onChange={(e) => set('email', e.target.value)} required />
          {!form.email || emailOk ? null : <span className="small muted">Enter a valid email.</span>}
        </label>
        <label>
          Phone (optional)
          <input value={form.phone} onChange={(e) => set('phone', e.target.value)} />
        </label>
        <label>
          Professional registration number
          <input value={form.registration_number} onChange={(e) => set('registration_number', e.target.value)} required />
        </label>
        <label>
          Specialty
          <select value={form.specialty} onChange={(e) => set('specialty', e.target.value)} required>
            <option value="">Select…</option>
            {SPECIALTIES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Years in oncology practice
          <input
            type="number"
            min={0}
            max={60}
            value={form.years_in_oncology}
            onChange={(e) => set('years_in_oncology', e.target.value)}
            required
          />
        </label>
        <label>
          Institution
          <input value={form.institution} onChange={(e) => set('institution', e.target.value)} required />
        </label>
        <label className="study-choice">
          <input type="checkbox" checked={form.has_uptodate} onChange={(e) => set('has_uptodate', e.target.checked)} />
          I have access to UpToDate
        </label>
        <label className="study-choice">
          <input type="checkbox" checked={form.has_nccn} onChange={(e) => set('has_nccn', e.target.checked)} />
          I have access to NCCN guidelines
        </label>
        <label>
          Familiarity with clinical AI tools (1 = none, 5 = very familiar)
          <input
            type="number"
            min={1}
            max={5}
            value={form.ai_familiarity}
            onChange={(e) => set('ai_familiarity', e.target.value)}
            required
          />
        </label>
        <button type="submit" className="study-button" disabled={!valid || busy}>
          Finish enrollment
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