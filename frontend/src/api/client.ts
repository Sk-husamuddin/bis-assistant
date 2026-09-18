import type { HealthResponse, QueryResponse, TargetLanguage } from './types'

const BASE = '' // same-origin via Vite proxy or FastAPI mount

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const r = await fetch(`${BASE}/health`, { signal, cache: 'no-store' })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return (await r.json()) as HealthResponse
}

export async function postSpeak(text: string, language: string = 'en', signal?: AbortSignal): Promise<Blob> {
  const r = await fetch(`${BASE}/speak`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, language }),
    signal,
  })
  if (!r.ok) {
    // Try to surface a clear error regardless of body shape (Vite 404 HTML vs FastAPI JSON)
    let msg = `${r.status} ${r.statusText}`
    try {
      const ct = r.headers.get('content-type') || ''
      if (ct.includes('application/json')) {
        const j = (await r.json()) as { detail?: unknown }
        if (j?.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
      } else {
        const t = await r.text()
        // Avoid dumping full HTML for Vite 404; give concise hint
        if (t.includes('<!DOCTYPE') || t.includes('<html')) {
          msg = `404 — /speak not proxied to backend. Restart Vite dev server after vite.config.ts change. (${r.status})`
        } else if (t) {
          msg = t.slice(0, 400)
        }
      }
    } catch {
      // fallback to status text already set
    }
    throw new Error(msg)
  }
  // Also verify we actually got audio, not an HTML error page with 200 (shouldn't happen)
  const ct = r.headers.get('content-type') || ''
  if (ct && !ct.includes('audio/') && !ct.includes('octet-stream')) {
    // If backend returned JSON error with 200, treat as error
    const t = await r.text()
    if (t) throw new Error(t.slice(0, 400))
  }
  return await r.blob()
}

export async function postTranscribe(file: Blob, language: TargetLanguage = 'en', signal?: AbortSignal): Promise<{ text: string; language?: string }> {
  const fd = new FormData()
  fd.append('file', file, 'audio.webm')
  fd.append('language', language)
  const r = await fetch(`${BASE}/transcribe`, { method: 'POST', body: fd, signal })
  const ct = r.headers.get('content-type') || ''
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try {
      if (ct.includes('application/json')) {
        const j = (await r.json()) as { detail?: unknown }
        if (j?.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
      } else {
        const t = await r.text()
        if (t) msg = t.slice(0, 400)
      }
    } catch {}
    throw new Error(msg)
  }
  // success: {text: "...", language: "te"}
  if (ct.includes('application/json')) {
    const j = (await r.json()) as { text?: string; language?: string }
    return { text: (j.text || '').trim(), language: j.language }
  }
  // fallback: text body
  const t = await r.text()
  try {
    const j = JSON.parse(t) as { text?: string; language?: string }
    return { text: (j.text || '').trim(), language: j.language }
  } catch {
    return { text: t.trim() }
  }
}

export async function postQuery(query: string, targetLanguage: TargetLanguage = 'en', signal?: AbortSignal): Promise<{ data: QueryResponse; status: number; ms: number }> {
  const t0 = performance.now()
  const r = await fetch(`${BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, target_language: targetLanguage }),
    signal,
  })
  const t1 = performance.now()
  const text = await r.text()
  let data: QueryResponse
  try {
    data = JSON.parse(text) as QueryResponse
  } catch {
    throw new Error(text.slice(0, 600))
  }
  if (!r.ok) {
    const msg = (data as unknown as { detail?: unknown })?.detail ? JSON.stringify((data as unknown as { detail: unknown }).detail) : text
    throw Object.assign(new Error(msg.slice(0, 600)), { status: r.status, data })
  }
  return { data, status: r.status, ms: Math.round(t1 - t0) }
}
