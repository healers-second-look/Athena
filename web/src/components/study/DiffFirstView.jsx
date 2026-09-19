import ChangeBanner from '../ChangeBanner.jsx'
import CaseHeader from './CaseHeader.jsx'
import StudyFindings from './StudyFindings.jsx'
import StudyTimeline from './StudyTimeline.jsx'

// Arm A: the change-review screen. The real ChangeBanner, the struck findings,
// and the question worklist are the treatment under test.
export default function DiffFirstView({ view, onFindingOpened, onCitationOpened }) {
  const events = [...view.baseline_events, ...view.update_events]
  const eventById = new Map(events.map((e) => [e.id, e]))
  const findingNumber = new Map(view.findings.map((f, i) => [f.id, i + 1]))
  const findingById = new Map(view.findings.map((f) => [f.id, f]))
  const lastBaseline = view.baseline_events.map((e) => e.occurred_on).sort().pop()

  const changeSet = {
    since: lastBaseline,
    changes: view.reported_changes.map((c) => ({
      kind: c.kind,
      summary: c.summary,
      triggering_event_id: c.triggering_event,
      observed_on: eventById.get(c.triggering_event)?.occurred_on,
    })),
    supersessions: view.reported_supersessions.map((s) => ({
      finding_id: s.finding_id,
      finding_label: `Finding #${findingNumber.get(s.finding_id)}`,
      finding_claim: findingById.get(s.finding_id)?.claim,
      note: s.note,
      triggering_event_id: s.triggering_event,
      triggering_event_label: eventById.get(s.triggering_event)?.summary,
    })),
    unchanged_reason: null,
  }

  return (
    <>
      <CaseHeader view={view} />
      <ChangeBanner changeSet={changeSet} />

      <h2>Open questions</h2>
      {view.questions.length ? (
        <ul className="study-questions">
          {view.questions.map((q) => (
            <li key={q.id}>{q.text}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">No open questions.</p>
      )}

      <h2>Findings</h2>
      <StudyFindings
        findings={view.findings}
        supersededIds={new Set(view.reported_supersessions.map((s) => s.finding_id))}
        onFindingOpened={onFindingOpened}
        onCitationOpened={onCitationOpened}
      />

      <h2>Timeline</h2>
      <StudyTimeline
        baselineEvents={view.baseline_events}
        updateEvents={view.update_events}
        highlightNew
      />
    </>
  )
}
