import { useEffect, useMemo, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getTimeline } from '../api/client.js'
import TimelineChart from '../components/timeline/TimelineChart.jsx'
import MeasurementExplorer from '../components/timeline/MeasurementExplorer.jsx'
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

  const eventCategories = useMemo(() => {
    if (!bundle) return []
    return [...new Set(bundle.events.map((e) => e.category))].sort()
  }, [bundle])

  const [activeCategories, setActiveCategories] = useState(null)
  useEffect(() => {
    if (eventCategories.length) setActiveCategories(new Set(eventCategories))
  }, [eventCategories])

  if (loading) return <p className="muted">Loading patient timeline…</p>
  if (error) return <Failure what="patient timeline" error={error} />
  if (!bundle) return null

  const toggleCategory = (cat) => {
    setActiveCategories((prev) => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }

  const visibleEvents = bundle.events.filter((e) => activeCategories?.has(e.category))

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

      <div className="timeline-legend">
        {eventCategories.map((cat) => (
          <button
            key={cat}
            type="button"
            className={`timeline-legend-chip cat-${cat.toLowerCase()} ${
              activeCategories?.has(cat) ? 'active' : 'inactive'
            }`}
            onClick={() => toggleCategory(cat)}
            aria-pressed={activeCategories?.has(cat)}
          >
            {cat} ({bundle.events.filter((e) => e.category === cat).length})
          </button>
        ))}
      </div>

      <TimelineChart events={visibleEvents} mrd={bundle.mrd} />

      <h2>Minimum Residual Disease (MRD)</h2>
      <MrdTable rows={bundle.mrd} />

      <h2>Flow Cytometry</h2>
      <MeasurementExplorer
        rows={bundle.cytometry}
        measurementKey="short_name"
        valueKey="value"
        emptyLabel="flow cytometry measurement"
      />

      <h2>Laboratory Results</h2>
      <MeasurementExplorer
        rows={bundle.lab_results}
        measurementKey="test_name"
        valueKey="value"
        emptyLabel="lab test"
        numeric={false}
      />
    </div>
  )
}

function MrdTable({ rows }) {
  if (!rows.length) return <p className="muted">No MRD measurements recorded.</p>
  return (
    <div className="timeline-table-scroll">
      <table className="timeline-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Assay</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={r.kind === 'not_detected' ? 'mrd-negative' : undefined}>
              <td>{r.date}</td>
              <td>{r.assay}</td>
              <td>{r.value ?? r.kind.replace(/_/g, ' ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
