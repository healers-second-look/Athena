import { useState } from 'react'
import RatingSlider from './RatingSlider.jsx'

// Raw NASA-TLX (Hart & Staveland, 1988): six subscales, each 0-100, unweighted.
// Wording is the published item text.
export const TLX_ITEMS = [
  { key: 'mental', label: 'Mental demand: how mentally demanding was the task?', low: 'Very low', high: 'Very high' },
  { key: 'physical', label: 'Physical demand: how physically demanding was the task?', low: 'Very low', high: 'Very high' },
  { key: 'temporal', label: 'Temporal demand: how hurried or rushed was the pace of the task?', low: 'Very low', high: 'Very high' },
  { key: 'performance', label: 'Performance: how successful were you in accomplishing what you were asked to do?', low: 'Perfect', high: 'Failure' },
  { key: 'effort', label: 'Effort: how hard did you have to work to accomplish your level of performance?', low: 'Very low', high: 'Very high' },
  { key: 'frustration', label: 'Frustration: how insecure, discouraged, irritated, stressed, and annoyed were you?', low: 'Very low', high: 'Very high' },
]

export default function TlxForm({ onSubmit }) {
  const [values, setValues] = useState({})
  const complete = TLX_ITEMS.every((item) => values[item.key] !== undefined)
  return (
    <form
      className="study-assessment"
      onSubmit={(e) => {
        e.preventDefault()
        if (complete) onSubmit(values)
      }}
    >
      <h2>About that case</h2>
      <p className="small muted">Rate the case you just reviewed.</p>
      {TLX_ITEMS.map((item) => (
        <RatingSlider
          key={item.key}
          id={`tlx-${item.key}`}
          label={item.label}
          low={item.low}
          high={item.high}
          step={5}
          value={values[item.key] ?? null}
          onChange={(v) => setValues((prev) => ({ ...prev, [item.key]: v }))}
        />
      ))}
      <button type="submit" className="study-button" disabled={!complete}>
        Continue
      </button>
    </form>
  )
}
