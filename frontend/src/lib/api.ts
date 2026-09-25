import type { HealthResponse, QueryResponse, TargetLanguage } from '../api/types'

/**
 * Single source of truth for backend base URL.
 * - Reads from `import.meta.env.VITE_API_BASE_URL` (set at build time via Vite)
 * - Falls back to `http://localhost:8000` for local dev if not set
 * - Trailing slash is stripped so callers can safely do `${API_BASE_URL}/query`
 */
export const API_BASE_URL: string =
  ((import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "")) ||
  "http://localhost:8000"

function url(path: string): string {
  return `${API_BASE_URL}${path}`
}

export async function checkHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const r = await fetch(url("/health"), { signal, cache: "no-store" })
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return (await r.json()) as HealthResponse
}

export async function askQuery(
  query: string,
  targetLanguage: TargetLanguage = "en",
  signal?: AbortSignal,
): Promise<{ data: QueryResponse; status: number; ms: number }> {
  const t0 = performance.now()
  const r = await fetch(url("/query"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
    const msg =
      (data as unknown as { detail?: unknown })?.detail != null
        ? JSON.stringify((data as unknown as { detail: unknown }).detail)
        : text
    throw Object.assign(new Error(msg.slice(0, 600)), { status: r.status, data })
  }
  return { data, status: r.status, ms: Math.round(t1 - t0) }
}

export async function speak(text: string, language: string = "en", signal?: AbortSignal): Promise<Blob> {
  const r = await fetch(url("/speak"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, language }),
    signal,
  })
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try {
      const ct = r.headers.get("content-type") || ""
      if (ct.includes("application/json")) {
        const j = (await r.json()) as { detail?: unknown }
        if (j?.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)
      } else {
        const t = await r.text()
        if (t.includes("<!DOCTYPE") || t.includes("<html")) {
          msg = `404 — /speak not proxied to backend. Restart Vite dev server after vite.config.ts change. (${r.status})`
        } else if (t) {
          msg = t.slice(0, 400)
        }
      }
    } catch {
      // fallback to status text
    }
    throw new Error(msg)
  }
  const ct = r.headers.get("content-type") || ""
  if (ct && !ct.includes("audio/") && !ct.includes("octet-stream")) {
    const t = await r.text()
    if (t) throw new Error(t.slice(0, 400))
  }
  return await r.blob()
}

export async function transcribe(
  file: Blob,
  language: TargetLanguage = "en",
  signal?: AbortSignal,
): Promise<{ text: string; language?: string }> {
  const fd = new FormData()
  fd.append("file", file, "audio.webm")
  fd.append("language", language)
  const r = await fetch(url("/transcribe"), { method: "POST", body: fd, signal })
  const ct = r.headers.get("content-type") || ""
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`
    try {
      if (ct.includes("application/json")) {
        const j = (await r.json()) as { detail?: unknown }
        if (j?.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)
      } else {
        const t = await r.text()
        if (t) msg = t.slice(0, 400)
      }
    } catch {}
    throw new Error(msg)
  }
  if (ct.includes("application/json")) {
    const j = (await r.json()) as { text?: string; language?: string }
    return { text: (j.text || "").trim(), language: j.language }
  }
  const t = await r.text()
  try {
    const j = JSON.parse(t) as { text?: string; language?: string }
    return { text: (j.text || "").trim(), language: j.language }
  } catch {
    return { text: t.trim() }
  }
}

export function getAudioCacheUrl(demoId: string, language: string): string {
  return url(`/audio_cache/${demoId}_${language}.mp3`)
}

export async function checkAudioCacheHead(demoId: string, language: string): Promise<boolean> {
  const cacheUrl = getAudioCacheUrl(demoId, language)
  try {
    const head = await fetch(cacheUrl, { method: "HEAD" })
    return head.ok
  } catch {
    return false
  }
}
