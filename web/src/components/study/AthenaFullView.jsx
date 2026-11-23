import { useEffect, useState } from 'react'
import DiffFirstView from './DiffFirstView.jsx'
import ChatInterface from '../../routes/ChatInterface.jsx'
import { studyChatApi } from '../../api/studyClient.js'

export default function AthenaFullView({
  view,
  caseId,
  onFindingOpened,
  onCitationOpened,
  onStudyEvent,
  phase,
}) {
  const [panel, setPanel] = useState('athena')
  const [chatSessionId, setChatSessionId] = useState(null)
  const [chatError, setChatError] = useState(null)

  useEffect(() => {
    if (phase !== 'review') return
    let cancelled = false
    studyChatApi
      .createSession({ case_id: caseId })
      .then((s) => {
        if (!cancelled) setChatSessionId(s.id)
      })
      .catch((error) => {
        if (!cancelled) setChatError(error)
      })
    return () => {
      cancelled = true
    }
  }, [caseId, phase])

  useEffect(() => {
    const chatActive = phase === 'review' && panel === 'chat'
    document.body.classList.toggle('chat-surface', chatActive)
    return () => document.body.classList.remove('chat-surface')
  }, [phase, panel])

  return (
    <div className="study-athena-full">
      <div className="study-athena-tabs" role="tablist" aria-label="Athena review panels">
        <button
          type="button"
          role="tab"
          aria-selected={panel === 'athena'}
          className={panel === 'athena' ? 'is-active' : undefined}
          onClick={() => setPanel('athena')}
        >
          Athena review
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={panel === 'chat'}
          className={panel === 'chat' ? 'is-active' : undefined}
          onClick={() => setPanel('chat')}
        >
          Study chat
        </button>
      </div>
      <div className="study-athena-panels">
        <div
          className={`study-athena-panel study-athena-panel--diff${panel === 'athena' ? ' is-visible' : ''}`}
          role="tabpanel"
          hidden={panel !== 'athena'}
        >
          <DiffFirstView view={view} onFindingOpened={onFindingOpened} onCitationOpened={onCitationOpened} />
        </div>
        <div
          className={`study-athena-panel study-athena-panel--chat${panel === 'chat' ? ' is-visible' : ''}`}
          role="tabpanel"
          hidden={panel !== 'chat'}
        >
          {chatError ? (
            <p className="muted">Could not open the chat: {String(chatError.message)}</p>
          ) : chatSessionId ? (
            <ChatInterface
              studySessionId={chatSessionId}
              studyClient={studyChatApi}
              onStudyEvent={onStudyEvent}
            />
          ) : (
            <p className="muted">Opening chat…</p>
          )}
        </div>
      </div>
    </div>
  )
}