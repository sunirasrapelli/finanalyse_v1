'use client'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem('finanalyse_token')
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export interface JobMetrics {
  years: number[]
  revenue: (number | null)[]
  gross_margin_pct: (number | null)[]
  fcf: (number | null)[]
  debt_equity: (number | null)[]
}

export interface JobStatus {
  id?: string
  job_id?: string
  status: 'queued' | 'running' | 'done' | 'error'
  company_name?: string
  ticker?: string
  currency?: string
  unit?: string
  fiscal_years?: string[]
  error?: string
  error_message?: string
  created_at?: string
  completed_at?: string
  finished_at?: string
  progress?: Array<{ step: string; message: string; done: boolean; timestamp?: string }>
  log?: Array<{ step: string; message: string; done: boolean; timestamp?: string }>
  next_steps?: Array<{ priority: string; title: string; description: string }>
  metrics?: JobMetrics | null
}

export interface HistoryEntry {
  job_id: string
  status: string
  company_name?: string
  ticker?: string
  currency?: string
  unit?: string
  fiscal_years?: string[]
  created_at?: string
  completed_at?: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatResponse {
  reply: string
}

/**
 * Start a new analysis job by uploading PDF(s) and config.
 */
export async function startAnalysis(formData: FormData): Promise<{ job_id: string }> {
  const res = await fetch(`${API_URL}/analyze`, {
    method: 'POST',
    headers: {
      ...authHeaders(),
    },
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Failed to start analysis')
  }
  return res.json()
}

/**
 * Poll the status of a running job.
 */
export async function pollStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_URL}/status/${jobId}`, {
    headers: {
      ...authHeaders(),
    },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Failed to fetch status')
  }
  return res.json()
}

/**
 * Fetch list of all past analyses from SQLite history.
 */
export async function getHistory(): Promise<HistoryEntry[]> {
  const res = await fetch(`${API_URL}/history`, {
    headers: {
      ...authHeaders(),
    },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Failed to fetch history')
  }
  return res.json()
}

/**
 * Delete a job and its associated files.
 */
export async function deleteJob(jobId: string): Promise<void> {
  const res = await fetch(`${API_URL}/history/${jobId}`, {
    method: 'DELETE',
    headers: {
      ...authHeaders(),
    },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Failed to delete job')
  }
}

/**
 * Fetch full detail for a completed job from SQLite history.
 * More reliable than pollStatus for already-completed jobs (always reads from DB).
 */
export async function getJobDetail(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_URL}/history/${jobId}`, {
    headers: { ...authHeaders() },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Job not found')
  }
  const d = await res.json()
  // Map history detail shape -> JobStatus shape
  return {
    id:           d.id,
    status:       d.status,
    company_name: d.company_name || '',
    currency:     d.currency || '',
    unit:         d.unit || '',
    fiscal_years: d.fiscal_years || [],
    error:        d.error || '',
    next_steps:   d.next_steps || [],
    created_at:   d.created_at,
    finished_at:  d.finished_at,
    progress:     [],
    metrics:      d.metrics || null,
  }
}

/**
 * Send a chat message grounded in a single-company analysis.
 */
export async function sendChat(
  jobId: string,
  message: string,
  history: ChatMessage[]
): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/chat/${jobId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body: JSON.stringify({ message, history }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Failed to send message')
  }
  return res.json()
}

/**
 * Get the direct download URL for a completed job's report or Excel model.
 */
export function getDownloadUrl(jobId: string, type: 'report' | 'excel'): string {
  return `${API_URL}/download/${jobId}/${type}`
}

/**
 * Get the Google OAuth redirect URL.
 */
export function getGoogleAuthUrl(): string {
  return `${API_URL}/auth/google`
}

export interface AutoDetectResult {
  company_name: string
  fiscal_years: number[]
}

/**
 * Send a single PDF/JSON file to the backend and get back
 * detected company name and fiscal years (first 5 pages only).
 */
export async function autoDetect(file: File): Promise<AutoDetectResult> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`${API_URL}/auto-detect`, {
    method: 'POST',
    headers: { ...authHeaders() },
    body: fd,
  })
  if (!res.ok) {
    return { company_name: '', fiscal_years: [] }
  }
  return res.json()
}
