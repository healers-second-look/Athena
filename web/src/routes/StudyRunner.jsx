import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import useAsync from '../api/useAsync.js'
import {
  getRecallOptions,
  getSchedule,
  getStudyCase,
  postEvents,
  studyChatApi,
} from '../api/studyClient.js'
import { createLogger } from '../study/logger.js'
import AssessmentForm from '../components/study/AssessmentForm.jsx'
import DashboardView from '../components/study/DashboardView.jsx'
import DiffFirstView from '../components/study/DiffFirstView.jsx'
import RecallForm from '../components/study/RecallForm.jsx'
import TlxForm from '../components/study/TlxForm.jsx'
import ChatInterface from './ChatInterface.jsx'

// The diff-first evaluation study runner (issue #136).
//
// One reviewer walks a fixed schedule of (case, arm) pairs computed server-side
// (study/assignment.py). Per case:  review  ->  assess  ->  tlx  ->  recall.
// The review step is the only step that differs by arm; assessment, workload
// and recall are the same standard forms in every arm.
//
// Nothing is scored here. Every action is one event in the append-only log, and
// outcomes are computed offline against ground truth the browser never sees.

const progressKey = (reviewerIndex) => `athena-study-progress-${reviewerIndex}`

function readProgress(reviewerIndex) {
  try {
    const value = Number(window.localStorage.getItem(progressKey(reviewerIndex)))
    return Number.isInteger(value) && value >= 0 ? value : 0
  } catch {
    return 0 // storage can be blocked; the server-side log is the record anyway
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
    />
  )
}

function newSessionId() {
  return `S${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

function StudyCase({ participantId, item, position, total, unreviewed, onDone }) {
  const view = useAsync(() => getStudyCase(item.case_id, item.arm), [item.case_id, item.arm])
  const [phase, setPhase] = useState('review')
  const [logError, setLogError] = useState(null)
  const [saveError, setSaveError] = useState(null)
  const [chatSessionId, setChatSessionId] = useState(null)
  const [chatError, setChatError] = useState(null)
  const openedRef = useRef(false)
  const chatRequestedRef = useRef(false)
  const finalizedRef = useRef(false)

  const logger = useMemo(
    () =>
      createLogger({
        participantId,
        sessionId: newSessionId(),
        caseId: item.case_id,
        arm: item.arm,
        send: postEvents,
        onError: setLogError,
      }),
    [participantId, item.case_id, item.arm],
  )

  // Log case_opened once the case has actually rendered (not before it loads),
  // so "time to complete" starts when the reviewer could first see something.
  useEffect(() => {
    if (view.data && !openedRef.current) {
      openedRef.current = true
      logger.log('case_opened', { position, total })
    }
  }, [view.data, logger, position, total])

  // Flush on a timer, and record attention: tab visibility and idle gaps.
  useEffect(() => {
    const timer = setInterval(() => logger.flush(), 2000)
    const onVisibility = () =>
      logger.log(document.hidden ? 'page_hidden' : 'page_visible', {})
    const onInput = () => logger.noteInput()
    document.addEventListener('visibilitychange', onVisibility)
    const inputs = ['pointerdown', 'keydown', 'scroll', 'pointermove']
    inputs.forEach((name) => window.addEventListener(name, onInput, { passive: true }))
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
      inputs.forEach((name) => window.removeEventListener(name, onInput))
      logger.flush()
    }
  }, [logger])

  // Arm C: open a study chat session about this case.
  useEffect(() => {
    if (item.arm !== 'chat' || chatRequestedRef.current) return
    chatRequestedRef.current = true
    studyChatApi
      .createSession({ case_id: item.case_id })
      .then((s) => setChatSessionId(s.id))
      .catch((error) => setChatError(error))
  }, [item.arm, item.case_id])

  // The chat UI uses its own page-level styles.
  const chatScreen = item.arm === 'chat' && phase === 'review'
  useEffect(() => {
    document.body.classList.toggle('chat-surface', chatScreen)
    return () => document.body.classList.remove('chat-surface')
  }, [chatScreen])

  // Never advance on unsaved data: if the final flush did not empty the buffer,
  // say so and let the reviewer retry rather than silently losing answers.
  const finish = async () => {
    await logger.flush()
    if (logger.pending() > 0) {
      setSaveError('Your answers could not be saved yet. Check the connection and try again.')
      return
    }
    setSaveError(null)
    onDone()
  }

  const banner = (
    <>
      {unreviewed ? (
        <div className="study-debug-banner" role="alert">
          HARNESS DEBUG — unreviewed pilot cases. This is not a study run.
        </div>
      ) : null}
      {logError ? (
        <div className="study-log-error" role="alert">
          Study logging is failing: {String(logError.message || logError)}. Events are kept and
          retried.
        </div>
      ) : null}
    </>
  )

  if (view.loading) return <div className="wrap">{banner}<p className="muted">Loading case…</p></div>
  if (view.error) {
    return (
      <div className="wrap">
        {banner}
        <div className="card card-computed" role="alert">
          <div className="badge badge-computed">Could not load</div>
          <p className="claim">The case could not be loaded.</p>
          <p className="small muted">{String(view.error.message || view.error)}</p>
        </div>
      </div>
    )
  }

  const data = view.data.case
  const onFindingOpened = (findingId) => logger.log('finding_opened', { finding_id: findingId })
  const onCitationOpened = (findingId, url) =>
    logger.log('citation_opened', { source: 'card', finding_id: findingId, url })

  if (phase === 'review') {
    return (
      <div className="study-shell">
        {banner}
        <header className="study-bar">
          <span>
            Case {position} of {total}
          </span>
          <button type="button" className="study-button" onClick={() => setPhase('assess')}>
            Finish review →
          </button>
        </header>
        {item.arm === 'diff_first' ? (
          <div className="wrap">
            <DiffFirstView
              view={data}
              onFindingOpened={onFindingOpened}
              onCitationOpened={onCitationOpened}
            />
          </div>
        ) : null}
        {item.arm === 'dashboard' ? (
          <div className="wrap">
            <DashboardView
              view={data}
              onFindingOpened={onFindingOpened}
              onCitationOpened={onCitationOpened}
            />
          </div>
        ) : null}
        {item.arm === 'chat' ? (
          <div className="study-chat-frame">
            {chatError ? (
              <div className="wrap">
                <p className="muted">Could not open the chat: {String(chatError.message)}</p>
              </div>
            ) : chatSessionId ? (
              <ChatInterface
                studySessionId={chatSessionId}
                studyClient={studyChatApi}
                onStudyEvent={logger.log}
              />
            ) : (
              <div className="wrap"><p className="muted">Opening chat…</p></div>
            )}
          </div>
        ) : null}
      </div>
    )
  }

  if (phase === 'assess') {
    return (
      <div className="wrap">
        {banner}
        <AssessmentForm
          findings={data.findings}
          options={data.decision_options}
          prompt={data.decision_prompt}
          onEvent={logger.log}
          onSubmit={({ flags, confidence, decision, rationale }) => {
            logger.log('decision_submitted', { decision, rationale, flags, confidence })
            logger.flush()
            setPhase('tlx')
          }}
        />
      </div>
    )
  }

  if (phase === 'tlx') {
    return (
      <div className="wrap">
        {banner}
        <TlxForm
          onSubmit={(values) => {
            logger.log('tlx_submitted', values)
            setPhase('recall')
          }}
        />
      </div>
    )
  }

  return (
    <div className="wrap">
      {banner}
      <RecallStep
        caseId={item.case_id}
        onSubmit={(selected) => {
          // Log once: a retry after a failed save must not duplicate the events.
          if (!finalizedRef.current) {
            finalizedRef.current = true
            logger.log('recall_submitted', { selected })
            logger.log('case_submitted', {})
          }
          finish()
        }}
      />
      {saveError ? (
        <p className="study-log-error" role="alert">
          {saveError}
        </p>
      ) : null}
    </div>
  )
}

// Fetched only now, after the reviewer has left the case screen, so the probe's
// options were never in the page during review.
function RecallStep({ caseId, onSubmit }) {
  const recall = useAsync(() => getRecallOptions(caseId), [caseId])
  if (recall.loading) return <p className="muted">Loading…</p>
  if (recall.error) {
    return <p className="muted">Could not load the last question: {String(recall.error.message)}</p>
  }
  return <RecallForm options={recall.data.options} onSubmit={onSubmit} />
}
