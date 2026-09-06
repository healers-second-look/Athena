import { useEffect, useState } from 'react'
import { getReferenceTimeline } from '../../api/chatClient.js'
import TimelineContent from './TimelineContent.jsx'

// Patient Timeline as a modal inside the chat interface (ChatInterface.jsx),
// alongside the existing "Explore Graph" modal (GraphViewer.jsx) -- same
// backdrop/header chrome, reusing its .graph-modal-* classes from chat.css.
//
// Chat sessions have no case attached (they're keyed by context_id, a KG
// context -- see chatClient.js), so this fetches the unscoped
// /api/timeline route rather than a case-scoped one. That route returns the
// same reference bundle CaseDashboard's Patient Timeline page shows -- see
// secondlook/timeline/reference_data.py's docstring for why it's not yet
// patient-specific.
export default function TimelineModal({ onClose }) {
  const [bundle, setBundle] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    getReferenceTimeline()
      .then(setBundle)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="graph-modal-backdrop" onClick={onClose}>
      <div className="graph-modal timeline-modal" onClick={(e) => e.stopPropagation()}>
        <div className="graph-header">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined" style={{ color: 'var(--sage-dark)', fontSize: 24 }}>
              timeline
            </span>
            <div>
              <h2 className="graph-title">Patient Timeline</h2>
              <p className="graph-subtitle">Reference dataset -- see secondlook/timeline/reference_data.py</p>
            </div>
          </div>
          <button className="graph-close-btn" onClick={onClose}>
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>

        <div className="graph-body timeline-modal-body">
          {loading && (
            <div className="empty-state" style={{ height: 400 }}>
              <span className="material-symbols-outlined" style={{ animation: 'spin 1s linear infinite' }}>
                sync
              </span>
              <p>Loading timeline...</p>
            </div>
          )}

          {error && (
            <div className="empty-state" style={{ height: 400, color: 'var(--alarm)' }}>
              <span className="material-symbols-outlined">error</span>
              <p>Timeline query error: {error}</p>
            </div>
          )}

          {!loading && !error && bundle && (
            <div className="patient-timeline patient-timeline-embedded">
              <TimelineContent bundle={bundle} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
