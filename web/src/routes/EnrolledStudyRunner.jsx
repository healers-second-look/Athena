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
          }}
        />
      </div>
    )
  }

  if (cursor >= items.length) {
    return (
      <div className="wrap">
        <h1>Block complete</h1>
        <p>Thank you. Return to study home when you are ready.</p>
        <Link to="/study" className="study-button study-link-button">
          Study home
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