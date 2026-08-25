import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import useAsync from '../api/useAsync.js'
import { getQueue } from '../api/client.js'
import { Failure } from './CaseDashboard.jsx'
import DegradeNotice from '../components/DegradeNotice.jsx'
import EmptyState from '../components/EmptyState.jsx'
import QueueDecision, { ACTIONS, actionForKey } from '../components/QueueDecision.jsx'
import useRovingFocus from '../components/useRovingFocus.js'

// §9 — Research Queue. Open questions by priority, and "N suppressed as
// already answered" as a VISIBLE count.
//
// The suppressed count is a deliverable, not a detail: IMPLEMENTATION_PLAN.md
// §4.1 says suppressed questions are returned and never dropped silently, and
// the count is what shows the case has memory — it is the second-order wow
// moment. So it renders as a block, and every suppressed question can be
// expanded to show the prior question it matched. A count nobody can
// interrogate is a number the user has to take on trust.
export default function ResearchQueue() {
  const { id } = useParams()
  const queue = useAsync(() => getQueue(id), [id])

  if (queue.loading) return <p className="muted">Loading queue…</p>
  if (queue.error) return <Failure what="research queue" error={queue.error} />

  const { counts = {}, open = [], suppressed = [], failures = [] } = queue.data
  // Which lanes could not be reached this run. A question in one of them has
  // no findings for a different reason than a question we actually answered,
  // and the two must not render the same way.
  const degradedLanes = new Map(failures.filter((f) => f.lane).map((f) => [f.lane, f]))
  const byPriority = [...open].sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id))

  return (
    <QueueBody
      id={id}
      counts={counts}
      open={open}
      suppressed={suppressed}
      failures={failures}
      degradedLanes={degradedLanes}
      byPriority={byPriority}
    />
  )
}

// Split out so the hooks below sit above the loading/error returns rather
// than after them -- a conditional return before a hook call is the one thing
// the rules of hooks will not forgive.
function QueueBody({ id, counts, open, suppressed, failures, degradedLanes, byPriority }) {
  // Which question a decision is being written against, and which action.
  // Null means the list has focus and the keys navigate.
  const [pending, setPending] = useState(null)
  const { onNavigationKey, itemProps, refocusActive, activeIndex } = useRovingFocus(
    byPriority.length,
  )

  const closeDecision = useCallback(() => {
    setPending(null)
    // Focus must come back to the question it was opened from. Leaving it on
    // a form that just unmounted drops focus to <body>, and the next arrow
    // key does nothing -- the classic way a keyboard path quietly dead-ends.
    refocusActive()
  }, [refocusActive])

  const onKeyDown = (event, question) => {
    // A decision is open; it owns the keyboard until it is dismissed.
    if (pending) return
    if (onNavigationKey(event)) {
      event.preventDefault()
      return
    }
    const action = actionForKey(event.key.toLowerCase())
    if (action) {
      event.preventDefault()
      // Arms the action and focuses the reason field. Records nothing:
      // Decision.reason is NOT NULL and this path must not be the way around
      // it (issue #88).
      setPending({ questionId: question.id, action, question })
    }
  }

  return (
    <>
      <p className="small muted"><Link to={`/cases/${id}`}>← Case dashboard</Link></p>
      <h1>Research queue</h1>
      <p className="small muted">
        {counts.open ?? open.length} open · {counts.answered ?? 0} answered ·{' '}
        {counts.suppressed ?? suppressed.length} suppressed
      </p>

      {failures.length ? (
        <>
          <h2>Coverage</h2>
          {/* Rendered before the questions, not after: a reader who stops
              scrolling must still know the run was incomplete. */}
          {failures.map((f, i) => (
            <DegradeNotice key={`${f.lane}-${i}`} failure={f} />
          ))}
        </>
      ) : null}

      <h2 id="open-questions">Open questions</h2>
      {byPriority.length > 0 ? <KeyboardLegend /> : null}
      {byPriority.length === 0 ? (
        <EmptyState reason="No open questions. Every question raised by the last change set has been answered." />
      ) : (
        <ul className="q-list" aria-labelledby="open-questions">
          {/* A plain list, deliberately NOT role="listbox". A listbox option
              must contain no interactive descendants, and these rows carry
              links to their findings -- claiming listbox here would announce
              a structure that does not match what is inside it. Roving
              tabindex still applies: it collapses N row stops into one, and
              the finding links keep their own stops in document order. */}
          {byPriority.map((q, index) => (
          <li
            className="q"
            key={q.id}
            id={`q-${q.id}`}
            aria-label={`Priority ${q.priority} question: ${q.text}`}
            onKeyDown={(event) => onKeyDown(event, q)}
            {...itemProps(index)}
          >
            <div className="q-priority">Priority {q.priority} · {String(q.kind).replace(/_/g, ' ')}</div>
            <div>{q.text}</div>
            {q.triggered_by?.summary ? (
              <div className="small muted">Triggered by: {q.triggered_by.summary}</div>
            ) : null}
            {q.finding_ids?.length ? (
              <div className="small">
                {q.finding_ids.map((fid, i) => (
                  <span key={fid}>
                    {i > 0 ? ' · ' : ''}
                    <Link to={`/findings/${fid}`}>Finding {fid.slice(-4)}</Link>
                  </span>
                ))}
              </div>
            ) : degradedLanes.has(q.lane) ? (
              // Not "no findings" -- we never got to look. Saying the former
              // here would report a failed lookup as a searched-and-empty
              // result, which is the defect #88 exists to remove.
              <DegradeNotice failure={degradedLanes.get(q.lane)} />
            ) : (
              <EmptyState reason="No findings recorded against this question yet. The lanes it dispatches to were reached and returned nothing." />
            )}

            {pending?.questionId === q.id ? (
              <QueueDecision
                action={pending.action}
                questionText={q.text}
                onCancel={closeDecision}
                onSubmit={({ action, reason }) => {
                  closeDecision()
                  // Subsystem L (issue #13) owns POST /api/findings/{id}/decision.
                  // Until it exists this does not pretend to have saved anything --
                  // the same posture as FindingDetail's ReviewForm. A keyboard path
                  // that silently discarded decisions would be worse than none.
                  window.alert(
                    `Not yet wired: POST /api/questions/${q.id}/decision\n\n` +
                      `action=${action}\nreason=${reason}\n\n` +
                      'Subsystem L (issue #13) owns this endpoint.',
                  )
                }}
              />
            ) : null}
          </li>
        ))}
        </ul>
      )}

      <SuppressedBlock items={suppressed} count={counts.suppressed ?? suppressed.length} />
    </>
  )
}

// Keys nobody can discover are decoration. This is rendered, not hidden in a
// help modal, because the worklist is where someone would look for it.
function KeyboardLegend() {
  return (
    <p className="kbd-legend small muted">
      <kbd>Tab</kbd> into the list, then <kbd>↑</kbd>/<kbd>↓</kbd> to move ·{' '}
      {ACTIONS.map((a, i) => (
        <span key={a.id}>
          {i > 0 ? ' · ' : ''}
          <kbd>{a.key}</kbd> {a.label.toLowerCase()}
        </span>
      ))}{' '}
      · every decision still needs a reason
    </p>
  )
}

function SuppressedBlock({ items, count }) {
  if (!count) return null
  return (
    <div className="suppressed-count">
      <strong>{count} suppressed as already answered</strong>
      <p className="small muted">
        These were raised again by the latest change set and matched a question this
        case has already answered. They are kept, not discarded.
      </p>
      {items.map((q) => (
        <details key={q.id}>
          <summary className="small">{q.text}</summary>
          <div className="small muted">
            Matched: “{q.matched_prior_question?.text}”
            {q.matched_prior_question?.answered_at
              ? ` · answered ${q.matched_prior_question.answered_at.slice(0, 10)}`
              : null}
            {typeof q.similarity === 'number' ? ` · similarity ${q.similarity.toFixed(2)}` : null}
          </div>
        </details>
      ))}
    </div>
  )
}
