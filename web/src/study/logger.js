// Batching event logger for the diff-first study (issue #136).
//
// Pure of the DOM and of `fetch`: the transport, the clock and the idle
// threshold are injected, so this is unit-testable and so the exact same
// logic runs in every arm. Nothing here scores anything -- outcomes are
// computed offline from the event log plus the case set's ground truth.
//
// Loss policy: a failed send puts the events back at the front of the buffer
// and reports the error; it never drops them silently. A study that quietly
// loses events would look like reviewers who did less.

export const IDLE_THRESHOLD_MS = 60_000
const FLUSH_SIZE = 20
const BATCH_SIZE = 100
const MAX_BUFFER = 500

export function createLogger({
  participantId,
  sessionId,
  caseId,
  arm,
  send,
  now = () => new Date(),
  onError = () => {},
  idleThresholdMs = IDLE_THRESHOLD_MS,
}) {
  let buffer = []
  let lastInputAt = now().getTime()
  // Flushes are serialised on one chain, so a caller that awaits flush() always
  // waits for any send already in flight and then for the rest of the buffer --
  // never returns early because another flush happened to be running.
  let chain = Promise.resolve()

  const record = (eventType, payload = {}) => {
    buffer.push({
      participant_id: participantId,
      session_id: sessionId,
      case_id: caseId,
      arm,
      event_type: eventType,
      client_ts: now().toISOString(),
      payload,
    })
    if (buffer.length > MAX_BUFFER) {
      // Only reachable if the server has been unreachable for a long time.
      onError(new Error(`study event buffer exceeded ${MAX_BUFFER}; oldest events dropped`))
      buffer = buffer.slice(-MAX_BUFFER)
    }
    if (buffer.length >= FLUSH_SIZE) flush()
  }

  function flush() {
    chain = chain.then(async () => {
      while (buffer.length > 0) {
        const batch = buffer.splice(0, BATCH_SIZE)
        try {
          await send(batch)
        } catch (error) {
          buffer = batch.concat(buffer)
          onError(error)
          return // stop on failure; the next flush retries
        }
      }
    })
    return chain
  }

  // Call on every user input. If the gap since the previous input exceeded the
  // threshold, that gap is recorded as an idle period (protocol section 6:
  // time is reported with idle both included and excluded).
  function noteInput() {
    const t = now().getTime()
    const gap = t - lastInputAt
    if (gap > idleThresholdMs) record('idle_period', { seconds: Math.round(gap / 1000) })
    lastInputAt = t
  }

  return {
    log: record,
    noteInput,
    flush,
    pending: () => buffer.length,
  }
}
