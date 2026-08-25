import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import CaseDashboard from './routes/CaseDashboard.jsx'
import ResearchQueue from './routes/ResearchQueue.jsx'
import FindingDetail from './routes/FindingDetail.jsx'
import ChatLanding from './routes/ChatLanding.jsx'
import ChatInterface from './routes/ChatInterface.jsx'
import { DEMO_CASE_ID, isFixtureBacked } from './api/client.js'
import { useEffect } from 'react'

export default function App() {
  const location = useLocation()
  const isChat = location.pathname.startsWith('/chat')

  // Toggle body class for chat-specific styles
  useEffect(() => {
    document.body.classList.toggle('chat-surface', isChat)
  }, [isChat])

  return (
    <div className={isChat ? '' : 'wrap'}>
      {!isChat && isFixtureBacked() ? (
        <p className="nojs-note">
          Fixture-backed: Subsystem L (the REST API, issue #13) is not wired in.
          Set <code>VITE_API_BASE</code> to point these screens at a live API.
        </p>
      ) : null}
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/cases/:id" element={<CaseDashboard />} />
        <Route path="/cases/:id/queue" element={<ResearchQueue />} />
        <Route path="/findings/:id" element={<FindingDetail />} />
        {/* Chat surface (issue #103) */}
        <Route path="/chat" element={<ChatLanding />} />
        <Route path="/chat/:id" element={<ChatInterface />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </div>
  )
}

function NotFound() {
  return (
    <>
      <h1>Not found</h1>
      <p className="muted">
        Client routes are <code>/cases/:id</code>, <code>/cases/:id/queue</code>,{' '}
        <code>/findings/:id</code>, and <code>/chat</code>.
      </p>
    </>
  )
}
