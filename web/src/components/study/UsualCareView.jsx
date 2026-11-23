import { useState } from 'react'
import CaseHeader from './CaseHeader.jsx'
import StudyFindings from './StudyFindings.jsx'
import StudyTimeline from './StudyTimeline.jsx'

const SOURCE_TYPES = [
  'guideline',
  'PubMed',
  'trial registry',
  'UpToDate',
  'web',
  'other',
]

export default function UsualCareView({ view, onFindingOpened, onCitationOpened, onEvent }) {
  const [url, setUrl] = useState('')
  const [sourceType, setSourceType] = useState('guideline')
  const [sources, setSources] = useState([])

  const addSource = (e) => {
    e.preventDefault()
    const trimmed = url.trim()
    if (!trimmed) return
    onEvent('external_source_logged', { url: trimmed, type: sourceType })
    setSources((prev) => [...prev, { url: trimmed, type: sourceType }])
    setUrl('')
  }

  return (
    <>
      <CaseHeader view={view} />
      <p className="muted small">Previous consult note (synthetic scenario material).</p>

      <h2>Timeline</h2>
      <StudyTimeline baselineEvents={view.baseline_events} updateEvents={view.update_events} />

      <h2>Findings</h2>
      <StudyFindings
        findings={view.findings}
        onFindingOpened={onFindingOpened}
        onCitationOpened={onCitationOpened}
      />

      <section className="study-sources">
        <h2>Sources I used</h2>
        <p className="small muted">
          Use your usual tools in another tab or window, then log any sources you consulted.
        </p>
        <form className="study-source-form" onSubmit={addSource}>
          <label>
            URL
            <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
          </label>
          <label>
            Type
            <select value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
              {SOURCE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" className="study-button" disabled={!url.trim()}>
            Log source
          </button>
        </form>
        {sources.length ? (
          <ul className="study-source-list">
            {sources.map((s, i) => (
              <li key={i}>
                <span className="small muted">{s.type}</span> · {s.url}
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </>
  )
}