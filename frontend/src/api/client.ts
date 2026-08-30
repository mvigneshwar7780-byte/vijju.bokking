/**
 * The HTTP layer.
 *
 * Two things live here that are easy to get wrong and expensive to scatter:
 *
 *  - **Token refresh.** A 401 triggers exactly one refresh attempt, and
 *    concurrent 401s share it via a single in-flight promise. Without that,
 *    a page firing four requests at once would burn four refresh tokens and
 *    the server's rotation-replay detection would revoke the session.
 *  - **Error normalisation.** The API always returns
 *    `{error: {code, message, details}}`; every caller gets an `ApiError`
 *    instance with those fields, never a raw Axios error.
 */
import axios, { AxiosError, type AxiosInstance } from 'axios'
import type { ApiError, TokenPair } from './types'

const ACCESS_KEY = 'cineai.access'
const REFRESH_KEY = 'cineai.refresh'

export class ApiClientError extends Error {
  code: string
  status: number
  details: Record<string, unknown>
  requestId: string | null

  constructor(message: string, code: string, status: number, details = {}, requestId: string | null = null) {
    super(message)
    this.name = 'ApiClientError'
    this.code = code
    this.status = status
    this.details = details
    this.requestId = requestId
  }
}

export const tokenStore = {
  get access() { return localStorage.getItem(ACCESS_KEY) },
  get refresh() { return localStorage.getItem(REFRESH_KEY) },
  set(tokens: TokenPair) {
    localStorage.setItem(ACCESS_KEY, tokens.access_token)
    localStorage.setItem(REFRESH_KEY, tokens.refresh_token)
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

export const api: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
})

api.interceptors.request.use((config) => {
  const token = tokenStore.access
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

/** Shared across concurrent 401s so only one refresh is ever in flight. */
let refreshInFlight: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const refresh = tokenStore.refresh
  if (!refresh) return null
  try {
    const { data } = await axios.post<TokenPair>('/api/v1/auth/refresh', {
      refresh_token: refresh,
    })
    tokenStore.set(data)
    return data.access_token
  } catch {
    tokenStore.clear()
    return null
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiError>) => {
    const original = error.config as (typeof error.config & { _retried?: boolean }) | undefined

    if (error.response?.status === 401 && original && !original._retried && tokenStore.refresh) {
      original._retried = true
      refreshInFlight ??= refreshAccessToken().finally(() => { refreshInFlight = null })
      const token = await refreshInFlight
      if (token) {
        original.headers = original.headers ?? {}
        original.headers.Authorization = `Bearer ${token}`
        return api.request(original)
      }
    }

    const payload = error.response?.data
    let message = payload?.error?.message ?? error.message ?? 'Something went wrong.'

    // A bare "The request payload is invalid." tells the user nothing and sends
    // the developer to the server logs. The API already reports which field
    // failed and why -- surface it.
    const fieldErrors = payload?.error?.details?.errors
    if (Array.isArray(fieldErrors) && fieldErrors.length > 0) {
      message = fieldErrors
        .map((e: { field?: string; message?: string }) => {
          const field = (e.field ?? '').replace(/^body\./, '').replace(/_/g, ' ')
          return field ? `${field}: ${e.message}` : e.message
        })
        .join('; ')
    }

    throw new ApiClientError(
      message,
      payload?.error?.code ?? 'NETWORK_ERROR',
      error.response?.status ?? 0,
      payload?.error?.details ?? {},
      payload?.request_id ?? null,
    )
  },
)

/** A stable per-browser key so an anonymous visitor can reclaim their own hold
 *  after a refresh. Never used to authorise anything that costs money.
 *
 *  The key name must stay distinct from the zustand persist store's
 *  (`cineai.app`). They previously collided on `cineai.session`: zustand wrote
 *  its serialised state there, this function read it back, and every hold
 *  request went out with a 230-character JSON blob as its `session_key` — which
 *  the API rejected as "payload is invalid". The format guard below means even
 *  a stale or foreign value cannot produce that failure again; it is simply
 *  replaced.
 */
const GUEST_KEY = 'cineai.guest'
const GUEST_KEY_RE = /^[0-9a-f]{32}$/

export function sessionKey(): string {
  const stored = localStorage.getItem(GUEST_KEY)
  if (stored && GUEST_KEY_RE.test(stored)) return stored

  const value = crypto.randomUUID().replace(/-/g, '')
  localStorage.setItem(GUEST_KEY, value)
  return value
}

/** Idempotency keys for booking creation: one per checkout attempt. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}
