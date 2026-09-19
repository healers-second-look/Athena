import { describe, expect, it, vi } from 'vitest'
import { createLogger } from './logger.js'

const base = { participantId: 'P01', sessionId: 'S1', caseId: 'pilot-001', arm: 'diff_first' }

function clock(startMs = Date.parse('2026-01-01T09:00:00Z')) {
  let t = startMs
  return { now: () => new Date(t), advance: (ms) => (t += ms) }
}

describe('study event logger', () => {
  it('stamps every event with participant, session, case, arm and a client time', async () => {
    const send = vi.fn().mockResolvedValue({})
    const c = clock()
    const log = createLogger({ ...base, send, now: c.now })
    log.log('case_opened', { position: 1 })
    await log.flush()
    expect(send).toHaveBeenCalledTimes(1)
    expect(send.mock.calls[0][0][0]).toEqual({
      participant_id: 'P01',
      session_id: 'S1',
      case_id: 'pilot-001',
      arm: 'diff_first',
      event_type: 'case_opened',
      client_ts: '2026-01-01T09:00:00.000Z',
      payload: { position: 1 },
    })
  })

  it('flushes on its own once a batch is large enough', async () => {
    const send = vi.fn().mockResolvedValue({})
    const log = createLogger({ ...base, send })
    for (let i = 0; i < 20; i++) log.log('finding_opened', { i })
    await log.flush()
    expect(send).toHaveBeenCalled()
    expect(log.pending()).toBe(0)
  })

  it('keeps events when the server is unreachable and reports the error', async () => {
    const send = vi.fn().mockRejectedValue(new Error('offline'))
    const onError = vi.fn()
    const log = createLogger({ ...base, send, onError })
    log.log('case_opened')
    log.log('flag_set', { finding_id: 'f1' })
    await log.flush()
    expect(log.pending()).toBe(2) // nothing lost
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'offline' }))
  })

  it('retries kept events, in their original order, on the next flush', async () => {
    const send = vi
      .fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({})
    const log = createLogger({ ...base, send })
    log.log('case_opened')
    await log.flush()
    log.log('case_submitted')
    await log.flush()
    expect(log.pending()).toBe(0)
    const sent = send.mock.calls.at(-1)[0].map((e) => e.event_type)
    expect(sent).toEqual(['case_opened', 'case_submitted'])
  })

  it('a caller awaiting flush waits for a send already in flight, then drains the rest', async () => {
    let release
    const gate = new Promise((resolve) => (release = resolve))
    const send = vi.fn().mockImplementationOnce(() => gate).mockResolvedValue({})
    const log = createLogger({ ...base, send })
    log.log('case_opened')
    const first = log.flush()
    await new Promise((r) => setTimeout(r, 0)) // send #1 is now in flight, blocked on the gate
    log.log('case_submitted')
    let secondDone = false
    const second = log.flush().then(() => (secondDone = true))
    await new Promise((r) => setTimeout(r, 0))
    expect(secondDone).toBe(false) // must not return early just because #1 is running
    release({})
    await Promise.all([first, second])
    expect(secondDone).toBe(true)
    expect(log.pending()).toBe(0)
    expect(send).toHaveBeenCalledTimes(2)
  })

  it('records a gap longer than the threshold as an idle period, and only then', async () => {
    const send = vi.fn().mockResolvedValue({})
    const c = clock()
    const log = createLogger({ ...base, send, now: c.now, idleThresholdMs: 60_000 })
    c.advance(30_000)
    log.noteInput() // 30 s: fine
    c.advance(90_000)
    log.noteInput() // 90 s: idle
    await log.flush()
    const events = send.mock.calls.flatMap((call) => call[0])
    expect(events.map((e) => e.event_type)).toEqual(['idle_period'])
    expect(events[0].payload.seconds).toBe(90)
  })
})
