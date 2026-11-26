import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import useAsync from '../api/useAsync.js'
import { getMe, postEvents } from '../api/studyClient.js'
import { createLogger } from '../study/logger.js'
import SusForm from '../components/study/SusForm.jsx'
import StudyCase from './StudyCase.jsx'

export default function EnrolledStudyRunner() {
  const schedule = useAsync(() => getMe(), [])
  const [cursor, setCursor] = useState(0)
  const [pendingSus, setPendingSus] = useState(null)
  const [blockBreak, setBlockBreak] = useState(false)

  const items = useMemo(() => {
    if (!schedule.data) return []
    const completed = new Set(schedule.data.completed_case_ids)
    return schedule.data.items.filter((item) => !completed.has(item.case_id))
  }, [schedule.data])

  if (schedule.loading) return <div className="wrap"><p className="muted">Loading study…</p></div>
  if (schedule.error) {
    return (
      <div className="wrap">
        <p className="study-log-error" role="alert">
          Could not load your schedule.
        </p>
        <Link to="/study">Back to study home</Link>
      </div>
    )
  }

  const { participant_id, unreviewed } = schedule.data

  if (pendingSus) {
    const susLogger = createLogger({
    participantId: participant_id,
    sessionId: `sus-${pendingSus.arm}`,
    // The API rejects events without a known case id, so a block-level SUS is
    // filed under the block's last case (payload carries the arm it rates).
    caseId: pendingSus.caseId,
    arm: pendingSus.arm,
    send: postEvents,
  })
    return (
      <div className="wrap">
        <SusForm
          armLabel={pendingSus.arm}
          onEvent={susLogger.log}
          onSubmit={async () => {
            await susLogger.flush()
            setPendingSus(null)
            setCursor(pendingSus.nextIndex)
            // Another block follows: stop here so the doctor can take a break.
            setBlockBreak(pendingSus.nextIndex < items.length)
          }}
        />
      </div>
    )
  }

  if (cursor >= items.length) {
    return (
      <div className="wrap">
        <h1>Study complete</h1>
        <p>Thank you. You have finished every case in your schedule, and your answers are saved.</p>
        <Link to="/study" className="study-button study-link-button">
          Study home
        </Link>
      </div>
    )
  }

  if (blockBreak) {
    const next = items[cursor]
    return (
      <div className="wrap">
        <h1>First block complete</h1>
        <p>Your answers are saved. You can take a break now and continue later from study home.</p>
        <p>
          Next block:{' '}
          <strong>
            {next.arm === 'usual_care' ? 'usual tools, without Athena' : 'with Athena (review and chat)'}
          </strong>
          .
        </p>
        <button type="button" className="study-button" onClick={() => setBlockBreak(false)}>
          Start next block
        </button>{' '}
        <Link to="/study" className="study-button study-button--ghost study-link-button">
          Take a break
        </Link>
      </div>
    )
  }

  const item = items[cursor]
  const completedCount = schedule.data.completed_case_ids.length

  const onCaseDone = () => {
    const nextIndex = cursor + 1
    const nextItem = items[nextIndex]
    const armChanged = nextItem && nextItem.arm !== item.arm
    const atEnd = nextIndex >= items.length
    if (armChanged || atEnd) {
      setPendingSus({ arm: item.arm, caseId: item.case_id, nextIndex })
    } else {
      setCursor(nextIndex)
    }
  }

  return (
    <StudyCase
      key={`${item.case_id}-${item.arm}-${cursor}`}
      participantId={participant_id}
      item={item}
      position={completedCount + cursor + 1}
      total={schedule.data.items.length}
      unreviewed={unreviewed}
      onDone={onCaseDone}
      enrolled
    />
  )
}