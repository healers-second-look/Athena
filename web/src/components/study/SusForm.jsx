import { useState } from 'react'

// Standard SUS items with the rated thing named, the usual adaptation of SUS:
// "this system" is ambiguous in the usual-care block, where there is no system.
export const SUS_ITEM_TEMPLATES = [
  'I think that I would like to use {it} frequently.',
  'I found {it} unnecessarily complex.',
  'I thought {it} {was} easy to use.',
  'I think that I would need the support of a technical person to use {it}.',
  'I found the various functions in {it} were well integrated.',
  'I thought there was too much inconsistency in {it}.',
  'I would imagine that most people would learn to use {it} very quickly.',
  'I found {it} very cumbersome to use.',
  'I felt very confident using {it}.',
  'I needed to learn a lot of things before I could get going with {it}.',
]

export function susItems(armLabel) {
  const usual = armLabel === 'usual_care'
  const it = usual ? 'my usual tools' : 'Athena'
  const was = usual ? 'were' : 'was'
  return SUS_ITEM_TEMPLATES.map((t) => t.replace('{it}', it).replace('{was}', was))
}

export const SUS_ITEMS = susItems('athena_full')

export default function SusForm({ armLabel, onSubmit, onEvent }) {
  const items = susItems(armLabel)
  const [scores, setScores] = useState(() => Object.fromEntries(items.map((_, i) => [i, null])))

  const complete = items.every((_, i) => scores[i] !== null)

  return (
    <form
      className="study-sus"
      onSubmit={(e) => {
        e.preventDefault()
        if (!complete) return
        const responses = items.map((text, i) => ({ item: i + 1, text, score: scores[i] }))
        onEvent('sus_submitted', { arm: armLabel, responses })
        onSubmit({ responses })
      }}
    >
      <h2>Usability</h2>
      <p className="small muted">
        For the {armLabel === 'usual_care' ? 'usual-care' : 'Athena'} block you just finished: rate each
        statement from 1 (strongly disagree) to 5 (strongly agree).
      </p>
      {items.map((text, i) => (
        <fieldset key={i} className="study-sus-item">
          <legend>{text}</legend>
          <div className="study-sus-scale">
            {[1, 2, 3, 4, 5].map((n) => (
              <label key={n} className="study-choice">
                <input
                  type="radio"
                  name={`sus-${i}`}
                  checked={scores[i] === n}
                  onChange={() => setScores((prev) => ({ ...prev, [i]: n }))}
                />
                {n}
              </label>
            ))}
          </div>
        </fieldset>
      ))}
      <button type="submit" className="study-button" disabled={!complete}>
        Continue
      </button>
    </form>
  )
}