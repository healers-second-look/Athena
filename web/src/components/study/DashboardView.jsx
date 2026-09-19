import CaseHeader from './CaseHeader.jsx'
import StudyFindings from './StudyFindings.jsx'
import StudyTimeline from './StudyTimeline.jsx'

// Arm B: state without the diff. Same header, same events, same findings with
// the same citations -- but no change banner, no supersession marking, and no
// worklist. Deliberately no score or summary badge either: a dashboard with a
// consensus number would be a strawman (protocol section 3).
export default function DashboardView({ view, onFindingOpened, onCitationOpened }) {
  return (
    <>
      <CaseHeader view={view} />

      <h2>Timeline</h2>
      <StudyTimeline baselineEvents={view.baseline_events} updateEvents={view.update_events} />

      <h2>Findings</h2>
      <StudyFindings
        findings={view.findings}
        onFindingOpened={onFindingOpened}
        onCitationOpened={onCitationOpened}
      />
    </>
  )
}
