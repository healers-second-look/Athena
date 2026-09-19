import { useState } from 'react'

// Post-review memory probe (protocol section 6): asked after the reviewer has
// left the case screen, with the case no longer visible. The options are real
// update events mixed with authored distractors, under opaque ids.
export default function RecallForm({ options, onSubmit }) {
  const [selected, setSelected] = useState(new Set())
  const toggle = (id) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  return (
    <form
      className="study-assessment"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit([...selected])
      }}
    >
      <h2>What changed?</h2>
      <p className="small muted">
        Without looking back: which of these changed since the previous visit? Select all that
        apply, or none.
      </p>
      {options.map((option) => (
        <label key={option.id} className="study-choice">
          <input
            type="checkbox"
            checked={selected.has(option.id)}
            onChange={() => toggle(option.id)}
          />
          {option.text}
        </label>
      ))}
      <button type="submit" className="study-button">
        Finish case
      </button>
    </form>
  )
}
