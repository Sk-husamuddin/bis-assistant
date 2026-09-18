import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getHealth, postQuery, postSpeak, postTranscribe } from './api/client'
import type { QueryResponse, TargetLanguage } from './api/types'

type HealthState = 'checking' | 'ok' | 'offline'
type ResponseState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string; raw?: string }
  | { kind: 'success'; data: QueryResponse; status: number; ms: number; query: string }

const EXAMPLES: { label: string; query: string }[] = [
  { label: 'IS 2347', query: 'What is IS 2347 and which products does it cover?' },
  { label: 'IS 4151 helmets', query: 'What does IS 4151 specify for helmets?' },
  { label: 'Pressure cooker → standard', query: 'I manufacture stainless steel pressure cookers — which BIS standard and scheme applies?' },
  { label: 'LED bulbs CRS?', query: 'I want to sell LED bulbs in India — do I need CRS or ISI?' },
  { label: 'CRS process', query: 'What is the process for CRS (Scheme II) registration?' },
  { label: 'LRS lab', query: 'How does a lab get BIS recognition under LRS 2018?' },
]

const LANG_OPTIONS: { value: TargetLanguage; label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'हिन्दी' },
  { value: 'te', label: 'తెలుగు' },
  { value: 'ta', label: 'தமிழ்' },
]

function getDemoId(query: string): string | null {
  const idx = EXAMPLES.findIndex((e) => e.query === query)
  return idx >= 0 ? `demo_${idx}` : null
}

function useHealth() {
  const [state, setState] = useState<HealthState>('checking')
  const [detail, setDetail] = useState<string>('')
  const check = useCallback(async (signal?: AbortSignal) => {
    setState('checking')
    try {
      const j = await getHealth(signal)
      setState('ok')
      setDetail(j.status || 'ok')
    } catch (e) {
      setState('offline')
      setDetail(e instanceof Error ? e.message : 'error')
    }
  }, [])
  useEffect(() => {
    const ac = new AbortController()
    check(ac.signal)
    const id = setInterval(() => check(), 15000)
    return () => {
      ac.abort()
      clearInterval(id)
    }
  }, [check])
  return { state, detail, check }
}

function Skeleton() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading answer">
      <div className="h-4 w-3/4 animate-pulse rounded bg-[var(--hairline)]/40" />
      <div className="h-4 w-full animate-pulse rounded bg-[var(--hairline)]/40" />
      <div className="h-4 w-5/6 animate-pulse rounded bg-[var(--hairline)]/40" />
      <div className="h-24 w-full animate-pulse rounded-lg bg-[var(--hairline)]/30" />
    </div>
  )
}

function fmtAnswer(t: string) {
  const esc = t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  const withBold = esc.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  return withBold
}

export default function App() {
  const health = useHealth()
  const [query, setQuery] = useState('')
  const [lang, setLang] = useState<TargetLanguage>('en')
  const [voiceLang, setVoiceLang] = useState<TargetLanguage>('en')
  const [resp, setResp] = useState<ResponseState>({ kind: 'idle' })
  const [history, setHistory] = useState<{ q: string; type: string; ms: number; at: string }[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('bis_hist') || '[]')
    } catch {
      return []
    }
  })
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const [isRecording, setIsRecording] = useState(false)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [micError, setMicError] = useState<string | null>(null)
  const [recordingSecs, setRecordingSecs] = useState(30)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<BlobPart[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const timerRef = useRef<number | null>(null)

  const canSend = useMemo(() => query.trim().length >= 3, [query])
  const charCount = query.length

  const pushHistory = useCallback((q: string, type: string, ms: number) => {
    setHistory((h) => {
      const next = [{ q, type, ms, at: new Date().toLocaleTimeString() }, ...h].slice(0, 6)
      localStorage.setItem('bis_hist', JSON.stringify(next))
      return next
    })
  }, [])

  const getSupportedMimeType = () => {
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
    for (const c of candidates) {
      try {
        if ((window as unknown as { MediaRecorder?: { isTypeSupported?: (t: string) => boolean } }).MediaRecorder?.isTypeSupported?.(c)) return c
      } catch {}
    }
    return 'audio/webm'
  }

  const cleanupMic = useCallback(() => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
    try {
      streamRef.current?.getTracks().forEach((t) => t.stop())
    } catch {}
    streamRef.current = null
    mediaRecorderRef.current = null
    chunksRef.current = []
  }, [])

  const startRecording = async () => {
    setMicError(null)
    if (!navigator.mediaDevices?.getUserMedia) {
      setMicError('Microphone not supported in this browser — try Chrome or Edge on desktop.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      chunksRef.current = []
      const mimeType = getSupportedMimeType()
      const mr = new MediaRecorder(stream, { mimeType } as MediaRecorderOptions)
      mediaRecorderRef.current = mr
      mr.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data)
      }
      mr.onstop = async () => {
        if (timerRef.current) {
          window.clearInterval(timerRef.current)
          timerRef.current = null
        }
        const blob = new Blob(chunksRef.current, { type: mr.mimeType || mimeType })
        chunksRef.current = []
        try { stream.getTracks().forEach((t) => t.stop()) } catch {}
        streamRef.current = null
        if (blob.size === 0) {
          setMicError('No speech detected — try again, speak clearly near the mic.')
          setIsRecording(false)
          setIsTranscribing(false)
          return
        }
        setIsRecording(false)
        setIsTranscribing(true)
        setMicError(null)
        try {
          const { text } = await postTranscribe(blob, voiceLang)
          if (!text || text.trim().length === 0) {
            setMicError('No speech detected — try again, speak clearly.')
          } else {
            setQuery(text.trim())
            requestAnimationFrame(() => {
              textareaRef.current?.focus()
              const len = text.trim().length
              try { textareaRef.current?.setSelectionRange(len, len) } catch {}
            })
          }
        } catch (e: unknown) {
          const msg = e instanceof Error ? e.message : String(e)
          if (msg.toLowerCase().includes('no speech')) setMicError(msg)
          else setMicError(`Transcription failed: ${msg}`)
        } finally {
          setIsTranscribing(false)
        }
      }
      mr.start(100)
      setIsRecording(true)
      setRecordingSecs(30)
      timerRef.current = window.setInterval(() => {
        setRecordingSecs((s) => {
          if (s <= 1) {
            try { mr.state === 'recording' && mr.stop() } catch {}
            return 0
          }
          return s - 1
        })
      }, 1000)
      window.setTimeout(() => {
        try {
          if (mr.state === 'recording') mr.stop()
        } catch {}
      }, 30000)
    } catch (e: unknown) {
      const name = (e as DOMException)?.name
      if (name === 'NotAllowedError') setMicError('Microphone permission denied — allow mic in browser settings and try again.')
      else if (name === 'NotFoundError') setMicError('No microphone found — connect a mic and try again.')
      else setMicError(e instanceof Error ? e.message : 'Failed to access microphone')
    }
  }

  const stopRecording = () => {
    const mr = mediaRecorderRef.current
    if (!mr) return
    try {
      if (mr.state === 'recording') mr.stop()
    } catch {}
  }

  const doAsk = useCallback(
    async (overrideQuery?: string, overrideLang?: TargetLanguage) => {
      const q = (overrideQuery ?? query).trim()
      const targetLang = overrideLang ?? lang
      if (q.length < 3) {
        textareaRef.current?.focus()
        textareaRef.current?.setAttribute('aria-invalid', 'true')
        setTimeout(() => textareaRef.current?.removeAttribute('aria-invalid'), 1200)
        return
      }
      handleStopInternal()
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac
      setResp({ kind: 'loading' })
      try {
        const { data, status, ms } = await postQuery(q, targetLang, ac.signal)
        setResp({ kind: 'success', data, status, ms, query: q })
        pushHistory(q, data.query_type, ms)
      } catch (e) {
        if ((e as DOMException)?.name === 'AbortError') return
        const msg = e instanceof Error ? e.message : String(e)
        setResp({ kind: 'error', message: msg })
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [query, lang, pushHistory],
  )

  const handleLangChange = (newLang: TargetLanguage) => {
    setLang(newLang)
    handleStopInternal()
    if (resp.kind === 'success' && resp.query) {
      doAsk(resp.query, newLang)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      doAsk()
    }
  }

  const copy = async (text: string, btn: HTMLButtonElement) => {
    try {
      await navigator.clipboard.writeText(text)
      const prev = btn.textContent
      btn.textContent = 'Copied!'
      setTimeout(() => (btn.textContent = prev), 1200)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      ta.remove()
    }
  }

  const [isFetchingAudio, setIsFetchingAudio] = useState(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const blobUrlRef = useRef<string | null>(null)

  const handleStopInternal = useCallback(() => {
    try {
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current.currentTime = 0
      }
    } catch {}
    setIsPlaying(false)
    setIsFetchingAudio(false)
  }, [])

  const handleStop = useCallback(() => {
    handleStopInternal()
  }, [handleStopInternal])

  useEffect(() => {
    return () => {
      if (blobUrlRef.current) {
        try { URL.revokeObjectURL(blobUrlRef.current) } catch {}
      }
      try { audioRef.current?.pause() } catch {}
      cleanupMic()
    }
  }, [cleanupMic])

  const handleListen = async (text: string, language: TargetLanguage) => {
    if (!text?.trim()) return
    if (isFetchingAudio || isPlaying) {
      handleStopInternal()
      if (blobUrlRef.current) {
        try { URL.revokeObjectURL(blobUrlRef.current) } catch {}
        blobUrlRef.current = null
      }
    }
    const currentQuery = resp.kind === 'success' ? resp.query : query
    const demoId = getDemoId(currentQuery)
    if (demoId) {
      const cacheUrl = `/audio_cache/${demoId}_${language}.mp3`
      try {
        const head = await fetch(cacheUrl, { method: 'HEAD' })
        if (head.ok) {
          if (blobUrlRef.current) {
            try { URL.revokeObjectURL(blobUrlRef.current) } catch {}
            blobUrlRef.current = null
          }
          if (!audioRef.current) {
            audioRef.current = new Audio()
            audioRef.current.onended = () => setIsPlaying(false)
            audioRef.current.onerror = () => setIsPlaying(false)
          } else {
            audioRef.current.onended = () => setIsPlaying(false)
            audioRef.current.onerror = () => setIsPlaying(false)
          }
          audioRef.current.src = cacheUrl
          audioRef.current.currentTime = 0
          setIsPlaying(true)
          await audioRef.current.play().catch((err: unknown) => {
            const m = err instanceof Error ? err.message : String(err)
            throw new Error(m || 'Audio playback failed')
          })
          return
        }
      } catch {}
    }
    setIsFetchingAudio(true)
    try {
      const blob = await postSpeak(text, language)
      if (!blob || blob.size === 0) throw new Error('Empty audio response')
      const url = URL.createObjectURL(blob)
      if (blobUrlRef.current) {
        try { URL.revokeObjectURL(blobUrlRef.current) } catch {}
      }
      blobUrlRef.current = url
      if (!audioRef.current) {
        audioRef.current = new Audio()
      }
      audioRef.current.onended = () => setIsPlaying(false)
      audioRef.current.onerror = () => {
        setIsPlaying(false)
        setIsFetchingAudio(false)
      }
      audioRef.current.src = url
      audioRef.current.currentTime = 0
      setIsFetchingAudio(false)
      setIsPlaying(true)
      await audioRef.current.play().catch((err: unknown) => {
        const m = err instanceof Error ? err.message : String(err)
        throw new Error(m || 'Audio playback failed')
      })
    } catch (e: unknown) {
      setIsFetchingAudio(false)
      setIsPlaying(false)
      let msg = 'Unknown error'
      if (e instanceof Error && e.message) msg = e.message
      else if (typeof e === 'string' && e) msg = e
      else if (e && typeof e === 'object' && 'message' in e && typeof (e as { message: unknown }).message === 'string') {
        msg = (e as { message: string }).message
      }
      console.error('speak failed', msg)
      alert('Listen failed: ' + msg)
    }
  }

  const displayed = resp.kind === 'success' ? (resp.data.translated_answer ?? resp.data.answer) : ''
  const isGrounded = resp.kind === 'success' && !resp.data.used_live_fallback && resp.data.citations.length > 0 && !resp.data.answer.toLowerCase().includes("sorry, but")
  const isAbstained = resp.kind === 'success' && (resp.data.citations.length === 0 || resp.data.answer.toLowerCase().includes("sorry, but none of the authorized"))

  return (
    <div className="min-h-screen">
      {/* Letterhead */}
      <header className="sticky top-0 z-10 bg-[var(--paper)]">
        <div className="letterhead-rule" />
        <div className="mx-auto flex max-w-[1240px] flex-wrap items-center justify-between gap-4 px-5 py-5 md:px-8">
          <div>
            <div className="text-[11px] font-semibold tracking-[0.14em] text-[var(--slate)]">BUREAU OF INDIAN STANDARDS</div>
            <h1 className="font-serif text-[20px] font-bold leading-none tracking-tight text-[var(--ink)]">
              Intelligent Assistant <span className="align-baseline text-[11px] font-semibold tracking-[0.08em] text-[var(--slate)]">SIH26107</span>
            </h1>
            <div className="mt-1 font-serif text-[12px] italic text-[var(--slate)]">Registry of Standards, Schemes &amp; Hallmarking — Official Record</div>
          </div>
          <div className="flex items-center gap-3 text-xs" role="status" aria-live="polite" aria-label="Backend health">
            <span className={`h-2 w-2 rounded-full ${health.state === 'ok' ? 'bg-[var(--verified)]' : health.state === 'offline' ? 'bg-[var(--rust)]' : 'bg-[var(--brass)]'}`} aria-hidden />
            <span className={`font-medium ${health.state === 'ok' ? 'text-[var(--verified)]' : health.state === 'offline' ? 'text-[var(--rust)]' : 'text-[var(--slate)]'}`}>
              {health.state === 'checking' ? 'Checking…' : health.state === 'ok' ? `Online · ${health.detail}` : `Offline · ${health.detail.slice(0,60)}`}
            </span>
            <button onClick={() => health.check()} className="rounded border border-[var(--hairline)] bg-white px-2.5 py-1 text-xs font-medium text-[var(--slate)] hover:bg-[var(--paper)]" aria-label="Recheck health">Check</button>
          </div>
        </div>
        <div className="letterhead-subrule" />
      </header>

      <div className="mx-auto grid max-w-[1240px] grid-cols-1 gap-0 px-0 md:grid-cols-[300px_1fr] md:px-5 md:py-6 md:gap-6">
        {/* Left rail — Docket */}
        <aside className="order-2 md:order-1 border-t border-[var(--hairline)] bg-white md:rounded-lg md:border">
          <div className="border-b border-[var(--hairline)] px-4 py-3">
            <h2 className="font-serif text-[13px] font-semibold tracking-tight text-[var(--ink)]">Docket</h2>
            <p className="mt-1 text-[11px] leading-relaxed text-[var(--slate)]">Running log of submitted queries. Select an entry to repopulate the submission form.</p>
          </div>
          <div className="max-h-[340px] overflow-auto md:max-h-[62vh]">
            {EXAMPLES.length > 0 && (
              <div className="border-b border-dashed border-[var(--hairline)] bg-[var(--paper)]/50 px-4 py-3">
                <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--slate)]">Examples</div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {EXAMPLES.map(ex => (
                    <button key={ex.label} onClick={() => { setQuery(ex.query); textareaRef.current?.focus(); }} className="rounded border border-[var(--hairline)] bg-white px-2.5 py-1 text-xs font-medium text-[var(--slate)] hover:border-[var(--ink)] hover:text-[var(--ink)]">
                      {ex.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {history.length === 0 ? (
              <div className="px-4 py-10 text-center">
                <div className="mx-auto h-px w-12 bg-[var(--hairline)]" />
                <p className="mt-3 font-serif text-[13px] italic text-[var(--slate)]">No entries yet.</p>
                <p className="mt-1 text-[11px] text-[var(--slate)]">Submit a query to create the first record.</p>
              </div>
            ) : (
              <ol className="divide-y divide-dashed divide-[var(--hairline)]" role="list">
                {history.map((h, idx) => {
                  const num = String(history.length - idx).padStart(2, '0')
                  return (
                    <li key={idx} className={`docket-entry ${h.type === 'standard_lookup' ? 'grounded' : 'grounded'} py-3 pr-4 pl-4`}>
                      <button onClick={() => { setQuery(h.q); doAsk(h.q); window.scrollTo({top:0, behavior:'smooth'}) }} className="w-full text-left focus:outline-none">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="font-serif text-[11px] font-semibold text-[var(--ink)]">#{num}</span>
                          <span className="text-[11px] text-[var(--slate)]">{h.at} · {h.ms}ms</span>
                        </div>
                        <div className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-[var(--ink)]">{h.q}</div>
                        <div className="mt-1 text-[11px] text-[var(--slate)]">{h.type}</div>
                      </button>
                    </li>
                  )
                })}
              </ol>
            )}
          </div>
          {history.length > 0 && (
            <div className="border-t border-[var(--hairline)] px-4 py-3">
              <button onClick={() => { setHistory([]); localStorage.removeItem('bis_hist') }} className="text-xs text-[var(--slate)] underline decoration-[var(--hairline)] underline-offset-4 hover:text-[var(--ink)]">Clear docket</button>
            </div>
          )}
        </aside>

        {/* Main — Registry entry */}
        <main className="order-1 md:order-2 min-w-0">
          {/* Submission group — single control area */}
          <section className="card overflow-hidden" aria-labelledby="submission-heading">
            <div className="border-b border-[var(--hairline)] bg-[var(--paper)]/60 px-5 py-3">
              <h2 id="submission-heading" className="font-serif text-[13px] font-semibold tracking-tight text-[var(--ink)]">Submission</h2>
              <p className="mt-1 text-[11px] text-[var(--slate)]">Enter a query in plain language. Select language, optionally use voice, then submit.</p>
            </div>
            <div className="p-5">
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-xs font-medium text-[var(--ink)]">
                  Answer
                  <select value={lang} onChange={e => handleLangChange(e.target.value as TargetLanguage)} className="rounded border border-[var(--hairline)] bg-white px-2 py-1.5 text-xs font-medium text-[var(--ink)] focus:border-[var(--brass)] focus:ring-1 focus:ring-[var(--brass)]/30" aria-label="Select answer language">
                    {LANG_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label} ({o.value})</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-2 text-xs font-medium text-[var(--ink)]">
                  Voice
                  <select value={voiceLang} onChange={e => setVoiceLang(e.target.value as TargetLanguage)} className="rounded border border-[var(--hairline)] bg-white px-2 py-1.5 text-xs font-medium text-[var(--ink)] focus:border-[var(--brass)] focus:ring-1 focus:ring-[var(--brass)]/30" aria-label="Select voice input language" title="Select speaking language before pressing mic — Telugu/Hindi/Tamil/English via Groq Whisper">
                    {LANG_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label} ({o.value})</option>)}
                  </select>
                </label>
                <span className="text-[11px] text-[var(--slate)]">{charCount} chars {charCount < 3 ? '(minimum 3)' : '· ready'}</span>
                <span className="ml-auto hidden text-[11px] text-[var(--slate)] md:inline">Ctrl+Enter to submit</span>
              </div>

              <div className="relative mt-4">
                <textarea
                  id="q"
                  ref={textareaRef}
                  value={query}
                  onChange={e => { setQuery(e.target.value); if (micError) setMicError(null) }}
                  onKeyDown={onKeyDown}
                  rows={4}
                  placeholder="Describe a product or ask about an Indian Standard, scheme, or hallmark…"
                  className="w-full resize-y rounded border border-[var(--hairline)] bg-white px-3 py-3 pr-12 text-sm leading-relaxed text-[var(--ink)] placeholder:text-[var(--slate)]/70 focus:border-[var(--brass)] focus:outline-none focus:ring-1 focus:ring-[var(--brass)]/30"
                  aria-describedby="q-help"
                />
                <button
                  type="button"
                  onClick={() => (isRecording ? stopRecording() : startRecording())}
                  disabled={isTranscribing}
                  aria-label={isRecording ? `Stop recording (${recordingSecs}s left)` : isTranscribing ? `Start voice input in ${voiceLang}` : 'Start voice input'}
                  title={isRecording ? `Recording — ${recordingSecs}s left — click to stop` : isTranscribing ? `Transcribing ${voiceLang}…` : `Record voice input — speaks ${LANG_OPTIONS.find(o=>o.value===voiceLang)?.label} via Groq Whisper`}
                  className={`absolute right-2 top-2 inline-flex h-9 min-w-9 items-center justify-center rounded-full border px-2.5 text-xs font-semibold shadow-sm ${isRecording ? 'border-[var(--rust)] bg-[var(--rust)] text-white' : isTranscribing ? 'cursor-not-allowed border-[var(--hairline)] bg-[var(--paper)] text-[var(--slate)]' : 'border-[var(--hairline)] bg-white text-[var(--ink)] hover:bg-[var(--paper)]'} ${isRecording ? 'pulse-ring' : ''}`}
                  style={isRecording ? { position: 'absolute' } : undefined}
                >
                  {isRecording ? `⏹ ${recordingSecs}s` : isTranscribing ? `Transcribing ${voiceLang}…` : '🎤'}
                </button>
                {isRecording && (
                  <div className="pointer-events-none absolute bottom-2 left-3 right-14 h-1 overflow-hidden rounded-full bg-[var(--hairline)]/50">
                    <div className="h-full bg-[var(--brass)]" style={{ width: `${((30 - recordingSecs) / 30) * 100}%` }} aria-hidden />
                  </div>
                )}
              </div>
              {micError && <p role="alert" className="mt-2 rounded border border-[var(--rust)]/20 bg-[#F9E8E2] px-3 py-2 text-xs text-[var(--rust)]">{micError}</p>}
              <p id="q-help" className="mt-2 text-[11px] text-[var(--slate)]">Voice selector sets Groq Whisper language (te/hi/ta/en) — select before recording. Answer language change re-queries last submission.</p>

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <button onClick={() => doAsk()} disabled={!canSend || resp.kind === 'loading'} className="rounded bg-[var(--ink)] px-4 py-2 text-sm font-semibold text-white hover:bg-black disabled:opacity-50">
                  Submit
                </button>
                <button onClick={() => { setQuery(''); textareaRef.current?.focus() }} className="rounded border border-[var(--hairline)] bg-white px-3 py-2 text-sm font-medium text-[var(--ink)] hover:bg-[var(--paper)]">
                  Clear
                </button>
                {resp.kind === 'success' && <span className="text-[11px] text-[var(--slate)]">{resp.ms} ms · {resp.data.target_language ?? 'en'}</span>}
              </div>
            </div>
          </section>

          {/* Registry Entry */}
          <section className="card mt-5 overflow-hidden p-0" aria-labelledby="registry-heading" aria-busy={resp.kind === 'loading'}>
            <div className="border-b border-[var(--hairline)] bg-[var(--paper)]/60 px-5 py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 id="registry-heading" className="font-serif text-[13px] font-semibold tracking-tight text-[var(--ink)]">Registry Entry</h2>
                {resp.kind === 'success' && (
                  <span className={`stamp ${isAbstained ? 'stamp-abstained' : isGrounded ? 'stamp-verified' : 'stamp-fallback'}`}>
                    {isAbstained ? 'ABSTAINED' : isGrounded ? 'VERIFIED' : 'UNVERIFIED'}
                  </span>
                )}
                {resp.kind === 'idle' && <span className="stamp stamp-fallback">IDLE</span>}
                {resp.kind === 'loading' && <span className="stamp stamp-fallback">RETRIEVING</span>}
                {resp.kind === 'error' && <span className="stamp stamp-abstained">ERROR</span>}
              </div>
              {resp.kind === 'success' && (
                <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-[var(--slate)]">
                  <span>type <b className="font-medium text-[var(--ink)]">{resp.data.query_type}</b></span>
                  <span>·</span>
                  <span>source <b className="font-medium text-[var(--ink)]">{resp.data.used_live_fallback ? 'live' : 'registry'}</b></span>
                  <span>·</span>
                  <span>{resp.ms} ms</span>
                  <span>·</span>
                  <span>lang <b className="font-medium text-[var(--ink)]">{resp.data.target_language ?? lang}</b></span>
                </div>
              )}
            </div>

            <div className="px-5 py-5">
              {resp.kind === 'idle' && (
                <div className="py-10 text-center">
                  <div className="mx-auto h-px w-16 bg-[var(--hairline)]" />
                  <p className="font-serif mt-4 text-sm italic text-[var(--slate)]">No entry selected.</p>
                  <p className="mx-auto mt-1 max-w-[30ch] text-xs leading-relaxed text-[var(--slate)]">Submit a query to generate a registry entry. The response is rendered as a structured record, not a chat bubble.</p>
                </div>
              )}
              {resp.kind === 'loading' && <Skeleton />}
              {resp.kind === 'error' && <div role="alert" className="rounded border border-[var(--rust)]/20 bg-[#F9E8E2] p-3 text-sm text-[var(--rust)]"><span className="font-semibold">Error:</span> {resp.message}</div>}
              {resp.kind === 'success' && (
                <>
                  <div className="prose prose-sm max-w-none text-sm leading-relaxed text-[var(--ink)]">
                    <div className="whitespace-pre-wrap" dangerouslySetInnerHTML={{ __html: fmtAnswer(displayed || '(no answer)') }} />
                  </div>

                  <div className="mt-6">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--slate)]">Schedule — Sources</div>
                    {resp.data.citations.length === 0 ? (
                      <p className="mt-2 text-xs italic text-[var(--slate)]">No sources cited — answer is ungrounded.</p>
                    ) : (
                      <ol className="mt-2 space-y-0 divide-y divide-dashed divide-[var(--hairline)] border-y border-[var(--hairline)]">
                        {resp.data.citations.map((c, i) => (
                          <li key={i} className="schedule-item py-3">
                            <div className="flex items-baseline gap-2">
                              <span className="schedule-num">{i + 1}.</span>
                              <span className="font-serif text-[13px] font-semibold leading-tight text-[var(--ink)]">{c.source_title || 'Untitled'}</span>
                            </div>
                            <a href={c.source_url} target="_blank" rel="noopener noreferrer" className="mt-1 block break-all font-serif text-xs italic text-[var(--slate)] underline decoration-[var(--hairline)] underline-offset-4 hover:text-[var(--ink)] hover:decoration-[var(--brass)]">
                              {c.source_url}
                            </a>
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    {isPlaying ? (
                      <button onClick={handleStop} aria-label="Stop audio" className="rounded bg-[var(--ink)] px-4 py-2 text-xs font-semibold text-white hover:bg-black">
                        ⏹ Stop
                      </button>
                    ) : (
                      <button onClick={() => handleListen(displayed, lang)} disabled={isFetchingAudio || !displayed} aria-label="Listen to answer" className="rounded bg-[var(--brass)] px-4 py-2 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50">
                        {isFetchingAudio ? 'Loading audio…' : 'Listen'}
                      </button>
                    )}
                    <button onClick={e => copy(displayed, e.currentTarget)} className="rounded border border-[var(--hairline)] bg-white px-3 py-2 text-xs font-medium text-[var(--ink)] hover:bg-[var(--paper)]">Copy</button>
                    <button onClick={e => copy(JSON.stringify(resp.data, null, 2), e.currentTarget)} className="rounded border border-[var(--hairline)] bg-white px-3 py-2 text-xs font-medium text-[var(--ink)] hover:bg-[var(--paper)]">JSON</button>
                  </div>
                </>
              )}
            </div>
          </section>

          <div className="mt-4 text-center text-[11px] text-[var(--slate)]">
            Registry served from <span className="font-mono text-[11px]">/health</span> and <span className="font-mono text-[11px]">/query</span> — Vite dev proxies to <span className="font-mono text-[11px]">:8000</span>.
          </div>
        </main>
      </div>
    </div>
  )
}
