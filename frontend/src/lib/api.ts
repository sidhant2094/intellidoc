import type { AnalyzeResponse, ApiError, AskResponse, Profile, StreamEvent } from './types'

/**
 * Backend origin. Empty in local development: requests go to /api and the Vite dev server proxies them to
 * http://127.0.0.1:8000. In production set VITE_API_BASE_URL to the backend URL (e.g. on Render).
 * Only this public URL is ever configured in the frontend — never API keys.
 */
export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '')

const url = (path: string) => `${API_BASE}${path}`

export class AnalysisFailure extends Error {
  error: ApiError
  constructor(error: ApiError) {
    super(error.message)
    this.error = error
  }
}

const OFFLINE: ApiError = {
  code: 'backend_offline',
  message: 'Can’t reach IntelliDoc.',
  hint: 'The server may be starting up or temporarily unavailable. Please try again in a moment.',
}

export interface Health {
  status: string
  max_file_mb: number
}

export async function checkHealth(signal?: AbortSignal): Promise<Health | null> {
  try {
    const res = await fetch(url('/api/health'), { signal, cache: 'no-store' })
    if (!res.ok) return null
    return (await res.json()) as Health
  } catch {
    return null
  }
}

/** POST the PDF and profile; invokes onEvent for each real backend stage; resolves with the result. */
export async function analyze(
  file: File,
  profile: Profile,
  onEvent: (e: StreamEvent) => void,
  signal: AbortSignal,
): Promise<AnalyzeResponse> {
  const form = new FormData()
  form.append('file', file, file.name)
  form.append('persona', profile.persona)
  form.append('expertise', profile.expertise)
  form.append('objective', profile.objective)
  form.append('focus_terms', profile.focusTerms.join(','))

  let res: Response
  try {
    res = await fetch(url('/api/analyze'), { method: 'POST', body: form, signal })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new AnalysisFailure(OFFLINE)
  }

  if (!res.ok) {
    let err: ApiError = OFFLINE
    try {
      const body = await res.json()
      err = body.error ?? { code: `http_${res.status}`, message: 'The analysis request was rejected.' }
    } catch {
      if (res.status >= 500) err = OFFLINE
    }
    throw new AnalysisFailure(err)
  }
  if (!res.body) throw new AnalysisFailure(OFFLINE)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: AnalyzeResponse | null = null

  const handle = (line: string) => {
    if (!line.trim()) return
    const event = JSON.parse(line) as StreamEvent
    if (event.type === 'error') throw new AnalysisFailure(event.error)
    if (event.type === 'result') result = event.data
    onEvent(event)
  }

  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let nl: number
      while ((nl = buffer.indexOf('\n')) >= 0) {
        handle(buffer.slice(0, nl))
        buffer = buffer.slice(nl + 1)
      }
    }
    handle(buffer)
  } catch (e) {
    if (e instanceof AnalysisFailure || (e as Error).name === 'AbortError') throw e
    throw new AnalysisFailure({
      code: 'stream_interrupted',
      message: 'The connection to IntelliDoc was interrupted.',
      hint: 'Check that the server is still running, then try again.',
    })
  }

  if (!result) {
    throw new AnalysisFailure({
      code: 'no_result',
      message: 'The analysis ended without a result.',
      hint: 'Try again. If it keeps happening, check the backend terminal for details.',
    })
  }
  return result
}

/** Ask a follow-up question about an analyzed document. */
export async function ask(sessionId: string, question: string, signal?: AbortSignal): Promise<AskResponse> {
  let res: Response
  try {
    res = await fetch(url(`/api/session/${encodeURIComponent(sessionId)}/ask`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new AnalysisFailure(OFFLINE)
  }
  if (!res.ok) {
    let err: ApiError = { code: `http_${res.status}`, message: 'That question couldn’t be answered.' }
    try {
      err = (await res.json()).error ?? err
    } catch {
      /* keep default */
    }
    throw new AnalysisFailure(err)
  }
  return (await res.json()) as AskResponse
}
