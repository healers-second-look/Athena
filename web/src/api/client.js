// The one place that knows where data comes from.
//
// Subsystem L (issue #13, the REST API) does not exist yet. Rather than block
// on it, every function here reads the committed fixtures under web/fixtures/
// — the same files secondlook/web/fixtures.py loads for the server-rendered
// views, so the two halves of Subsystem M cannot show different things.
//
// Switching to the real API is a base-URL swap and nothing else: set
// VITE_API_BASE and each function fetches its route instead. The routes below
// are IMPLEMENTATION_PLAN.md §5's verbatim, and the fixture shapes mirror
// their responses, so no call site changes.

import caseFixture from '../../fixtures/case.json'
import changesFixture from '../../fixtures/changes.json'
import queueFixture from '../../fixtures/queue.json'
import findingsFixture from '../../fixtures/findings.json'

const BASE = import.meta.env?.VITE_API_BASE || ''

export const isFixtureBacked = () => !BASE

async function get(route, fixture) {
  if (!BASE) return structuredClone(fixture)
  const response = await fetch(`${BASE}${route}`, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    // Surfaced, never swallowed. docs/api-contracts.md's failure rule: a
    // failure object is always rendered, never filtered out silently before
    // reaching the frontend.
    throw new Error(`${route} returned ${response.status}`)
  }
  return response.json()
}

export const getCase = (id) => get(`/api/cases/${id}`, caseFixture)
export const getChanges = (id) => get(`/api/cases/${id}/changes`, changesFixture)
export const getQueue = (id) => get(`/api/cases/${id}/queue`, queueFixture)

// No fixture fallback: the timeline bundle is ~1.6MB of real reference data
// (see src/secondlook/timeline/reference_data.py), not something to also
// duplicate as a small committed fixture. VITE_API_BASE must be set to use
// this route -- the error is the honest signal that it isn't, rather than a
// silent empty timeline.
export async function getTimeline(id) {
  if (!BASE) {
    throw new Error('Patient Timeline needs VITE_API_BASE set -- there is no offline fixture for it')
  }
  return get(`/api/cases/${id}/timeline`, null)
}

export async function getFinding(id) {
  if (!BASE) {
    const record = findingsFixture[id]
    if (!record) throw new Error(`No finding ${id} in the fixture set`)
    return structuredClone(record)
  }
  return get(`/api/findings/${id}`, null)
}

export async function getFindings(ids = []) {
  return Promise.all(ids.map(getFinding))
}

// The demo case id, so routes can redirect somewhere real without the user
// having to know a UUID.
export const DEMO_CASE_ID = caseFixture.id
