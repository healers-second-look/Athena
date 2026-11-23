import { useEffect, useMemo, useRef, useState } from 'react'
import useAsync from '../api/useAsync.js'
import { getRecallOptions, getStudyCase, postEvents, studyChatApi } from '../api/studyClient.js'
import { createLogger } from '../study/logger.js'
import AssessmentForm from '../components/study/AssessmentForm.jsx'
import AthenaFullView from '../components/study/AthenaFullView.jsx'
import DashboardView from '../components/study/DashboardView.jsx'
import DiffFirstView from '../components/study/DiffFirstView.jsx'
import RecallForm from '../components/study/RecallForm.jsx'
import TlxForm from '../components/study/TlxForm.jsx'
import UsualCareView from '../components/study/UsualCareView.jsx'
import {
  AssessmentFlagsStep,
  DecisionTaskStep,
  EvidenceLookupForm,
  TrialMatchForm,
} from '../components/study/TaskForms.jsx'
import ChatInterface from './ChatInterface.jsx'

function newSessionId() {
  return `S${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

function RecallStep({ caseId, onSubmit }) {
  const recall = useAsync(() => getRecallOptions(caseId), [caseId])
  if (recall.loading) return <p className="muted">Loading…</p>
  if (recall.error) {
    return <p className="muted">Could not load the last question: {String(recall.error.message)}</p>
  }
  return <RecallForm options={recall.data.options} onSubmit={onSubmit} />
}

export default function StudyCase({
  participantId,
  item,
  position,
  total,
  unreviewed,
  onDone,
  enrolled = false,
}) {
  const view = useAsync(() => getStudyCase(item.case_id, item.arm), [item.case_id, item.arm])
  const firstPhase = 'review'
  const [phase, setPhase] = useState(firstPhase)
  const [assessmentSnapshot, setAssessmentSnapshot] = useState(null)
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

  useEffect(() => {
    if (view.data && !openedRef.current) {
      openedRef.current = true
      logger.log('case_opened', { position, total })
    }
  }, [view.data, logger, position, total])

  useEffect(() => {
    const timer = setInterval(() => logger.flush(), 2000)
    const onVisibility = () => logger.log(document.hidden ? 'page_hidden' : 'page_visible', {})
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

  useEffect(() => {
    if (item.arm !== 'chat' || chatRequestedRef.current) return
    chatRequestedRef.current = true
    studyChatApi
      .createSession({ case_id: item.case_id })
      .then((s) => setChatSessionId(s.id))
      .catch((error) => setChatError(error))
  }, [item.arm, item.case_id])

  const chatScreen = item.arm === 'chat' && phase === 'review'
  useEffect(() => {
    document.body.classList.toggle('chat-surface', chatScreen)
    return () => document.body.classList.remove('chat-surface')
  }, [chatScreen])

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
          Study logging is failing: {String(logError.message || logError)}. Events are kept and retried.
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
  const tasks = data.tasks
  const onFindingOpened = (findingId) => logger.log('finding_opened', { finding_id: findingId })
  const onCitationOpened = (findingId, url) =>
    logger.log('citation_opened', { source: 'card', finding_id: findingId, url })

  const afterReview = () => {
    if (enrolled && tasks) setPhase('t1')
    else if (enrolled) setPhase('t3')
    else setPhase('assess')
  }

  if (phase === 'review') {
    return (
      <div className="study-shell">
        {banner}
        <header className="study-bar">
          <span>
            Case {position} of {total}
          </span>
          <button type="button" className="study-button" onClick={afterReview}>
            Finish review →
          </button>
        </header>
        {item.arm === 'diff_first' || item.arm === 'athena_full' ? (
          <div className="wrap">
            {item.arm === 'athena_full' ? (
              <AthenaFullView
                view={data}
                caseId={item.case_id}
                phase={phase}
                onFindingOpened={onFindingOpened}
                onCitationOpened={onCitationOpened}
                onStudyEvent={logger.log}
              />
            ) : (
              <DiffFirstView
                view={data}
                onFindingOpened={onFindingOpened}
                onCitationOpened={onCitationOpened}
              />
            )}
          </div>
        ) : null}
        {item.arm === 'dashboard' || item.arm === 'usual_care' ? (
          <div className="wrap">
            {item.arm === 'usual_care' ? (
              <UsualCareView
                view={data}
                onFindingOpened={onFindingOpened}
                onCitationOpened={onCitationOpened}
                onEvent={logger.log}
              />
            ) : (
              <DashboardView
                view={data}
                onFindingOpened={onFindingOpened}
                onCitationOpened={onCitationOpened}
              />
            )}
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

  if (enrolled && phase === 't1' && tasks) {
    return (
      <div className="wrap">
        {banner}
        <EvidenceLookupForm
          question={tasks.evidence_lookup.question}
          onEvent={logger.log}
          onSubmit={() => setPhase('t2')}
        />
      </div>
    )
  }

  if (enrolled && phase === 't2' && tasks) {
    return (
      <div className="wrap">
        {banner}
        <TrialMatchForm
          question={tasks.trial_match.question}
          region={tasks.trial_match.region}
          maxAnswers={tasks.trial_match.max_answers}
          onEvent={logger.log}
          onSubmit={() => setPhase('t3')}
        />
      </div>
    )
  }

  if ((enrolled && phase === 't3') || (!enrolled && phase === 'assess')) {
    if (enrolled) {
      return (
        <div className="wrap">
          {banner}
          <AssessmentFlagsStep
            findings={data.findings}
            onEvent={logger.log}
            onSubmit={(snapshot) => {
              setAssessmentSnapshot(snapshot)
              setPhase('t4')
            }}
          />
        </div>
      )
    }
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

  if (enrolled && phase === 't4') {
    return (
      <div className="wrap">
        {banner}
        <DecisionTaskStep
          options={data.decision_options}
          prompt={data.decision_prompt}
          rationalePrompt={tasks?.decision_rationale?.prompt}
          onEvent={logger.log}
          onSubmit={({ decision, rationale }) => {
            logger.log('decision_submitted', {
              decision,
              rationale,
              flags: assessmentSnapshot?.flags,
              confidence: assessmentSnapshot?.confidence,
            })
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