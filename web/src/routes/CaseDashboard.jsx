import { Link, useParams } from 'react-router-dom'
import ChangeBanner from '../components/ChangeBanner.jsx'
import Timeline from '../components/Timeline.jsx'
import CurrentStatePanel from '../components/CurrentStatePanel.jsx'
import useAsync from '../api/useAsync.js'
import { getCase, getChanges } from '../api/client.js'

// §9 — Case Dashboard. Timeline of events, current state panel, change banner.
//
// The banner is placed above everything else on purpose. The premise of the
// whole system is that the case has memory and something changed since the
// clinician last looked; burying that below a fold makes the one thing worth
// opening the page for the last thing seen.
export default function CaseDashboard() {
  const { id } = useParams()
  const kase = useAsync(() => getCase(id), [id])
  const changes = useAsync(() => getChanges(id), [id])

  if (kase.loading || changes.loading) return <p className="muted">Loading case…</p>
  if (kase.error) return <Failure what="case" error={kase.error} />
  if (changes.error) return <Failure what="change set" error={changes.error} />

  const c = kase.data
  return (
    <>
      <h1>{c.label}</h1>
      <p className="small muted">
        {c.cancer_type}
        {c.stage ? ` · stage ${c.stage}` : null}
        {c.doid ? ` · DOID ${c.doid}` : null}
        {' · '}
        <Link to={`/cases/${id}/queue`}>Research queue</Link>
        {' · '}
        <Link to={`/cases/${id}/timeline`}>Patient timeline</Link>
        {' · '}
        {/* A normal link, not a client route: the brief is server-rendered
            and print-ready, and routing it through the SPA would replace a
            5 KB no-JS page with the whole bundle. */}
        <a href={`/cases/${id}/brief`}>Tumour-board brief</a>
      </p>

      <ChangeBanner changeSet={changes.data} />

      <h2>Current state</h2>
      <CurrentStatePanel
        state={c.current_state}
        cancerType={c.cancer_type}
        stage={c.stage}
        ageYears={c.age_years}
      />

      <h2>Timeline</h2>
      <Timeline events={c.timeline} highlightSince={changes.data?.since} />
    </>
  )
}

export function Failure({ what, error }) {
  // docs/api-contracts.md: a failure is always rendered, never filtered out
  // silently. It says what failed and whether retrying is worth anything.
  return (
    <div className="card card-computed" role="alert">
      <div className="badge badge-computed">Could not load</div>
      <p className="claim">The {what} could not be loaded.</p>
      <p className="small muted">{String(error?.message || error)}</p>
    </div>
  )
}
