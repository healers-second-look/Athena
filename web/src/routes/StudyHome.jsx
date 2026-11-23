import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import useAsync from '../api/useAsync.js'
import { clearStudyToken, getMe, withdraw } from '../api/studyClient.js'

function blockProgress(items, completed) {
  const done = new Set(completed)
  const blocks = []
  let currentArm = null
  let block = null
  for (const item of items) {
    if (item.arm !== currentArm) {
      currentArm = item.arm
      block = { arm: item.arm, total: 0, done: 0 }
      blocks.push(block)
    }
    block.total += 1
    if (done.has(item.case_id)) block.done += 1
  }
  return blocks
}

export default function StudyHome() {
  const navigate = useNavigate()
  const schedule = useAsync(() => getMe(), [])
  const [withdrawing, setWithdrawing] = useState(false)
  const [error, setError] = useState(null)

  if (schedule.loading) return <div className="wrap"><p className="muted">Loading…</p></div>
  if (schedule.error) {
    return (
      <div className="wrap">
        <p className="study-log-error" role="alert">
          Could not load your study schedule.
        </p>
        <Link to="/join">Return to join</Link>
      </div>
    )
  }

  const { participant_id, items, completed_case_ids, unreviewed } = schedule.data
  const completed = new Set(completed_case_ids)
  const remaining = items.filter((i) => !completed.has(i.case_id))
  const allDone = remaining.length === 0
  const blocks = blockProgress(items, completed_case_ids)

  const signOut = () => {
    clearStudyToken()
    navigate('/join')
  }

  const doWithdraw = async () => {
    if (!window.confirm('Withdraw from the study? You can close the browser at any time, but this marks your withdrawal for the study team.')) {
      return
    }
    setWithdrawing(true)
    setError(null)
    try {
      await withdraw()
      clearStudyToken()
      navigate('/join')
    } catch {
      setError('Withdrawal could not be recorded. Try again.')
    } finally {
      setWithdrawing(false)
    }
  }

  return (
    <div className="wrap study-home">
      <h1>Study home</h1>
      <p>
        Participant ID: <code>{participant_id}</code>
      </p>
      {unreviewed ? (
        <div className="study-debug-banner" role="alert">
          HARNESS DEBUG — unreviewed pilot cases. This is not a production study run.
        </div>
      ) : null}
      {allDone ? (
        <>
          <p>Thank you. You have completed every case in your schedule.</p>
          <button type="button" className="study-button study-button--ghost" onClick={signOut}>
            Sign out
          </button>
        </>
      ) : (
        <>
          <p>
            Progress: {completed_case_ids.length} of {items.length} cases completed.
          </p>
          <ul className="study-block-progress">
            {blocks.map((b) => (
              <li key={b.arm}>
                {b.arm === 'usual_care' ? 'Usual care' : 'Athena'} block: {b.done}/{b.total}
              </li>
            ))}
          </ul>
          <Link to="/study/run" className="study-button study-link-button">
            {completed_case_ids.length ? 'Continue study' : 'Start study'}
          </Link>
          <button type="button" className="study-button study-button--ghost" onClick={doWithdraw} disabled={withdrawing}>
            Withdraw
          </button>
          <button type="button" className="study-button study-button--ghost" onClick={signOut}>
            Sign out
          </button>
        </>
      )}
      {error ? (
        <p className="study-log-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}