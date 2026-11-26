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

export const STUDY_TOKEN_KEY = 'athena.study.token'

export function getStudyToken() {
  try {
    return window.localStorage.getItem(STUDY_TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setStudyToken(token) {
  try {
    if (token) window.localStorage.setItem(STUDY_TOKEN_KEY, token)
    else window.localStorage.removeItem(STUDY_TOKEN_KEY)
  } catch {
    /* storage blocked */
  }
}

export function clearStudyToken() {
  setStudyToken('')
}

let onUnauthorized = () => {
  clearStudyToken()
  if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/join')) {
    window.location.assign('/join')
  }
}

/** @internal — test hook */
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...options.headers }
  const token = getStudyToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const res = await fetch(`${BASE}${path}`, {
    headers,
    ...options,
  })
  if (res.status === 401 && token) {
    onUnauthorized()
  }
  if (!res.ok) {
    const text = await res.text()
    const error = new Error(`${path} returned ${res.status}: ${text}`)
    error.status = res.status
    error.body = text
    throw error
  }
  if (res.status === 204) return null
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

export const enrollCode = (code) =>
  request('/api/study/enroll/code', { method: 'POST', body: JSON.stringify({ code }) })

export const enrollConsent = (body) =>
  request('/api/study/enroll/consent', { method: 'POST', body: JSON.stringify(body) })

export const enrollProfile = (body) =>
  request('/api/study/enroll/profile', { method: 'POST', body: JSON.stringify(body) })

export const enrollResume = (body) =>
  request('/api/study/enroll/resume', { method: 'POST', body: JSON.stringify({ code, ...body }) })

export const getMe = () => request('/api/study/me')

export const withdraw = () => request('/api/study/withdraw', { method: 'POST' })

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