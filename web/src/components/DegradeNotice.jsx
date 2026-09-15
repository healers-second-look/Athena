// A lane whose live lookup failed, labelled as such.
//
// The distinction this exists to preserve: a panel empty because a lookup
// failed currently renders identically to one empty because nothing matched.
// The reader cannot tell which, and the two mean opposite things -- one says
// "we checked, there is nothing", the other says "we did not manage to
// check". Treating the second as the first is the same class of error as a
// swallowed VinaError or a computed verdict wearing a documented citation: a
// real distinction collapsing into one indistinguishable output.
//
// Shape is docs/api-contracts.md's failure object. Per that document it is
// ALWAYS rendered when produced and never filtered out before reaching the
// frontend, so there is no severity threshold below which this stays quiet.
export default function DegradeNotice({ failure }) {
  if (!failure) return null
  const { reason, retryable, last_known_at: lastKnown, lane } = failure
  return (
    <div className="degraded" role="status">
      <div className="degraded-head">
        {lane ? `${lane} lookup unavailable` : 'Lookup unavailable'}
      </div>
      <p className="small">{reason}</p>
      {lastKnown ? (
        // Stale data is useful and must never be passed off as current.
        <p className="small">
          Showing last known state from <strong>{String(lastKnown).slice(0, 10)}</strong>. This is
          not a live result.
        </p>
      ) : (
        <p className="small">No cached result is available for this lane.</p>
      )}
      <p className="small muted">
        {retryable
          ? 'This may succeed on retry. Everything else on this page is local and unaffected.'
          : 'This will not succeed on retry without a change upstream.'}
      </p>
    </div>
  )
}
