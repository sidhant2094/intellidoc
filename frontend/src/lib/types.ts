// Mirrors backend/app/schemas.py

export type Expertise = 'Beginner' | 'Intermediate' | 'Advanced'
export type ContentType = 'prose' | 'table' | 'code' | 'figure'
export type StageName = 'reading' | 'sections' | 'matching' | 'ranking'

export interface DocumentInfo {
  filename: string
  title: string | null
  page_count: number
  pages_with_text: number
  scanned_pages: number[]
  blank_pages: number[]
  section_count: number
  chunk_count: number
  structure_source: 'outline' | 'headings' | 'pages'
}

export interface AnalysisInfo {
  persona: string
  expertise: Expertise
  objective: string
  focus_terms: string[]
  duration_ms: number
  method: string
  weights: Record<SignalName, number>
  content_type_active: boolean
  detected_intents: string[]
  candidates_considered: number
}

export type SignalName = 'semantic' | 'keyword' | 'content_type' | 'expertise' | 'structure' | 'contextual'

export interface Highlight {
  page: number
  rects: [number, number, number, number][]
}

export interface Result {
  id: string
  rank: number
  section_id: string
  title: string
  breadcrumb: string[]
  level: number
  page_start: number
  page_end: number
  match_score: number
  relevance_label: string
  why_relevant: string
  matched_terms: string[]
  summary: string
  findings: string[]
  takeaways: string[]
  limitations: string[]
  key_points: { text: string; page: number }[]
  excerpt: string
  excerpt_page: number
  highlights: Highlight[]
  content_types: ContentType[]
  context: string
  context_excerpt: { start: number; end: number }
  context_pages: { offset: number; page: number }[]
  signals: Record<SignalName, number>
}

export type InsightKind =
  | 'concentration'
  | 'recurring'
  | 'gap'
  | 'theme'
  | 'relationship'
  | 'contradiction'
  | 'repetition'
  | 'risk'

export interface Insight {
  kind: InsightKind
  title: string
  text: string
  pages: number[]
  result_ids: string[]
}

export interface AnalyzeResponse {
  session_id: string | null
  document: DocumentInfo
  analysis: AnalysisInfo
  results: Result[]
  insights: Insight[]
  warnings: { code: string; message: string }[]
}

export interface ApiError {
  code: string
  message: string
  hint?: string
}

export type StreamEvent =
  | { type: 'stage'; stage: StageName; detail: string }
  | { type: 'result'; data: AnalyzeResponse }
  | { type: 'error'; error: ApiError }

export interface Profile {
  persona: string
  expertise: Expertise
  objective: string
  focusTerms: string[]
}

export interface Citation {
  n: number
  section_id: string
  title: string
  breadcrumb: string[]
  page_start: number
  page_end: number
  excerpt: string
  excerpt_page: number
  result_id: string | null
}

export interface AskResponse {
  answer: string
  supported: boolean
  citations: Citation[]
}
