import { useMemo, useState, useEffect } from 'react'
import TimelineChart from './TimelineChart.jsx'
import MeasurementExplorer from './MeasurementExplorer.jsx'

// Shared body for both timeline surfaces (the case-scoped page in
// PatientTimeline.jsx and the unscoped modal in TimelineModal.jsx): category
// legend, the swim-lane chart, the MRD table, and the two measurement
// explorers. Takes an already-loaded bundle -- loading/error states are the
// caller's concern, since a page and a modal handle those differently.
export default function TimelineContent({ bundle }) {
  const eventCategories = useMemo(
    () => [...new Set(bundle.events.map((e) => e.category))].sort(),
    [bundle],
  )

  const [activeCategories, setActiveCategories] = useState(() => new Set(eventCategories))
  useEffect(() => {
    setActiveCategories(new Set(eventCategories))
  }, [eventCategories])

  const toggleCategory = (cat) => {
    setActiveCategories((prev) => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }

  const visibleEvents = bundle.events.filter((e) => activeCategories.has(e.category))

  return (
    <>
      <div className="timeline-legend">
        {eventCategories.map((cat) => (
          <button
            key={cat}
            type="button"
            className={`timeline-legend-chip cat-${cat.toLowerCase()} ${
              activeCategories.has(cat) ? 'active' : 'inactive'
            }`}
            onClick={() => toggleCategory(cat)}
            aria-pressed={activeCategories.has(cat)}
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
    </>
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
