import { useState } from 'react'
import RatingSlider from './RatingSlider.jsx'

// The same standard form in every arm, shown after the review step. Only claims
// are listed -- never a struck/superseded mark, even in the diff-first arm -- so
// the form itself cannot carry the treatment.
export default function AssessmentForm({ findings, options, prompt, onEvent, onSubmit }) {
  const [flags, setFlags] = useState({})
  const [confidence, setConfidence] = useState({})
  const [decision, setDecision] = useState(null)
  const [rationale, setRationale] = useState('')

  const complete =
    findings.every((f) => flags[f.id] !== undefined && confidence[f.id] !== undefined) &&
    decision !== null

  // flag_cleared means "was flagged, now isn't". A first "valid" answer is not a
  // clearing -- it is recorded in the submitted snapshot -- so it logs nothing.
  const setFlag = (id, flagged) => {
    const wasFlagged = flags[id] === true
    setFlags((prev) => ({ ...prev, [id]: flagged }))
    if (flagged) onEvent('flag_set', { finding_id: id })
    else if (wasFlagged) onEvent('flag_cleared', { finding_id: id })
  }

  return (
    <form
      className="study-assessment"
      onSubmit={(e) => {
        e.preventDefault()
        if (!complete) return
        onSubmit({ flags, confidence, decision, rationale })
      }}
    >
      <h2>Your assessment</h2>
      <p className="small muted">
        For each finding, say whether you think it is valid and supported, and how confident you
        are.
      </p>

      {findings.map((finding, index) => (
        <fieldset key={finding.id} className="study-assess-finding">
          <legend>
            Finding #{index + 1}
            <span className="small muted"> · {finding.evidence_class}</span>
          </legend>
          <p className="claim">{finding.claim}</p>
          <label className="study-choice">
            <input
              type="radio"
              name={`flag-${finding.id}`}
              checked={flags[finding.id] === false}
              onChange={() => setFlag(finding.id, false)}
            />
            Valid and supported
          </label>
          <label className="study-choice">
            <input
              type="radio"
              name={`flag-${finding.id}`}
              checked={flags[finding.id] === true}
              onChange={() => setFlag(finding.id, true)}
            />
            Flag: no longer valid, or not supported
          </label>
          <RatingSlider
            id={`conf-${finding.id}`}
            label="How confident are you that this finding is valid?"
            low="Not at all"
            high="Certain"
            value={confidence[finding.id] ?? null}
            onChange={(v) => setConfidence((prev) => ({ ...prev, [finding.id]: v }))}
            onCommit={(v) => onEvent('confidence_set', { finding_id: finding.id, value: v })}
          />
        </fieldset>
      ))}

      <fieldset className="study-assess-finding">
        <legend>{prompt}</legend>
        {options.map((option) => (
          <label key={option.id} className="study-choice">
            <input
              type="radio"
              name="decision"
              checked={decision === option.id}
              onChange={() => setDecision(option.id)}
            />
            {option.text}
          </label>
        ))}
        <label className="study-rationale">
          Rationale (optional)
          <textarea
            rows={3}
            maxLength={2000}
            value={rationale}
            onChange={(e) => setRationale(e.target.value)}
          />
        </label>
      </fieldset>

      <button type="submit" className="study-button" disabled={!complete}>
        Submit assessment
      </button>
      {!complete ? (
        <p className="small muted">
          Answer every finding (flag and confidence) and choose a next step to continue.
        </p>
      ) : null}
    </form>
  )
}
