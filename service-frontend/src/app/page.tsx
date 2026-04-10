'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import Image from 'next/image'
import {
  Upload,
  FileSpreadsheet,
  FileText,
  BarChart3,
  MessageSquare,
  TrendingUp,
  ChevronDown,
  ArrowRight,
  Sparkles,
  Download,
} from 'lucide-react'
import { getGoogleAuthUrl } from '@/lib/api'
import { handleAuthCallback, isLoggedIn, getToken, decodeTokenPayload, removeToken } from '@/lib/auth'

// =====================================================
// Animated Counter
// =====================================================
const AnimatedCounter = ({
  value,
  suffix = '',
  prefix = '',
}: {
  value: number
  suffix?: string
  prefix?: string
}) => {
  const [count, setCount] = useState(0)
  const ref = useRef<HTMLSpanElement>(null)
  const started = useRef(false)

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && !started.current) {
          started.current = true
          const duration = 1800
          const end = value
          const increment = end / (duration / 16)
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
      { threshold: 0.5 }
    )
    if (ref.current) observer.observe(ref.current)
    return () => observer.disconnect()
  }, [value])

  return (
    <span ref={ref} className="animated-counter">
      {prefix}
      {count.toFixed(value % 1 !== 0 ? 0 : 0)}
      {suffix}
    </span>
  )
}

// =====================================================
// Sparkline SVG
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

  const gradId = `sg-${color.replace(/[^a-z0-9]/gi, '')}`

  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ width: '100%', height }}>
      <defs>
        <linearGradient id={gradId} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline
        points={`0,${height} ${points} 100,${height}`}
        fill={`url(#${gradId})`}
      />
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
// Header
// =====================================================
const Header = () => {
  const [loggedIn, setLoggedIn] = useState(false)
  const [userEmail, setUserEmail] = useState('')
  const authUrl = getGoogleAuthUrl()

  useEffect(() => {
    handleAuthCallback()
    const token = getToken()
    if (token) {
      setLoggedIn(true)
      const info = decodeTokenPayload(token)
      setUserEmail(info?.email || 'User')
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
              width={46}
              height={46}
              className="logo-image"
              style={{ objectFit: 'contain' }}
            />
          </div>
          <div className="logo-text">
            <span className="logo-title">FinAnalyse</span>
            <span className="logo-subtitle">FINANCIAL ADVISORY &amp; ANALYTICS</span>
          </div>
        </Link>
      </div>

      <div className="header-right header-auth">
        {loggedIn ? (
          <>
            <div className="user-pill">
              <span className="user-dot" />
              <span>{userEmail}</span>
            </div>
            <Link href="/analyse" className="btn-primary" style={{ padding: '0.5rem 1.25rem', fontSize: '0.875rem' }}>
              Go to App
            </Link>
            <button
              className="btn-secondary"
              style={{ padding: '0.5rem 1rem', fontSize: '0.875rem' }}
              onClick={() => { removeToken(); setLoggedIn(false) }}
            >
              Sign Out
            </button>
          </>
        ) : (
          <>
            <a href={authUrl} className="btn-secondary" style={{ padding: '0.5rem 1.25rem', fontSize: '0.875rem' }}>
              Log In
            </a>
            <a href={authUrl} className="btn-primary" style={{ padding: '0.5rem 1.25rem', fontSize: '0.875rem' }}>
              Sign Up
            </a>
          </>
        )}
      </div>
    </header>
  )
}

// =====================================================
// Scroll animation hook
// =====================================================
function useScrollAnimation() {
  useEffect(() => {
    const elements = document.querySelectorAll('.animate-on-scroll')
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('visible')
          }
        })
      },
      { threshold: 0.12 }
    )
    elements.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [])
}

// =====================================================
// Hero Section
// =====================================================
const HeroSection = () => {
  const authUrl = getGoogleAuthUrl()

  return (
    <section className="hero-section">
      <div className="hero-tag">
        <span className="hero-tag-dot" />
        AI-powered equity research
      </div>

      <h1 className="hero-headline">
        Institutional-grade financial analysis.{' '}
        <span className="highlight">Automated.</span>
      </h1>

      <p className="hero-subheadline">
        Upload an annual report PDF. Get a 19-sheet Excel model, AI investment commentary,
        and 6 analyst recommendations in minutes.
      </p>

      <div className="hero-ctas">
        <a href={authUrl} className="btn-primary">
          <Sparkles size={18} />
          Get Started Free
        </a>
        <Link href="/analyse" className="btn-secondary">
          View Sample Report
          <ArrowRight size={16} />
        </Link>
      </div>

      <div className="hero-metrics">
        <div className="hero-metric-card">
          <span className="hero-metric-value">60.1%</span>
          <span className="hero-metric-label">Gross Margin</span>
          <Sparkline data={[55, 57, 58, 56, 59, 60.1]} color="var(--accent-green)" height={32} />
        </div>
        <div className="hero-metric-card">
          <span className="hero-metric-value">$3.63B</span>
          <span className="hero-metric-label">Free Cash Flow</span>
          <Sparkline data={[2.8, 3.1, 2.9, 3.4, 3.2, 3.63]} color="var(--accent-green)" height={32} />
        </div>
        <div className="hero-metric-card">
          <span className="hero-metric-value negative">21.9x</span>
          <span className="hero-metric-label">Debt/Equity</span>
          <Sparkline data={[12, 14, 16, 18, 20, 21.9]} color="var(--accent-orange)" height={32} />
        </div>
        <div className="hero-metric-card">
          <span className="hero-metric-value">$20.38B</span>
          <span className="hero-metric-label">Revenue</span>
          <Sparkline data={[18.5, 19.2, 19.8, 20.1, 20.1, 20.38]} color="var(--accent-purple)" height={32} />
        </div>
      </div>

      <div
        className="scroll-indicator"
        onClick={() => document.getElementById('how-it-works')?.scrollIntoView({ behavior: 'smooth' })}
      >
        <span style={{ fontSize: '0.7rem', letterSpacing: '0.1em', fontFamily: 'Space Grotesk, sans-serif' }}>
          SCROLL
        </span>
        <ChevronDown size={18} />
      </div>
    </section>
  )
}

// =====================================================
// How It Works
// =====================================================
const HowItWorksSection = () => {
  const steps = [
    {
      num: '01',
      icon: Upload,
      title: 'Upload Annual Report',
      desc: 'Drag and drop your PDF. Supports up to 1 GB files. Chunked upload for large documents ensures nothing gets lost.',
    },
    {
      num: '02',
      icon: BarChart3,
      title: 'AI Extracts and Analyses',
      desc: 'Two-pass extraction: local PDF parsing then Claude AI gap-fill. 30+ financial ratios computed automatically with confidence scoring.',
    },
    {
      num: '03',
      icon: Download,
      title: 'Download Your Reports',
      desc: '19-sheet Excel model with live formulas, DCF valuation, WACC, beta regression, and a Word report with AI investment commentary.',
    },
  ]

  return (
    <section className="how-section" id="how-it-works">
      <div className="section-header animate-on-scroll">
        <p className="section-label" style={{ marginBottom: '0.75rem' }}>HOW IT WORKS</p>
        <h2>From PDF to institutional model in minutes</h2>
        <p>No spreadsheet gymnastics. No manual data entry. Just upload and analyse.</p>
      </div>

      <div className="steps-grid">
        {steps.map((step, i) => {
          const Icon = step.icon
          return (
            <div
              key={i}
              className="step-card animate-on-scroll"
              style={{ transitionDelay: `${i * 0.12}s` }}
            >
              <span className="step-number">{step.num}</span>
              <div className="step-icon-wrap">
                <Icon size={22} />
              </div>
              <h3>{step.title}</h3>
              <p>{step.desc}</p>
            </div>
          )
        })}
      </div>
    </section>
  )
}

// =====================================================
// Features Grid
// =====================================================
const FeaturesSection = () => {
  const features = [
    {
      icon: FileSpreadsheet,
      title: '19-Sheet Excel Model',
      desc: 'Cover, IS, BS, CF, Common Size, Ratios, Forecasting, Beta Regression, WACC, DCF, DDM, Comps, VaR, DuPont, Working Capital, and more - with live formulas and 6 embedded charts.',
    },
    {
      icon: FileText,
      title: 'AI Investment Commentary',
      desc: '7-section analysis: Executive Summary, Revenue, Profitability, Balance Sheet, Cash Flow, Key Risks, Key Strengths - all grounded in extracted figures.',
    },
    {
      icon: MessageSquare,
      title: 'Comparison Chat',
      desc: 'Compare two companies side-by-side using AI. Ask questions grounded in both completed analyses. No hallucinations - only figure-cited answers.',
    },
    {
      icon: TrendingUp,
      title: '6 Analyst Recommendations',
      desc: 'Prioritized next steps with specific figures cited. At least 1 high, 2 medium, 1 low priority. Each recommendation cites exact numbers from the model.',
    },
  ]

  return (
    <section className="features-section">
      <div className="section-header animate-on-scroll">
        <p className="section-label" style={{ marginBottom: '0.75rem' }}>WHAT YOU GET</p>
        <h2>Everything an equity analyst needs</h2>
        <p>Built to institutional standards with real financial modeling methodology.</p>
      </div>

      <div className="features-grid">
        {features.map((f, i) => {
          const Icon = f.icon
          return (
            <div
              key={i}
              className="feature-card animate-on-scroll"
              style={{ transitionDelay: `${i * 0.1}s` }}
            >
              <div className="feature-icon">
                <Icon size={22} />
              </div>
              <h3>{f.title}</h3>
              <p>{f.desc}</p>
            </div>
          )
        })}
      </div>
    </section>
  )
}

// =====================================================
// Stats Section
// =====================================================
const StatsSection = () => {
  const stats = [
    { value: 19, suffix: '', label: 'Excel Sheets' },
    { value: 30, suffix: '+', label: 'Financial Ratios' },
    { value: 7, suffix: '', label: 'AI Commentary Sections' },
    { value: 6, suffix: '', label: 'Analyst Recommendations' },
  ]

  return (
    <section className="stats-section">
      <div className="section-header animate-on-scroll">
        <p className="section-label" style={{ marginBottom: '0.75rem' }}>BY THE NUMBERS</p>
        <h2>Built for depth, not shortcuts</h2>
      </div>

      <div className="stats-grid">
        {stats.map((s, i) => (
          <div
            key={i}
            className="stat-card animate-on-scroll"
            style={{ transitionDelay: `${i * 0.1}s` }}
          >
            <span className="stat-big-number">
              <AnimatedCounter value={s.value} suffix={s.suffix} />
            </span>
            <span className="stat-big-label">{s.label}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

// =====================================================
// Output Preview Section
// =====================================================
const OutputsSection = () => {
  return (
    <section className="outputs-section">
      <div className="section-header animate-on-scroll">
        <p className="section-label" style={{ marginBottom: '0.75rem' }}>OUTPUT FORMATS</p>
        <h2>Two deliverables, ready to share</h2>
        <p>Download and present to clients or use directly in your investment workflow.</p>
      </div>

      <div className="outputs-grid">
        <div className="output-preview-card animate-on-scroll">
          <div className="output-preview-icon word">
            <FileText size={32} />
          </div>
          <div className="output-preview-info">
            <h3>AI Word Report</h3>
            <p>
              9-section investment report: cover page, 7-section AI commentary, financial
              ratios table, and professional disclaimer. Ready for client distribution.
            </p>
          </div>
        </div>

        <div className="output-preview-card animate-on-scroll" style={{ transitionDelay: '0.1s' }}>
          <div className="output-preview-icon excel">
            <FileSpreadsheet size={32} />
          </div>
          <div className="output-preview-info">
            <h3>Excel Financial Model</h3>
            <p>
              19-sheet workbook with live formulas - IS, BS, CF, Ratios, DCF, DDM,
              WACC, Beta Regression, VaR, DuPont, and 6 embedded charts.
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}

// =====================================================
// Footer CTA
// =====================================================
const FooterCTA = () => {
  const authUrl = getGoogleAuthUrl()

  return (
    <>
      <section className="footer-cta animate-on-scroll">
        <h2>Ready to analyse your first company?</h2>
        <p>Upload an annual report and get institutional-grade analysis in minutes.</p>
        <a href={authUrl} className="btn-primary" style={{ fontSize: '1rem', padding: '0.9rem 2.5rem' }}>
          <Sparkles size={18} />
          Get Started Free
        </a>
      </section>

      <footer className="footer-bottom">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Image src="/logo_cropped.png" alt="FinAnalyse" width={24} height={24} style={{ filter: 'invert(1) sepia(1) saturate(3) hue-rotate(190deg) brightness(1.2)', opacity: 0.7 }} />
          <span style={{ fontFamily: 'Space Grotesk, sans-serif', fontWeight: 600 }}>FinAnalyse</span>
        </div>
        <span>Built for Nurix Hackathon 2026</span>
      </footer>
    </>
  )
}

// =====================================================
// Main Landing Page
// =====================================================
export default function LandingPage() {
  useScrollAnimation()

  return (
    <>
      <div
        style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          pointerEvents: 'none',
          zIndex: 0,
          overflow: 'hidden',
        }}
        aria-hidden="true"
      >
        <div className="gradient-orb orb-1" />
        <div className="gradient-orb orb-2" />
        <div className="gradient-orb orb-3" />
        <div className="grid-pattern" />
      </div>

      <div style={{ position: 'relative', zIndex: 1 }}>
        <Header />
        <main>
          <HeroSection />
          <HowItWorksSection />
          <FeaturesSection />
          <StatsSection />
          <OutputsSection />
        </main>
        <FooterCTA />
      </div>
    </>
  )
}
