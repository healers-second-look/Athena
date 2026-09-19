// Chronological event list, the same events in the diff-first and dashboard
// arms. (The chat arm gets them as context, not as a screen.)
//
// `highlightNew` marks the update events, as the shipped case dashboard does
// once it knows what changed. That highlight is a piece of the diff, so only
// the diff-first arm turns it on; the dashboard arm shows a plain timeline.
export default function StudyTimeline({
  baselineEvents = [],
  updateEvents = [],
  highlightNew = false,
}) {
  const events = [...baselineEvents, ...updateEvents].sort((a, b) =>
    a.occurred_on.localeCompare(b.occurred_on),
  )
  const updateIds = new Set(updateEvents.map((e) => e.id))
  if (!events.length) return <p className="muted">No events recorded for this case.</p>
  return (
    <ol className="timeline">
      {events.map((event) => (
        <li key={event.id} className={highlightNew && updateIds.has(event.id) ? 'is-new' : undefined}>
          <div className="event-type">{event.event_type.replace(/_/g, ' ')}</div>
          <div>{event.summary}</div>
          <div className="small muted">
            {event.occurred_on}
            {event.source_document ? ` · ${event.source_document}` : null}
          </div>
        </li>
      ))}
    </ol>
  )
}
