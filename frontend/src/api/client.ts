// Deprecated shim — use `frontend/src/lib/api.ts` as single source of truth.
// This file remains only for backward compat; all backend URL construction lives in lib/api.ts.
export { checkHealth as getHealth, askQuery as postQuery, speak as postSpeak, transcribe as postTranscribe, getAudioCacheUrl, checkAudioCacheHead, API_BASE_URL } from '../lib/api'
export type { HealthResponse, QueryResponse, TargetLanguage } from './types'
