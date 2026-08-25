import { useEffect, useRef, useState } from 'react'

// The three actions are case/models.py's DECISION_ACTIONS verbatim. Issue #88
// says "accept / dismiss / defer"; the data model calls them investigating /
// rejected / deferred, and the model wins — a UI verb that does not exist in
// DECISION_ACTIONS would have to be translated somewhere, and that mapping is
// exactly the kind of thing that drifts.
export const ACTIONS = [
  { id: 'investigating', key: 'i', label: 'Investigating', hint: 'take this one on' },
  { id: 'deferred', key: 'd', label: 'Defer', hint: 'not now, keep it open' },
  { id: 'rejected', key: 'r', label: 'Reject', hint: 'not worth pursuing' },
]

export const ACTION_KEYS = new Set(ACTIONS.map((a) => a.key))
export const actionForKey = (key) => ACTIONS.find((a) => a.key === key) || null

// A decision, keyboard-reachable, that CANNOT be completed without a reason.
//
// This is the whole risk in #88 part 2, and the issue says so: "A keyboard
// path that lets someone skip the reason field would be worse than no
// keyboard path." case/models.py makes Decision.reason NOT NULL and comments
// it "required, even for investigating" — so the fast path must not be a way
// around it.
//
// The shape that holds that: pressing i/d/r does not record anything. It
// arms an action and moves focus into the reason field. The decision only
// exists once a reason does. There is deliberately no key that both chooses
// an action and submits, because a single keystroke that writes an unexplained
// decision is the failure mode — and a hurried user would find it.
export default function QueueDecision({ action, questionText, onCancel, onSubmit }) {
  const [reason, setReason] = useState('')
  const inputRef = useRef(null)

  // Focus follows the action. Arming a decision and leaving focus on the list
  // would mean the next keystroke navigates instead of typing the reason.
  useEffect(() => {
    inputRef.current?.focus()
  }, [action])

  const ready = reason.trim().length > 0

  const submit = (event) => {
    event?.preventDefault()
    if (!ready) return
    onSubmit({ action: action.id, reason: reason.trim() })
  }

  const onKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      onCancel()
      return
    }
    // Enter submits, but only through the same gate the button uses. Shift
    // gives a newline, since a reason is prose.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.stopPropagation()
      submit()
      return
    }
    // Everything else stays here rather than reaching the list's handler --
    // otherwise typing "defer the biopsy" navigates the worklist.
    event.stopPropagation()
  }

  return (
    <form className="decision" onSubmit={submit} onKeyDown={onKeyDown}>
      <div className="decision-head">
        {action.label}
        <span className="small muted"> — {questionText}</span>
      </div>
      <label className="small muted" htmlFor="queue-reason">
        Reason (required for every decision, including “investigating”)
      </label>
      <textarea
        id="queue-reason"
        ref={inputRef}
        rows={2}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        aria-describedby="queue-reason-help"
      />
      <div className="actions">
        <button type="submit" disabled={!ready} title={ready ? undefined : 'A reason is required'}>
          Record {action.label.toLowerCase()}
        </button>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
        <span id="queue-reason-help" className="small muted">
          {ready ? 'Enter to record · Esc to cancel' : 'A reason is required · Esc to cancel'}
        </span>
      </div>
    </form>
  )
}
