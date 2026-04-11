'use client'

import {
  useState,
  useCallback,
  useEffect,
  useRef,
  Suspense,
} from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import Image from 'next/image'
import {
  Upload,
  FileText,
  FileSpreadsheet,
  Download,
  X,
  Info,
  Check,
  AlertTriangle,
  Loader2,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Activity,
  MessageSquare,
  Send,
  DollarSign,
  PieChart,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import {
  startAnalysis,
  pollStatus,
  getDownloadUrl,
  sendChat,
  autoDetect,
  getJobDetail,
  type JobStatus,
  type JobMetrics,
  type ChatMessage,
} from '@/lib/api'
import { getGoogleAuthUrl } from '@/lib/api'
import { handleAuthCallback, getToken, decodeTokenPayload, removeToken } from '@/lib/auth'

// =====================================================
// Sparkline
// =====================================================
const Sparkline = ({
  data,
  color = 'var(--accent-green)',
  height = 40,
}: {
  data: number[]
  color?: string
  height?: number
}) => {
  const max = Math.max(...data)
  const min = Math.min(...data)
  const range = max - min || 1
  const points = data
    .map((val, i) => {
      const x = (i / (data.length - 1)) * 100
      const y = height - ((val - min) / range) * (height - 4) - 2
      return `${x},${y}`
    })
    .join(' ')
  const gradId = `spark-${color.replace(/[^a-z0-9]/gi, '')}-${height}`
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ width: '100%', height }}>
      <defs>
        <linearGradient id={gradId} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline points={`0,${height} ${points} 100,${height}`} fill={`url(#${gradId})`} />
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

// =====================================================
// Animated Counter
// =====================================================
const AnimatedCounter = ({
  value,
  suffix = '',
  prefix = '',
  decimals = 0,
}: {
  value: number
  suffix?: string
  prefix?: string
  decimals?: number
}) => {
  const [count, setCount] = useState(0)
  const ref = useRef<HTMLSpanElement>(null)
  const started = useRef(false)

  useEffect(() => {
    started.current = false
    setCount(0)
  }, [value])

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !started.current) {
          started.current = true
          const duration = 1200
          const end = value
          const steps = duration / 16
          const increment = end / steps
          let current = 0
          const timer = setInterval(() => {
            current += increment
            if (current >= end) {
              setCount(end)
              clearInterval(timer)
            } else {
              setCount(current)
            }
          }, 16)
        }
      },
      { threshold: 0.3 }
    )
    if (ref.current) observer.observe(ref.current)
    return () => observer.disconnect()
  }, [value])

  return (
    <span ref={ref}>
      {prefix}{count.toFixed(decimals)}{suffix}
    </span>
  )
}

// =====================================================
// File Upload
// =====================================================
interface FileItem {
  file: File
}

const FileUpload = ({
  files,
  setFiles,
}: {
  files: FileItem[]
  setFiles: React.Dispatch<React.SetStateAction<FileItem[]>>
}) => {
  const [isDragging, setIsDragging] = useState(false)

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      const dropped = Array.from(e.dataTransfer.files)
      const valid = dropped.filter(
        (f) => f.type === 'application/pdf' || f.type === 'application/json'
      )
      setFiles((prev) => [...prev, ...valid.map((f) => ({ file: f }))])
    },
    [setFiles]
  )

  const handleSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || [])
    setFiles((prev) => [...prev, ...selected.map((f) => ({ file: f }))])
    e.target.value = ''
  }

  const remove = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx))
  }

  const fmt = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  return (
    <div className="upload-section">
      <h3 className="section-label">UPLOAD FILES</h3>

      <div
        className={`upload-dropzone ${isDragging ? 'dragging' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => document.getElementById('file-input-analyse')?.click()}
      >
        <input
          id="file-input-analyse"
          type="file"
          multiple
          accept=".pdf,.json"
          onChange={handleSelect}
          style={{ display: 'none' }}
        />
        <div className="upload-icon-wrapper">
          <Upload className="upload-icon" />
          <div className="upload-pulse" />
        </div>
        <p className="upload-text">Click to upload or drag &amp; drop</p>
        <p className="upload-hint">PDF - JSON - Up to 50 MB per file</p>
      </div>

      {files.length > 0 && (
        <div className="file-list">
          {files.map((item, idx) => (
            <div key={idx} className="file-item" style={{ animationDelay: `${idx * 0.1}s` }}>
              <div className="file-icon pdf">
                <FileText size={18} />
              </div>
              <div className="file-info">
                <span className="file-name">{item.file.name}</span>
                <span className="file-size">{fmt(item.file.size)}</span>
              </div>
              <button className="file-remove" onClick={() => remove(idx)}>
                <X size={16} />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="upload-tip">
        <Info size={14} />
        <span>Upload 3+ fiscal years for full trend analysis and AI insights.</span>
      </div>
    </div>
  )
}

// =====================================================
// Config Panel
// =====================================================
interface Config {
  companyName: string
  fiscalYears: string
  currency: string
  units: string
  ticker: string
}

const ConfigPanel = ({
  config,
  setConfig,
  onRun,
  isRunning,
  isDetecting,
  hasFiles,
}: {
  config: Config
  setConfig: React.Dispatch<React.SetStateAction<Config>>
  onRun: () => void
  isRunning: boolean
  isDetecting: boolean
  hasFiles: boolean
}) => (
  <div className="config-section">
    <h3 className="section-label">
      CONFIGURATION
      {isDetecting && (
        <span style={{ marginLeft: '0.5rem', fontSize: '0.7rem', color: 'var(--accent-blue)', fontWeight: 400, letterSpacing: 0 }}>
          <Loader2 size={11} className="spin" style={{ display: 'inline', marginRight: '0.25rem', verticalAlign: 'middle' }} />
          AI detecting...
        </span>
      )}
    </h3>

    <div className="config-field">
      <label>COMPANY NAME</label>
      <div style={{ position: 'relative' }}>
        <input
          type="text"
          value={config.companyName}
          onChange={(e) => setConfig((p) => ({ ...p, companyName: e.target.value }))}
          placeholder={isDetecting ? 'AI detecting...' : 'Enter company name...'}
          className="config-input"
          style={isDetecting && !config.companyName ? { opacity: 0.5 } : undefined}
        />
        {isDetecting && !config.companyName && (
          <Loader2 size={14} className="spin" style={{ position: 'absolute', right: '0.75rem', top: 'calc(50% - 7px)', color: 'var(--accent-blue)', pointerEvents: 'none' }} />
        )}
      </div>
    </div>

    <div className="config-field">
      <label>
        TICKER (optional)
        <span className="label-hint">for beta/VaR</span>
      </label>
      <input
        type="text"
        value={config.ticker}
        onChange={(e) => setConfig((p) => ({ ...p, ticker: e.target.value }))}
        placeholder="e.g. CL, INFY"
        className="config-input"
      />
    </div>

    <div className="config-field">
      <label>
        FISCAL YEARS
        <span className="label-hint">{config.fiscalYears || '2022,2023,2024'}</span>
      </label>
      <div style={{ position: 'relative' }}>
        <input
          type="text"
          value={config.fiscalYears}
          onChange={(e) => setConfig((p) => ({ ...p, fiscalYears: e.target.value }))}
          placeholder={isDetecting ? 'AI detecting...' : '2022,2023,2024'}
          className="config-input"
          style={isDetecting && !config.fiscalYears ? { opacity: 0.5 } : undefined}
        />
        {isDetecting && !config.fiscalYears && (
          <Loader2 size={14} className="spin" style={{ position: 'absolute', right: '0.75rem', top: 'calc(50% - 7px)', color: 'var(--accent-blue)', pointerEvents: 'none' }} />
        )}
      </div>
    </div>

    <div className="config-row">
      <div className="config-field half">
        <label>CURRENCY</label>
        <select
          value={config.currency}
          onChange={(e) => setConfig((p) => ({ ...p, currency: e.target.value }))}
          className="config-select"
        >
          <option value="USD">USD - Dollar</option>
          <option value="INR">INR - Rupee</option>
          <option value="EUR">EUR - Euro</option>
          <option value="GBP">GBP - Pound</option>
        </select>
      </div>
      <div className="config-field half">
        <label>UNITS</label>
        <select
          value={config.units}
          onChange={(e) => setConfig((p) => ({ ...p, units: e.target.value }))}
          className="config-select"
        >
          <option value="Millions">Millions</option>
          <option value="Crores">Crores</option>
          <option value="Billions">Billions</option>
        </select>
      </div>
    </div>

    <button
      className="run-analysis-btn"
      onClick={onRun}
      disabled={isRunning || isDetecting || !hasFiles}
    >
      {isRunning ? (
        <>
          <Loader2 size={18} className="spin" />
          <span>Analysing...</span>
        </>
      ) : (
        <>
          <Activity size={18} />
          <span>Run Analysis</span>
          <div className="btn-shine" />
        </>
      )}
    </button>
  </div>
)

// =====================================================
// Priority Badge
// =====================================================
const PriorityBadge = ({ priority }: { priority: string }) => {
  const styles: Record<string, React.CSSProperties> = {
    HIGH: { color: '#ef4444', backgroundColor: 'rgba(239,68,68,0.15)', borderColor: 'rgba(239,68,68,0.3)' },
    MEDIUM: { color: '#f97316', backgroundColor: 'rgba(249,115,22,0.15)', borderColor: 'rgba(249,115,22,0.3)' },
    LOW: { color: '#71717a', backgroundColor: 'rgba(113,113,122,0.15)', borderColor: 'rgba(113,113,122,0.3)' },
  }
  return (
    <span className="priority-badge" style={styles[priority] ?? styles.MEDIUM}>
      {priority}
    </span>
  )
}

// =====================================================
// Pipeline Progress
// =====================================================
const PIPELINE_STEPS = [
  { key: 'extract',    label: 'Extract Financial Data' },
  { key: 'commentary', label: 'Generate AI Commentary' },
  { key: 'excel',      label: 'Build Excel Model' },
  { key: 'report',     label: 'Generate Word Report' },
  { key: 'next_steps', label: 'Compute Next Steps' },
]

const PipelineProgress = ({ status }: { status: JobStatus | null }) => {
  const logEntries = status?.progress ?? status?.log ?? []

  const stepStates = PIPELINE_STEPS.map((step) => {
    const entries = logEntries.filter((e) => e.step === step.key)
    const isDone    = entries.some((e) => e.done)
    const isRunning = entries.length > 0 && !isDone
    const latestMsg = entries.length > 0 ? entries[entries.length - 1].message : null
    return { ...step, isDone, isRunning, latestMsg }
  })

  const company = status?.company_name || 'your document'

  return (
    <div className="pipeline-v2">
      <div className="pipeline-v2-header">
        <Loader2 size={16} className="spin pipeline-v2-spinner" />
        <span>Analysing {company}...</span>
      </div>

      <div className="pipeline-v2-steps">
        {stepStates.map((step, i) => {
          const state   = step.isDone ? 'done' : step.isRunning ? 'running' : 'pending'
          const isLast  = i === PIPELINE_STEPS.length - 1
          return (
            <div key={step.key} className="pipeline-v2-step">
              <div className="pipeline-v2-left">
                <div className={`pipeline-v2-circle pvc-${state}`}>
                  {step.isDone ? <Check size={11} /> : <span>{i + 1}</span>}
                </div>
                {!isLast && (
                  <div className={`pipeline-v2-line ${step.isDone ? 'pvl-done' : step.isRunning ? 'pvl-running' : ''}`} />
                )}
              </div>
              <div className="pipeline-v2-right">
                <span className={`pipeline-v2-label pvtext-${state}`}>{step.label}</span>
                {step.latestMsg && state !== 'pending' && (
                  <span className="pipeline-v2-sub">{step.latestMsg}</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// =====================================================
// Analysis Header (results)
// =====================================================

/** Pull last non-null entry from a nullable array. */
function lastVal(arr: (number | null)[] | undefined): number | null {
  if (!arr) return null
  for (let i = arr.length - 1; i >= 0; i--) {
    if (arr[i] !== null && arr[i] !== undefined) return arr[i] as number
  }
  return null
}

/** Strip nulls; return at least a 2-point flat line for sparkline rendering. */
function sparkData(arr: (number | null)[] | undefined): number[] {
  const filtered = (arr ?? []).filter((v): v is number => v !== null && v !== undefined)
  return filtered.length >= 2 ? filtered : [0, 0]
}

function currencySymbol(currency: string | undefined): string {
  const map: Record<string, string> = { USD: '$', INR: '\u20B9', EUR: '\u20AC', GBP: '\u00A3' }
  return map[currency ?? ''] ?? ''
}

function unitSuffix(unit: string | undefined): string {
  const map: Record<string, string> = { Millions: 'M', Crores: 'Cr', Billions: 'B' }
  return map[unit ?? ''] ?? ''
}

const AnalysisHeader = ({
  status,
  jobId,
}: {
  status: JobStatus
  jobId: string
}) => {
  const companyName = status.company_name || 'Analysis'
  const reportUrl = getDownloadUrl(jobId, 'report')
  const excelUrl = getDownloadUrl(jobId, 'excel')
  const m: JobMetrics | null | undefined = status.metrics
  const sym  = currencySymbol(status.currency)
  const unit = unitSuffix(status.unit)
  const metricYears = m?.years?.length
    ? m.years.map((year) => `FY${year}`).join(' - ')
    : (status.fiscal_years ?? []).map((year) => `FY${year}`).join(' - ')

  const grossMargin = lastVal(m?.gross_margin_pct)
  const fcf         = lastVal(m?.fcf)
  const de          = lastVal(m?.debt_equity)
  const revenue     = lastVal(m?.revenue)

  return (
    <div className="analysis-header animate-on-scroll visible">
      <div className="analysis-status">
        <div className="status-icon success">
          <Check size={28} />
          <div className="status-pulse" />
        </div>
        <div className="status-text">
          <h2>{companyName} - Analysis Complete</h2>
          <p>Investment-grade analysis ready for download</p>
        </div>
      </div>

      <div className="quick-stats">
        <div className="stat-item">
          <span className="stat-value">
            {grossMargin !== null
              ? <AnimatedCounter value={grossMargin} suffix="%" decimals={1} />
              : <span style={{ color: 'var(--text-muted)' }}>--</span>}
          </span>
          <span className="stat-label">Gross Margin</span>
          <Sparkline data={sparkData(m?.gross_margin_pct)} color="var(--accent-green)" height={28} />
          <span className="stat-trend">{metricYears || 'Trend unavailable'}</span>
        </div>
        <div className="stat-item">
          <span className="stat-value">
            {fcf !== null
              ? <AnimatedCounter value={fcf} prefix={sym} suffix={` ${unit}`} decimals={0} />
              : <span style={{ color: 'var(--text-muted)' }}>--</span>}
          </span>
          <span className="stat-label">Free Cash Flow</span>
          <Sparkline data={sparkData(m?.fcf)} color="var(--accent-green)" height={28} />
          <span className="stat-trend">{metricYears || 'Trend unavailable'}</span>
        </div>
        <div className={`stat-item${de !== null && de > 2 ? ' negative' : ''}`}>
          <span className="stat-value">
            {de !== null
              ? <AnimatedCounter value={de} suffix="x" decimals={1} />
              : <span style={{ color: 'var(--text-muted)' }}>--</span>}
          </span>
          <span className="stat-label">Debt/Equity</span>
          <Sparkline data={sparkData(m?.debt_equity)} color={de !== null && de > 2 ? 'var(--accent-orange)' : 'var(--accent-green)'} height={28} />
          <span className="stat-trend">{metricYears || 'Trend unavailable'}</span>
        </div>
        <div className="stat-item">
          <span className="stat-value">
            {revenue !== null
              ? <AnimatedCounter value={revenue} prefix={sym} suffix={` ${unit}`} decimals={0} />
              : <span style={{ color: 'var(--text-muted)' }}>--</span>}
          </span>
          <span className="stat-label">Revenue</span>
          <Sparkline data={sparkData(m?.revenue)} color="var(--accent-purple)" height={28} />
          <span className="stat-trend">{metricYears || 'Trend unavailable'}</span>
        </div>
      </div>

      {/* Download buttons */}
      <div className="downloads-section" style={{ marginTop: '1.25rem' }}>
        <h3 className="section-label" style={{ marginBottom: '0.75rem' }}>DOWNLOADS</h3>
        <div className="download-cards">
          <div className="download-card">
            <div className="card-inner">
              <div className="download-preview word">
                <FileText size={28} />
              </div>
              <div className="download-info">
                <span className="download-type">WORD REPORT</span>
                <span className="download-title">AI Analysis Report</span>
                <span className="download-desc">7-section investment commentary</span>
              </div>
              <a
                href={reportUrl}
                className="download-btn"
                download
                title="Download Word Report"
              >
                <Download size={16} />
              </a>
            </div>
            <div className="card-glow" />
          </div>

          <div className="download-card">
            <div className="card-inner">
              <div className="download-preview excel">
                <FileSpreadsheet size={28} />
              </div>
              <div className="download-info">
                <span className="download-type">EXCEL MODEL</span>
                <span className="download-title">Financial Model</span>
                <span className="download-desc">IS - BS - CF - Ratios - DCF - DDM</span>
              </div>
              <a
                href={excelUrl}
                className="download-btn"
                download
                title="Download Excel Model"
              >
                <Download size={16} />
              </a>
            </div>
            <div className="card-glow" />
          </div>
        </div>
      </div>
    </div>
  )
}

// =====================================================
// Recommendations
// =====================================================
interface Recommendation {
  priority: string
  title: string
  description: string
  icon: React.ElementType
}

function iconForPriority(priority: string): React.ElementType {
  if (priority === 'HIGH') return AlertTriangle
  if (priority === 'MEDIUM') return TrendingUp
  return BarChart3
}

function buildRecommendations(status: JobStatus | null): Recommendation[] {
  const nextSteps = status?.next_steps ?? []
  if (!nextSteps.length) return defaultRecs
  return nextSteps.map((step) => ({
    priority: step.priority || 'MEDIUM',
    title: step.title,
    description: step.description,
    icon: iconForPriority(step.priority || 'MEDIUM'),
  }))
}

const defaultRecs: Recommendation[] = [
  {
    priority: 'HIGH',
    icon: AlertTriangle,
    title: 'Investigate EBIT Decline Before Adding Exposure',
    description:
      'The year-on-year EBIT decline is irreconcilable with reported gross margins and free cash flow. Management commentary is required before making a buy decision.',
  },
  {
    priority: 'HIGH',
    icon: TrendingUp,
    title: 'Stress-Test Refinancing Risk on Debt Stack',
    description:
      'With elevated net debt and interest expense, model three refinancing scenarios (base, adverse, stress) against current EBITDA coverage ratios.',
  },
  {
    priority: 'MEDIUM',
    icon: DollarSign,
    title: 'Quantify FX Drag on Reported Revenue',
    description:
      'Revenue growth appears constrained by emerging market currency headwinds. Strip out FX effects to understand organic growth trajectory.',
  },
  {
    priority: 'MEDIUM',
    icon: PieChart,
    title: 'Monitor Working Capital Deterioration',
    description:
      'Working capital has deteriorated materially over the past two years. Track DSO and DPO trends monthly as a leading liquidity indicator.',
  },
  {
    priority: 'LOW',
    icon: BarChart3,
    title: 'Validate DCF Assumptions Against Peer Set',
    description:
      'Compare implied WACC and terminal growth rate against sector peers to confirm the equity value range is within a defensible band.',
  },
  {
    priority: 'LOW',
    icon: TrendingDown,
    title: 'Review Dividend Sustainability',
    description:
      'Cross-check the dividend payout ratio against free cash flow generation and debt covenants to confirm dividend continuity is feasible.',
  },
]

const RecommendationsSection = ({
  recs,
}: {
  recs: Recommendation[]
}) => (
  <div className="recommendations-section">
    <h3 className="section-label">RECOMMENDED NEXT STEPS</h3>
    <div className="recommendations-list">
      {recs.map((rec, i) => {
        const Icon = rec.icon
        return (
          <div
            key={i}
            className="recommendation-card"
            style={{ animationDelay: `${i * 0.1}s` }}
          >
            <div className="rec-header">
              <PriorityBadge priority={rec.priority} />
              <h4 className="rec-title">{rec.title}</h4>
            </div>
            <p className="rec-description">{rec.description}</p>
            <div className="rec-progress">
              <div className="progress-bar" style={{ width: `${30 + (i * 13) % 50}%` }} />
            </div>
          </div>
        )
      })}
    </div>
  </div>
)

// =====================================================
// Empty State
// =====================================================
const EmptyMain = () => (
  <div className="empty-main">
    <div className="empty-main-icon">
      <BarChart3 size={40} />
    </div>
    <h2>Upload a report to begin</h2>
    <p>
      Select a PDF annual report on the left,wait for the company details to be filled in automatically (or enter them yourself), and
      then click Run Analysis to generate your institutional-grade financial model.
    </p>
    <div className="placeholder-metrics">
      {['Revenue', 'EBITDA', 'FCF'].map((label) => (
        <div key={label} className="placeholder-card">
          <div className="skeleton placeholder-line wide" />
          <div className="skeleton placeholder-num" />
          <div className="skeleton placeholder-line narrow" />
        </div>
      ))}
    </div>
  </div>
)

// =====================================================
// Error Card
// =====================================================
const ErrorCard = ({ message }: { message: string }) => (
  <div className="error-card">
    <div className="error-card-icon">
      <AlertTriangle size={22} />
    </div>
    <div>
      <h3>Analysis failed</h3>
      <p>{message}</p>
    </div>
  </div>
)

// =====================================================
// Chat Widget
// =====================================================
const ChatWidget = ({ jobId }: { jobId: string }) => {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'assistant', content: 'Ask me anything about this analysis. I can explain ratios, valuation assumptions, or compare metrics across years.' },
  ])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async () => {
    const text = input.trim()
    if (!text || sending) return
    setInput('')
    const userMsg: ChatMessage = { role: 'user', content: text }
    setMessages((prev) => [...prev, userMsg])
    setSending(true)
    try {
      const res = await sendChat(jobId, text, messages)
      setMessages((prev) => [...prev, { role: 'assistant', content: res.reply }])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Error: ${err instanceof Error ? err.message : 'Failed to get response.'}` },
      ])
    } finally {
      setSending(false)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <>
      {open && (
        <div className="chat-panel">
          <div className="chat-header">
            <div className="chat-header-info">
              <span className="chat-header-dot" />
              <div>
                <h4>Analysis Chat</h4>
                <p>Ask questions about this report</p>
              </div>
            </div>
            <button className="chat-close" onClick={() => setOpen(false)}>
              <X size={16} />
            </button>
          </div>

          <div className="chat-messages">
            {messages.map((msg, i) => (
              <div key={i} className={`chat-message ${msg.role}`}>
                <div className="chat-avatar">
                  {msg.role === 'user' ? 'U' : 'AI'}
                </div>
                <div className="chat-bubble chat-bubble-md">
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                </div>
              </div>
            ))}
            {sending && (
              <div className="chat-message assistant">
                <div className="chat-avatar">AI</div>
                <div className="chat-typing">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <div className="chat-input-area">
            <textarea
              className="chat-input"
              rows={1}
              placeholder="Ask about margins, DCF, ratios..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
            />
            <button className="chat-send" onClick={send} disabled={!input.trim() || sending}>
              {sending ? <Loader2 size={16} className="spin" /> : <Send size={16} />}
            </button>
          </div>

          <p className="chat-notice">Grounded in this analysis only - no external data.</p>
        </div>
      )}

      <button className="chat-fab" onClick={() => setOpen((o) => !o)} title="Open Analysis Chat">
        {open ? <X size={22} /> : <MessageSquare size={22} />}
      </button>
    </>
  )
}

// =====================================================
// App Header
// =====================================================
const AppHeader = () => {
  const [userEmail, setUserEmail] = useState('')
  const authUrl = getGoogleAuthUrl()

  useEffect(() => {
    handleAuthCallback()
    const token = getToken()
    if (token) {
      const info = decodeTokenPayload(token)
      setUserEmail(info?.email || '')
    }
  }, [])

  return (
    <header className="header">
      <div className="header-left">
        <Link href="/" className="logo-container">
          <div className="logo-mark">
            <Image
              src="/logo_cropped.png"
              alt="FinAnalyse"
              width={40}
              height={40}
              className="logo-image"
              style={{ objectFit: 'contain' }}
            />
          </div>
          <div className="logo-text">
            <span className="logo-title">FinAnalyse</span>
            <span className="logo-subtitle">FINANCIAL ADVISORY &amp; ANALYTICS</span>
          </div>
        </Link>

        <div className="header-divider" />

        <nav className="nav-tabs">
          <Link href="/analyse" className="nav-tab active">
            <BarChart3 size={18} />
            <span>Analyse</span>
          </Link>
          <Link href="/reports" className="nav-tab">
            <FileText size={18} />
            <span>Reports</span>
          </Link>
        </nav>
      </div>

      <div className="header-right header-auth">
        {userEmail ? (
          <>
            <div className="user-pill">
              <span className="user-dot" />
              <span>{userEmail}</span>
            </div>
            <button
              className="btn-secondary"
              style={{ padding: '0.4rem 0.875rem', fontSize: '0.8125rem' }}
              onClick={() => { removeToken(); setUserEmail('') }}
            >
              Sign Out
            </button>
          </>
        ) : (
          <a href={authUrl} className="btn-primary" style={{ padding: '0.4rem 0.875rem', fontSize: '0.8125rem' }}>
            Sign In
          </a>
        )}
      </div>
    </header>
  )
}

// =====================================================
// Dot Matrix
// =====================================================
const DotMatrix = () => {
  const colors = [
    'var(--accent-green)',
    'var(--accent-orange)',
    'var(--accent-purple)',
    'var(--text-muted)',
  ]
  const rows = 4
  const cols = 6
  return (
    <div className="dot-matrix">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="dot-row">
          {Array.from({ length: cols }).map((_, c) => (
            <span
              key={c}
              className="dot animated"
              style={{
                backgroundColor: colors[(r * cols + c) % colors.length],
                animationDelay: `${((r * cols + c) * 0.15) % 3}s`,
              }}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

// =====================================================
// Main Analyse Page
// =====================================================
type PageState = 'idle' | 'running' | 'done' | 'error'

function AnalysePageInner() {
  const searchParams = useSearchParams()
  const requestedJobId = searchParams.get('job_id')
  const isHistoryView = Boolean(requestedJobId)
  const [files, setFiles] = useState<FileItem[]>([])
  const [config, setConfig] = useState<Config>({
    companyName: '',
    fiscalYears: '',
    currency: 'USD',
    units: 'Millions',
    ticker: '',
  })

  const [isDetecting, setIsDetecting] = useState(false)
  const detectedFilesRef = useRef<Set<string>>(new Set())

  const [pageState, setPageState] = useState<PageState>('idle')
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const pollRef = useRef<NodeJS.Timeout | null>(null)
  const recommendations = buildRecommendations(jobStatus)

  // Restore a previous analysis when navigated from the Reports eye icon
  useEffect(() => {
    const fromJobId = requestedJobId
    if (!fromJobId) return
    setPageState('running')

    // Use getJobDetail (history endpoint) first - it always reads from SQLite
    // and returns company_name/currency/unit reliably for completed jobs.
    // Fall back to pollStatus for jobs that are still running in-memory.
    getJobDetail(fromJobId)
      .then((status) => {
        setJobId(fromJobId)
        setJobStatus(status)
        if (status.status === 'done') {
          setPageState('done')
        } else if (status.status === 'error') {
          setErrorMsg(status.error || status.error_message || 'This analysis failed.')
          setPageState('error')
        } else {
          // Still running - switch to live polling
          pollRef.current = setInterval(async () => {
            try {
              const s = await pollStatus(fromJobId)
              setJobStatus(s)
              if (s.status === 'done') { stopPolling(); setPageState('done') }
              else if (s.status === 'error') {
                stopPolling()
                setErrorMsg(s.error || s.error_message || 'An unknown error occurred.')
                setPageState('error')
              }
            } catch { /* ignore transient poll errors */ }
          }, 2000)
        }
      })
      .catch(() => {
        // History lookup failed - show an error rather than silently going blank
        setErrorMsg('Could not load this analysis. It may have been deleted.')
        setPageState('error')
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedJobId])

  // Auto-detect company name + fiscal years when new PDFs are added
  useEffect(() => {
    const newPdfs = files.filter(
      (item) =>
        item.file.type === 'application/pdf' &&
        !detectedFilesRef.current.has(item.file.name + item.file.size)
    )
    if (newPdfs.length === 0) return

    newPdfs.forEach((item) =>
      detectedFilesRef.current.add(item.file.name + item.file.size)
    )

    setIsDetecting(true)
    Promise.all(newPdfs.map((item) => autoDetect(item.file)))
      .then((results) => {
        const detectedCompany = results.find((r) => r.company_name)?.company_name || ''
        const detectedYears = results.flatMap((r) => r.fiscal_years)

        setConfig((prev) => {
          // Merge detected years with any already in the field
          const existingYears = prev.fiscalYears
            ? prev.fiscalYears.split(',').map((y) => parseInt(y.trim())).filter(Boolean)
            : []
          const merged = Array.from(new Set([...existingYears, ...detectedYears])).sort()
          return {
            ...prev,
            companyName: prev.companyName || detectedCompany,
            fiscalYears: merged.length ? merged.join(',') : prev.fiscalYears,
          }
        })
      })
      .catch(() => {/* silent - user can fill manually */})
      .finally(() => setIsDetecting(false))
  }, [files])

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  useEffect(() => () => stopPolling(), [])

  const runAnalysis = async () => {
    if (!files.length) return
    setPageState('running')
    setErrorMsg('')
    setJobStatus(null)

    try {
      const fd = new FormData()
      files.forEach((item) => fd.append('files', item.file))
      if (config.companyName) fd.append('company', config.companyName)
      if (config.ticker) fd.append('ticker', config.ticker)
      if (config.fiscalYears) fd.append('years', config.fiscalYears)
      fd.append('currency', config.currency)
      fd.append('unit', config.units)

      const { job_id } = await startAnalysis(fd)
      setJobId(job_id)

      pollRef.current = setInterval(async () => {
        try {
          const status = await pollStatus(job_id)
          setJobStatus(status)
          if (status.status === 'done') {
            stopPolling()
            setPageState('done')
          } else if (status.status === 'error') {
            stopPolling()
            setErrorMsg(status.error || status.error_message || 'An unknown error occurred.')
            setPageState('error')
          }
        } catch (err) {
          console.error('Polling error', err)
        }
      }, 2000)
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Failed to start analysis.')
      setPageState('error')
    }
  }

  return (
    <>
      <AppHeader />

      <div className={`analyse-page${isHistoryView ? ' report-view' : ''}`}>
        {!isHistoryView && (
          <aside className="sidebar">
            <FileUpload files={files} setFiles={setFiles} />
            <ConfigPanel
              config={config}
              setConfig={setConfig}
              onRun={runAnalysis}
              isRunning={pageState === 'running'}
              isDetecting={isDetecting}
              hasFiles={files.length > 0}
            />
            <div className="sidebar-metrics">
              <h3 className="section-label">QUICK METRICS</h3>
              <DotMatrix />
            </div>
          </aside>
        )}

        {/* Main */}
        <main className="main-content">
          {pageState === 'idle' && <EmptyMain />}

          {pageState === 'running' && (
            <PipelineProgress status={jobStatus} />
          )}

          {pageState === 'done' && jobStatus && jobId && (
            <>
              <AnalysisHeader status={jobStatus} jobId={jobId} />
              <RecommendationsSection recs={recommendations} />
            </>
          )}

          {pageState === 'error' && <ErrorCard message={errorMsg} />}
        </main>
      </div>

      {/* Chat FAB - only when analysis is done */}
      {pageState === 'done' && jobId && <ChatWidget jobId={jobId} />}
    </>
  )
}

export default function AnalysePage() {
  return (
    <Suspense>
      <AnalysePageInner />
    </Suspense>
  )
}
