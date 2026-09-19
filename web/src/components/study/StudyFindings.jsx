import EvidenceCard from '../evidence/index.jsx'

// The findings list every arm's reviewer is shown. It reuses the real
// EvidenceCard (documented/computed cards with their inline citation), so what
// a finding looks like is identical across arms -- only the surrounding
// organization differs (protocol section 3: matched content).
//
// `supersededIds` is the treatment. It is non-empty only in the diff-first arm;
// the server sends the supersessions to that arm alone (study/views.py), so the
// other arms cannot render a struck finding even by accident.

export function toCardFinding(finding) {
  return {
    claim: finding.claim,
    evidence_class: finding.evidence_class,
    evidence_level: finding.evidence_level,
    source: finding.citation
      ? {
          name: finding.citation.name,
          citation_url: finding.citation.url,
          citation_id: finding.citation.id,
        }
      : { method: finding.method, version: 'study' },
    caveats: [],
  }
}

export default function StudyFindings({
  findings,
  supersededIds = new Set(),
  onFindingOpened = () => {},
  onCitationOpened = () => {},
}) {
  if (!findings.length) return <p className="muted">No findings.</p>
  return (
    <div className="study-findings">
      {findings.map((finding, index) => {
        const superseded = supersededIds.has(finding.id)
        return (
          <div
            key={finding.id}
            className={`study-finding${superseded ? ' study-finding--superseded' : ''}`}
            data-finding-id={finding.id}
            onClick={(event) => {
              const link = event.target.closest('a')
              if (link) onCitationOpened(finding.id, link.href)
              else onFindingOpened(finding.id)
            }}
          >
            <div className="study-finding-label small muted">
              Finding #{index + 1}
              {superseded ? <span className="study-superseded-chip">superseded</span> : null}
            </div>
            <EvidenceCard finding={toCardFinding(finding)} />
          </div>
        )
      })}
    </div>
  )
}
