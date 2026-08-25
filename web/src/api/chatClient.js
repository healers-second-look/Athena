/**
 * Chat API client -- connects to the FastAPI backend.
 *
 * Base URL defaults to localhost:8000 (the FastAPI dev server) but respects
 * VITE_CHAT_API_BASE for production.
 */

const BASE = import.meta.env?.VITE_CHAT_API_BASE || 'http://localhost:8000'

async function request(path, options = {}) {
  const url = `${BASE}${path}`
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${path} returned ${res.status}: ${text}`)
  }
  return res.json()
}

// Sessions
export const createSession = (body = {}) =>
  request('/api/chat/sessions', { method: 'POST', body: JSON.stringify(body) })

export const listSessions = () => request('/api/chat/sessions')

export const getSession = (id) => request(`/api/chat/sessions/${id}`)

export const updateSession = (id, body) =>
  request(`/api/chat/sessions/${id}`, { method: 'PATCH', body: JSON.stringify(body) })

export const deleteSession = (id) =>
  request(`/api/chat/sessions/${id}`, { method: 'DELETE' })

// Turns
export const sendTurn = (sessionId, message) =>
  request(`/api/chat/sessions/${sessionId}/turns`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  })

// Catalog
export const getModels = () => request('/api/chat/models')
export const getAttachments = () => request('/api/chat/attachments')
export const getContexts = () => request('/api/chat/contexts')

// Phase 5: FalkorDB Graph & Cypher
export const getContextGraph = (contextId) =>
  request(`/api/chat/contexts/${encodeURIComponent(contextId)}/graph`)
