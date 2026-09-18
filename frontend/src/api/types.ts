export type QueryType = 'standard_lookup' | 'product_to_standard' | 'scheme_process' | 'lab_query'
export type TargetLanguage = 'en' | 'hi' | 'te' | 'ta'

export interface Citation {
  source_title: string
  source_url: string
  chunk_id?: string
}

export interface QueryRequest {
  query: string
  target_language?: TargetLanguage
}

export interface QueryResponse {
  answer: string
  translated_answer?: string | null
  target_language?: TargetLanguage
  citations: Citation[]
  query_type: QueryType
  used_live_fallback: boolean
}

export interface HealthResponse {
  status: string
}
