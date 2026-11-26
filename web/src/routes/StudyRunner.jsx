import { useState } from 'react'
import { useParams } from 'react-router-dom'
import useAsync from '../api/useAsync.js'
import { getSchedule } from '../api/studyClient.js'
import StudyCase from './StudyCase.jsx'

const progressKey = (reviewerIndex) => `athena-study-progress-${reviewerIndex}`

function readProgress(reviewerIndex) {
  try {
    const value = Number(window.localStorage.getItem(progressKey(reviewerIndex)))
    return Number.isInteger(value) && value >= 0 ? value : 0
  } catch {
    return 0
  }
}

function writeProgress(reviewerIndex, index) {
  try {
    window.localStorage.setItem(progressKey(reviewerIndex), String(index))
  } catch {
    /* see readProgress */
  }
}

export default function StudyRunner() {
  const reviewerIndex = Number(useParams().reviewerIndex)
  const valid = Number.isInteger(reviewerIndex) && reviewerIndex >= 0
  const schedule = useAsync(
    () => (valid ? getSchedule(reviewerIndex) : Promise.reject(new Error('bad reviewer index'))),
    [reviewerIndex],
  )
  const [index, setIndex] = useState(() => (valid ? readProgress(reviewerIndex) : 0))

  if (schedule.loading) return <div className="wrap"><p className="muted">Loading study…</p></div>
  if (schedule.error) {
    return (
      <div className="wrap">
        <div className="card card-computed" role="alert">
          <div className="badge badge-computed">Study unavailable</div>
          <p className="claim">The study schedule could not be loaded.</p>
          <p className="small muted">{String(schedule.error.message || schedule.error)}</p>
          <p className="small muted">
            The server needs <code>ATHENA_STUDY_ENABLED=true</code> and an eligible case set.
          </p>
        </div>
      </div>
    )
  }

  const { items, participant_id: participantId, unreviewed } = schedule.data
  if (index >= items.length) {
    return (
      <div className="wrap">
        <h1>All done</h1>
        <p>Thank you. You have completed every case.</p>
      </div>
    )
  }

  const advance = () => {
    const next = index + 1
    writeProgress(reviewerIndex, next)
    setIndex(next)
  }

  return (
    <StudyCase
      key={`${index}-${items[index].case_id}-${items[index].arm}`}
      participantId={participantId}
      item={items[index]}
      position={index + 1}
      total={items.length}
      unreviewed={unreviewed}
      onDone={advance}
      enrolled={false}
    />
  )
}