import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getTimeline } from '../api/client.js'
import TimelineContent from '../components/timeline/TimelineContent.jsx'
import { Failure } from './CaseDashboard.jsx'

// Patient Timeline -- modeled on https://osteosarc.com/timeline/'s category
// structure: chronological events (Treatments, Procedures, Imaging) plus
// three measurement tracks (MRD, Flow Cytometry, Lab Results).
//
// Today `getTimeline` always returns the same reference dataset (real,
// published osteosarcoma treatment data -- see
// secondlook/timeline/reference_data.py's docstring) regardless of which
// case you're viewing. That is deliberate, temporary, and stated on the
// page itself, not hidden: swapping in real per-patient data later only
// touches that one backend function, not this component.
export default function PatientTimeline() {
  const { id } = useParams()
  const [bundle, setBundle] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    getTimeline(id)
      .then(setBundle)
      .catch((err) => setError(err))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <p className="muted">Loading patient timeline…</p>
  if (error) return <Failure what="patient timeline" error={error} />
  if (!bundle) return null

  return (
    <div className="patient-timeline">
      <p className="small muted">
        <Link to={`/cases/${id}`}>&larr; Back to case</Link>
      </p>
      <h1>Patient Timeline</h1>
      <p className="small muted timeline-source-note">
        Reference dataset (real, published osteosarcoma treatment data) shown while no
        per-patient timeline data source is wired up yet — see{' '}
        <code>secondlook/timeline/reference_data.py</code>. The same case is shown for every
        patient today; that will change without this page changing once a real data source is
        connected.
      </p>

      <TimelineContent bundle={bundle} />
    </div>
  )
}
