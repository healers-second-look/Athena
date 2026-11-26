import { useState } from 'react'
import RatingSlider from './RatingSlider.jsx'

export function EvidenceLookupForm({ question, onSubmit, onEvent }) {
  const [answer, setAnswer] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [confidence, setConfidence] = useState(null)

  const ready = answer.trim().length > 0 && confidence !== null

  return (
    <form
      className="study-task-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (!ready) return
        const payload = {
          task: 'evidence_lookup',
          answer: answer.trim(),
          confidence,
          source_url: sourceUrl.trim() || undefined,
        }
        onEvent('task_answer_submitted', payload)
        onSubmit(payload)
      }}
    >
      <h2>Evidence lookup</h2>
      <p className="claim">{question}</p>
      <label>
        Your answer
        <textarea rows={4} value={answer} onChange={(e) => setAnswer(e.target.value)} />
      </label>
      <label>
        Source URL (optional)
        <input type="url" value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} />
      </label>
      <RatingSlider
        id="evidence-conf"
        label="How confident are you in this answer?"
        low="Not at all"
        high="Certain"
        value={confidence}
        onChange={setConfidence}
        onCommit={(v) => onEvent('confidence_set', { task: 'evidence_lookup', value: v })}
      />
      <button type="submit" className="study-button" disabled={!ready}>
        Continue
      </button>
    </form>
  )
}

const REGION_LABELS = { india: 'India', us: 'United States', both: 'India and United States' }

export function TrialMatchForm({ question, region, maxAnswers, onSubmit, onEvent }) {
  const [ids, setIds] = useState([''])
  const [pathway, setPathway] = useState('')
  const [confidence, setConfidence] = useState(null)

  const trialIds = ids.map((x) => x.trim()).filter(Boolean)
  const ready = trialIds.length > 0 && confidence !== null

  const updateId = (index, value) => {
    setIds((prev) => prev.map((v, i) => (i === index ? value : v)))
  }

  const addRow = () => {
    if (ids.length < maxAnswers) setIds((prev) => [...prev, ''])
  }

  return (
    <form
      className="study-task-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (!ready) return
        const payload = {
          task: 'trial_match',
          answer: { trial_ids: trialIds.slice(0, maxAnswers), access_pathway: pathway.trim() || undefined },
          confidence,
          region,
        }
        onEvent('task_answer_submitted', payload)
        onSubmit(payload)
      }}
    >
      <h2>Trial matching</h2>
      <p className="claim">{question}</p>
      <p className="small muted">Region: {REGION_LABELS[region] ?? region}. Up to {maxAnswers} trial ID(s).</p>
      {ids.map((id, i) => (
        <label key={i}>
          Trial ID {i + 1}
          <input value={id} onChange={(e) => updateId(i, e.target.value)} />
        </label>
      ))}
      {ids.length < maxAnswers ? (
        <button type="button" className="study-button study-button--ghost" onClick={addRow}>
          Add another trial ID
        </button>
      ) : null}
      <label>
        Access pathway note (optional)
        <textarea rows={2} value={pathway} onChange={(e) => setPathway(e.target.value)} />
      </label>
      <RatingSlider
        id="trial-conf"
        label="How confident are you in these trial choices?"
        low="Not at all"
        high="Certain"
        value={confidence}
        onChange={setConfidence}
        onCommit={(v) => onEvent('confidence_set', { task: 'trial_match', value: v })}
      />
      <button type="submit" className="study-button" disabled={!ready}>
        Continue
      </button>
    </form>
  )
}

export function AssessmentFlagsStep({ findings, onEvent, onSubmit }) {
  const [flags, setFlags] = useState({})
  const [confidence, setConfidence] = useState({})

  const complete = findings.every((f) => flags[f.id] !== undefined && confidence[f.id] !== undefined)

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
        onSubmit({ flags, confidence })
      }}
    >
      <h2>Your assessment</h2>
      <p className="small muted">
        For each finding, say whether you think it is valid and supported, and how confident you are.
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
      <button type="submit" className="study-button" disabled={!complete}>
        Continue
      </button>
    </form>
  )
}

export function DecisionTaskStep({ options, prompt, rationalePrompt, onEvent, onSubmit }) {
  const [decision, setDecision] = useState(null)
  const [rationale, setRationale] = useState('')
  const needsRationale = Boolean(rationalePrompt)
  const rationaleOk = !needsRationale || rationale.trim().length > 0
  const complete = decision !== null && rationaleOk

  return (
    <form
      className="study-assessment"
      onSubmit={(e) => {
        e.preventDefault()
        if (!complete) return
        const payload = { decision, rationale: rationale.trim() }
        if (needsRationale) {
          onEvent('task_answer_submitted', {
            task: 'decision_rationale',
            answer: rationale.trim(),
            decision,
          })
        }
        onSubmit(payload)
      }}
    >
      <h2>Clinical decision</h2>
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
      </fieldset>
      {needsRationale ? (
        <fieldset className="study-assess-finding">
          <legend>{rationalePrompt}</legend>
          <textarea rows={4} maxLength={2000} value={rationale} onChange={(e) => setRationale(e.target.value)} />
        </fieldset>
      ) : (
        <label className="study-rationale">
          Rationale (optional)
          <textarea rows={3} maxLength={2000} value={rationale} onChange={(e) => setRationale(e.target.value)} />
        </label>
      )}
      <button type="submit" className="study-button" disabled={!complete}>
        Continue
      </button>
    </form>
  )
}