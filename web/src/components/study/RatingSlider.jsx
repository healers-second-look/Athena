// A 0-100 slider that starts "untouched". A default position would be recorded
// as an answer the reviewer never gave, so `value === null` means unanswered and
// the form refuses to submit until it is moved.
//
// Releasing the pointer (or pressing an arrow/Home/End/Page key) counts as an
// answer even if the value did not change: the untouched thumb sits at 50, and a
// reviewer whose honest answer is 50 would otherwise have no way to give it --
// clicking the thumb fires no change event.

const ANSWER_KEYS = new Set([
  'ArrowLeft',
  'ArrowRight',
  'ArrowUp',
  'ArrowDown',
  'Home',
  'End',
  'PageUp',
  'PageDown',
])

export default function RatingSlider({ id, label, low, high, value, onChange, onCommit, step = 1 }) {
  const commit = (raw) => {
    const v = Number(raw)
    onChange(v)
    onCommit?.(v)
  }
  return (
    <div className="rating">
      <label htmlFor={id} className="rating-label">
        {label}
      </label>
      <div className="rating-row">
        <span className="small muted rating-end">{low}</span>
        <input
          id={id}
          type="range"
          min={0}
          max={100}
          step={step}
          value={value ?? 50}
          className={value === null ? 'rating-untouched' : undefined}
          onChange={(e) => onChange(Number(e.target.value))}
          onPointerUp={(e) => commit(e.target.value)}
          onKeyUp={(e) => {
            // A Tab key-up lands on the newly focused slider and is not an answer.
            if (ANSWER_KEYS.has(e.key)) commit(e.target.value)
          }}
        />
        <span className="small muted rating-end">{high}</span>
        <output className="rating-value">{value === null ? '—' : value}</output>
      </div>
    </div>
  )
}
