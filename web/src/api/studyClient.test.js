import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  STUDY_TOKEN_KEY,
  clearStudyToken,
  setStudyToken,
  setUnauthorizedHandler,
  postEvents,
} from './studyClient.js'

describe('studyClient auth', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    vi.stubGlobal('localStorage', {
      store: {},
      getItem(key) {
        return this.store[key] ?? null
      },
      setItem(key, value) {
        this.store[key] = String(value)
      },
      removeItem(key) {
        delete this.store[key]
      },
      clear() {
        this.store = {}
      },
    })
    localStorage.clear()
    setUnauthorizedHandler(() => {
      clearStudyToken()
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('adds Authorization header when token is set', async () => {
    setStudyToken('secret-token')
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    })

    await postEvents([])

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/study/events'),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer secret-token',
        }),
      }),
    )
  })

  it('clears token on 401', async () => {
    setStudyToken('secret-token')
    vi.mocked(fetch).mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => 'unauthorized',
    })

    await expect(postEvents([])).rejects.toThrow()
    expect(localStorage.getItem(STUDY_TOKEN_KEY)).toBeFalsy()
  })
})