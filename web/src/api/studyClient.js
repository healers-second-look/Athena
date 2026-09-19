/**
 * Study API client (issue #136) -- talks to the routes in
 * src/secondlook/api/routes/study.py, which exist only when the server runs
 * with ATHENA_STUDY_ENABLED=true.
 *
 * Same convention as chatClient.js: defaults to the FastAPI dev server, and
 * respects VITE_STUDY_API_BASE (falling back to VITE_CHAT_API_BASE) elsewhere.
 * No fixture fallback, deliberately: a study run against fake data would
 * produce data that looks real.
 */

const BASE =
  import.meta.env?.VITE_STUDY_API_BASE ||
  import.meta.env?.VITE_CHAT_API_BASE ||
  'http://localhost:8000'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    const error = new Error(`${path} returned ${res.status}: ${text}`)
    error.status = res.status
    throw error
  }
  return res.json()
}

export const getSchedule = (reviewerIndex) => request(`/api/study/schedule/${reviewerIndex}`)

export const getStudyCase = (caseId, arm) =>
  request(`/api/study/cases/${encodeURIComponent(caseId)}?arm=${encodeURIComponent(arm)}`)

export const getRecallOptions = (caseId) =>
  request(`/api/study/cases/${encodeURIComponent(caseId)}/recall`)

// `keepalive` lets the last batch survive the tab closing.
export const postEvents = (events) =>
  request('/api/study/events', {
    method: 'POST',
    body: JSON.stringify({ events }),
    keepalive: true,
  })

// Same method names ChatInterface already calls on chatClient.js, so the chat
// arm can render the real chat UI against the study routes.
export const studyChatApi = {
  createSession: (body) =>
    request('/api/study/chat/sessions', { method: 'POST', body: JSON.stringify(body) }),
  getSession: (id) => request(`/api/study/chat/sessions/${id}`),
  sendTurn: (id, message) =>
    request(`/api/study/chat/sessions/${id}/turns`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),
}
