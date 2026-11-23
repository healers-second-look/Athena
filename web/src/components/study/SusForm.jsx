import { useState } from 'react'

export const SUS_ITEMS = [
  'I think that I would like to use this system frequently.',
  'I found the system unnecessarily complex.',
  'I thought the system was easy to use.',
  'I think that I would need the support of a technical person to use this system.',
  'I found the various functions in this system were well integrated.',
  'I thought there was too much inconsistency in this system.',
  'I would imagine that most people would learn to use this system very quickly.',
  'I found the system very cumbersome to use.',
  'I felt very confident using the system.',
  'I needed to learn a lot of things before I could get going with this system.',
]

export default function SusForm({ armLabel, onSubmit, onEvent }) {
  const [scores, setScores] = useState(() => Object.fromEntries(SUS_ITEMS.map((_, i) => [i, null])))

  const complete = SUS_ITEMS.every((_, i) => scores[i] !== null)

  return (
    <form
      className="study-sus"
      onSubmit={(e) => {
        e.preventDefault()
        if (!complete) return
        const responses = SUS_ITEMS.map((text, i) => ({ item: i + 1, text, score: scores[i] }))
        onEvent('sus_submitted', { arm: armLabel, responses })
        onSubmit({ responses })
      }}
    >
      <h2>System usability (brief)</h2>
      <p className="small muted">
        For the {armLabel === 'usual_care' ? 'usual-care' : 'Athena'} block you just finished: rate each
        statement from 1 (strongly disagree) to 5 (strongly agree).
      </p>
      {SUS_ITEMS.map((text, i) => (
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