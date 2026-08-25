/**
 * Chat API client -- connects to the FastAPI backend.
 *
 * Base URL resolution, in order:
 *
 *   1. VITE_CHAT_API_BASE -- only for the rare deployment that serves the
 *      chat API from a different origin than the rest of the REST API.
 *   2. VITE_API_BASE -- the one the deployment already sets. It is a build
 *      arg in web/Dockerfile, a build arg in docker-compose.yml, and is
 *      documented in .env.example.
 *   3. http://localhost:8000 -- the `uvicorn --reload` default, for
 *      `vite dev` where neither is set.
 *
 * Reading VITE_API_BASE matters because Vite INLINES these at build time.
 * This file previously read only VITE_CHAT_API_BASE, which is set nowhere
 * in the repo -- so every container built from docker-compose baked in the
 * localhost:8000 fallback and the chat UI reached for the user's own
 * machine no matter where the API actually was. It appeared to work for
 * exactly one person: whoever ran the API locally on the default port.
 */

const BASE =
  import.meta.env?.VITE_CHAT_API_BASE || import.meta.env?.VITE_API_BASE || 'http://localhost:8000'

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
