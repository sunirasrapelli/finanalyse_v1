'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import Image from 'next/image'
import {
  Search,
  FileText,
  Download,
  Trash2,
  Eye,
  Check,
  Loader2,
  X,
  BarChart3,
  RefreshCw,
} from 'lucide-react'
import { getHistory, deleteJob, getDownloadUrl, getGoogleAuthUrl, type HistoryEntry } from '@/lib/api'
import { handleAuthCallback, getToken, decodeTokenPayload, removeToken } from '@/lib/auth'

// =====================================================
// Status Badge
// =====================================================
const StatusBadge = ({ status }: { status: string }) => {
  type Cfg = { color: string; bg: string; border: string; Icon: React.ElementType; spin?: boolean }
  const map: Record<string, Cfg> = {
    done: {
      color: '#10b981',
      bg: 'rgba(16,185,129,0.15)',
      border: 'rgba(16,185,129,0.3)',
      Icon: Check,
    },
    running: {
      color: '#3B82F6',
      bg: 'rgba(59,130,246,0.15)',
      border: 'rgba(59,130,246,0.3)',
      Icon: Loader2,
      spin: true,
    },
    queued: {
      color: '#3B82F6',
      bg: 'rgba(59,130,246,0.15)',
      border: 'rgba(59,130,246,0.3)',
      Icon: Loader2,
      spin: true,
    },
    error: {
      color: '#ef4444',
      bg: 'rgba(239,68,68,0.15)',
      border: 'rgba(239,68,68,0.3)',
      Icon: X,
    },
  }
  const cfg = map[status] ?? map.done
  const Icon = cfg.Icon

  const label =
    status === 'done'
      ? 'Completed'
      : status === 'error'
      ? 'Failed'
      : status === 'queued'
      ? 'Queued'
      : 'Processing'

  return (
    <span
      className="status-badge"
      style={{ color: cfg.color, backgroundColor: cfg.bg, borderColor: cfg.border }}
    >
      <Icon size={12} className={cfg.spin ? 'spin' : ''} />
      {label}
    </span>
  )
}

// =====================================================
// App Header (shared)
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
              style={{ height: 40, width: 'auto', objectFit: 'contain' }}
            />
          </div>
          <div className="logo-text">
            <span className="logo-title">FinAnalyse</span>
            <span className="logo-subtitle">FINANCIAL ADVISORY &amp; ANALYTICS</span>
          </div>
        </Link>

        <div className="header-divider" />

        <nav className="nav-tabs">
          <Link href="/analyse" className="nav-tab">
            <BarChart3 size={18} />
            <span>Analyse</span>
          </Link>
          <Link href="/reports" className="nav-tab active">
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
// Format date
// =====================================================
function fmtDate(dateStr?: string): string {
  if (!dateStr) return '-'
  try {
    return new Date(dateStr).toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return dateStr
  }
}

// =====================================================
// Reports Page
// =====================================================
export default function ReportsPage() {
  const [reports, setReports] = useState<HistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [yearFilter, setYearFilter] = useState('')
  const [deleting, setDeleting] = useState<string | null>(null)

  const fetchReports = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getHistory()
      setReports(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load reports')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchReports()
  }, [])

  const handleDelete = async (jobId: string) => {
    if (!confirm('Delete this report? This cannot be undone.')) return
    setDeleting(jobId)
    try {
      await deleteJob(jobId)
      setReports((prev) => prev.filter((r) => r.job_id !== jobId))
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to delete')
    } finally {
      setDeleting(null)
    }
  }

  const clearFilters = () => {
    setSearchQuery('')
    setStatusFilter('all')
    setYearFilter('')
  }

  const filtered = reports.filter((r) => {
    if (
      searchQuery &&
      !(r.company_name || '').toLowerCase().includes(searchQuery.toLowerCase())
    ) return false
    if (statusFilter !== 'all' && r.status !== statusFilter) return false
    if (
      yearFilter &&
      !(r.fiscal_years || []).some((y) => String(y).includes(yearFilter))
    ) return false
    return true
  })

  return (
    <>
      <AppHeader />

      {/* Background */}
      <div
        style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          pointerEvents: 'none', zIndex: 0,
        }}
        aria-hidden="true"
      >
        <div className="gradient-orb orb-1" />
        <div className="gradient-orb orb-2" />
        <div className="gradient-orb orb-3" />
        <div className="grid-pattern" />
      </div>

      <div className="reports-page">
        <div className="reports-header">
          <h1>Financial Reports</h1>
          <span className="report-count">
            {filtered.length} report{filtered.length !== 1 ? 's' : ''}
          </span>
          <button
            className="btn-secondary"
            style={{ marginLeft: 'auto', padding: '0.4rem 0.875rem', fontSize: '0.8125rem', display: 'flex', alignItems: 'center', gap: '0.375rem' }}
            onClick={fetchReports}
            disabled={loading}
          >
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
            Refresh
          </button>
          <Link
            href="/analyse"
            className="btn-primary"
            style={{ padding: '0.4rem 0.875rem', fontSize: '0.8125rem' }}
          >
            New Analysis
          </Link>
        </div>

        {/* Filters */}
        <div className="filters-bar">
          <span className="filter-label">FILTER</span>

          <div className="filter-input-wrapper">
            <Search size={16} />
            <input
              type="text"
              placeholder="Search company..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="filter-input"
            />
          </div>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="filter-select"
          >
            <option value="all">All Statuses</option>
            <option value="done">Completed</option>
            <option value="running">Processing</option>
            <option value="queued">Queued</option>
            <option value="error">Failed</option>
          </select>

          <div className="filter-input-wrapper">
            <input
              type="text"
              placeholder="Year e.g. 2024"
              value={yearFilter}
              onChange={(e) => setYearFilter(e.target.value)}
              className="filter-input small"
            />
          </div>

          <button className="filter-btn clear" onClick={clearFilters}>
            Clear
          </button>
        </div>

        {/* Error state */}
        {error && (
          <div
            style={{
              padding: '1rem 1.25rem',
              background: 'rgba(239,68,68,0.06)',
              border: '1px solid rgba(239,68,68,0.2)',
              borderRadius: '8px',
              color: 'var(--accent-red)',
              fontSize: '0.875rem',
              marginBottom: '1rem',
            }}
          >
            {error}
          </div>
        )}

        {/* Loading skeleton */}
        {loading && !error && (
          <div className="reports-table-wrapper">
            <div style={{ padding: '2rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
              {[1, 2, 3].map((i) => (
                <div key={i} className="skeleton" style={{ height: 52, borderRadius: 8 }} />
              ))}
            </div>
          </div>
        )}

        {/* Table */}
        {!loading && (
          <div className="reports-table-wrapper">
            <table className="reports-table">
              <thead>
                <tr>
                  <th>COMPANY</th>
                  <th>STATUS</th>
                  <th>FISCAL YEARS</th>
                  <th>CURRENCY - UNITS</th>
                  <th>DATE</th>
                  <th>ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((report, idx) => (
                  <tr key={report.job_id} style={{ animationDelay: `${idx * 0.05}s` }}>
                    <td className="company-cell">
                      {report.company_name || 'Unknown Company'}
                    </td>
                    <td>
                      <StatusBadge status={report.status} />
                    </td>
                    <td>
                      <div className="year-pills">
                        {(report.fiscal_years || []).length > 0 ? (
                          (report.fiscal_years || []).map((y) => (
                            <span key={y} className="year-pill">{y}</span>
                          ))
                        ) : (
                          <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>-</span>
                        )}
                      </div>
                    </td>
                    <td className="currency-cell">
                      {report.currency ?? '-'} {report.unit ? `- ${report.unit}` : ''}
                    </td>
                    <td className="date-cell">
                      {fmtDate(report.created_at)}
                    </td>
                    <td>
                      <div className="action-buttons">
                        <a
                          href={getDownloadUrl(report.job_id, 'report')}
                          className={`action-btn primary ${report.status !== 'done' ? '' : ''}`}
                          style={report.status !== 'done' ? { pointerEvents: 'none', opacity: 0.4 } : {}}
                          download
                          title="Download Word Report"
                        >
                          <Download size={14} /> Report
                        </a>
                        <a
                          href={getDownloadUrl(report.job_id, 'excel')}
                          className="action-btn secondary"
                          style={report.status !== 'done' ? { pointerEvents: 'none', opacity: 0.4 } : {}}
                          download
                          title="Download Excel Model"
                        >
                          <Download size={14} /> Excel
                        </a>
                        <Link
                          href={`/analyse?job_id=${report.job_id}`}
                          className="action-btn icon"
                          title="View Analysis"
                        >
                          <Eye size={16} />
                        </Link>
                        <button
                          className="action-btn icon danger"
                          onClick={() => handleDelete(report.job_id)}
                          disabled={deleting === report.job_id}
                          title="Delete"
                        >
                          {deleting === report.job_id ? (
                            <Loader2 size={14} className="spin" />
                          ) : (
                            <Trash2 size={16} />
                          )}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {filtered.length === 0 && !loading && (
              <div className="empty-state">
                <FileText size={48} />
                <h3>No reports found</h3>
                <p>
                  {reports.length === 0
                    ? 'Upload an annual report PDF to get started.'
                    : 'Try adjusting your filters or clear them to see all reports.'}
                </p>
                {reports.length === 0 && (
                  <Link href="/analyse" className="btn-primary" style={{ marginTop: '0.5rem' }}>
                    New Analysis
                  </Link>
                )}
              </div>
            )}
          </div>
        )}

        <div className="table-footer">
          Showing {filtered.length} of {reports.length} reports
        </div>
      </div>
    </>
  )
}
