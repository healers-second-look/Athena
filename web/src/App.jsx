import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import CaseDashboard from './routes/CaseDashboard.jsx'
import ResearchQueue from './routes/ResearchQueue.jsx'
import FindingDetail from './routes/FindingDetail.jsx'
import PatientTimeline from './routes/PatientTimeline.jsx'
import StudyRunner from './routes/StudyRunner.jsx'
import EnrolledStudyRunner from './routes/EnrolledStudyRunner.jsx'
import StudyHome from './routes/StudyHome.jsx'
import Join from './routes/Join.jsx'
import Consent from './routes/Consent.jsx'
import Profile from './routes/Profile.jsx'
import ChatLanding from './routes/ChatLanding.jsx'
import ChatInterface from './routes/ChatInterface.jsx'
import { DEMO_CASE_ID, isFixtureBacked } from './api/client.js'
import { useEffect } from 'react'

export default function App() {
  const location = useLocation()
  const isChat = location.pathname.startsWith('/chat')
  const isStudy =
    location.pathname.startsWith('/study') || location.pathname.startsWith('/join')

  useEffect(() => {
    document.body.classList.toggle('chat-surface', isChat)
  }, [isChat])

  return (
    <div className={isChat || isStudy ? '' : 'wrap'}>
      {!isChat && !isStudy && isFixtureBacked() ? (
        <p className="nojs-note">
          Fixture-backed: Subsystem L (the REST API, issue #13) is not wired in.
          Set <code>VITE_API_BASE</code> to point these screens at a live API.
        </p>
      ) : null}
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/cases/:id" element={<CaseDashboard />} />
        <Route path="/cases/:id/queue" element={<ResearchQueue />} />
        <Route path="/cases/:id/timeline" element={<PatientTimeline />} />
        <Route path="/findings/:id" element={<FindingDetail />} />
        <Route path="/chat" element={<ChatLanding />} />
        <Route path="/chat/:id" element={<ChatInterface />} />
        <Route path="/join" element={<Join />} />
        <Route path="/join/consent" element={<Consent />} />
        <Route path="/join/profile" element={<Profile />} />
        <Route path="/study" element={<StudyHome />} />
        <Route path="/study/run" element={<EnrolledStudyRunner />} />
        <Route path="/study/:reviewerIndex" element={<StudyRunner />} />
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
        Client routes include <code>/join</code>, <code>/study</code>, <code>/cases/:id</code>,{' '}
        <code>/chat</code>, and <code>/study/:reviewerIndex</code>.
      </p>
    </>
  )
}