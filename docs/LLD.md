# Low-Level Design (LLD)

**Team:** Team PPO Nahi Milega (Suniras Ram Rapelli, Shikhar Kansal)
**Related PRD:** [PRD.md](./PRD.md)
**Last updated:** 9 April 2026

---

## 1. Context

FinAnalyse takes a company's annual report PDF (the only supported input format) and produces two artifacts automatically: (1) a professional 19-sheet Excel workbook matching institutional equity research standards, and (2) an AI-written Word report with 7-section investment commentary. The reference output format is a Financial Modeling Report of the kind produced for Reliance Industries — covering historical financials, common-size analysis, 30+ ratios, forecasting, beta regression, WACC, DCF valuation, comparable comps, VaR simulation, and DuPont decomposition.

```
[ Browser / User ]
      │  HTTPS (multipart PDF upload, up to 1 GB via chunked upload)
      ▼
[ FastAPI — service-backend ]  ←──────────────────── [ SQLite DB (outputs/finanalyse.db) ]
      │  BackgroundTask (non-blocking response → job_id returned immediately)
      ▼
[ _run_pipeline_sync() — 5 steps in-process ]
      │
      ├── Step 1: Extract    — pdfplumber Pass 1 → Claude API Pass 2 (if confidence < 0.75)
      ├── Step 2: Commentary — Claude API: 7-section narrative + 6 recommendations
      ├── Step 3: Excel      — xlsxwriter: 19-sheet workbook (non-fatal if fails)
      ├── Step 4: Report     — python-docx: 9-section Word report
      └── Step 5: Next Steps — Claude API: 6 prioritized analyst actions
                                       │
                               [ outputs/<jobId>/ ]
                                   ├── model.xlsx
                                   └── report.docx

[ Frontend polls GET /status/{job_id} → real-time progress updates ]
```

**Scaling path (post-hackathon):** Replace `BackgroundTasks` with Celery + Valkey (ElastiCache `in-hack-cache-01`); replace SQLite with MySQL RDS (`in-hack-mysql`). The pipeline logic is identical — only the dispatch and persistence layers change.

---

## 2. Architecture

### 2.1 Components

| Component | Responsibility | Location in repo |
|-----------|---------------|-----------------|
| FastAPI app | HTTP API: upload, status, download, history, chat, health | `service-backend/src/web/app.py` |
| Job store | Thread-safe in-memory job tracking (UUID → status, progress, files) | `service-backend/src/web/jobs.py` |
| SQLite DB | Long-term persistence of completed analyses; survives restart | `service-backend/src/web/db.py` |
| PDF Parser | Pass 1: pdfplumber local table extraction with per-field confidence scoring | `service-backend/src/agents/pdf_parser.py` |
| Extractor | Orchestrates two-pass extraction; merges results; validates relevance | `service-backend/src/agents/extractor.py` |
| Analyzer | Claude API: 7-section commentary + 6 next-step recommendations | `service-backend/src/agents/analyzer.py` |
| Excel Builder | xlsxwriter: 19-sheet workbook, live formulas, 6 charts | `service-backend/src/agents/excel_builder.py` |
| Charts Builder | 6 embedded professional charts (trends, margins, CF, returns, capital structure) | `service-backend/src/agents/charts_builder.py` |
| Valuation Builder | DCF, DDM, Comparable Comps sheets with formulaic models | `service-backend/src/agents/valuation_builder.py` |
| Report Generator | python-docx: 9-section Word report with tables + AI commentary | `service-backend/src/agents/report_generator.py` |
| Verifier | Post-build cross-checks: BS equation, CF reconciliation, formula errors | `service-backend/src/agents/verifier.py` |
| Formula Registry | Centralised Excel formula generators — never hardcoded in builders | `service-backend/src/utils/formula_registry.py` |
| Excel Styles | xlsxwriter format objects (navy/gold theme, consistent across sheets) | `service-backend/src/utils/excel_styles.py` |
| PDF Handler | PDF load, base64 encode, page count, page-range extraction | `service-backend/src/utils/pdf_handler.py` |
| Settings | All constants, thresholds, paths, valuation defaults | `service-backend/src/config/settings.py` |
| Next.js Frontend | Upload UI, live progress tracker, Analysis Library, chat UI | `service-frontend/src/` |

### 2.2 Boundaries

- **Owns:** full pipeline from PDF upload to .xlsx + .docx; all job state; chat context
- **Calls / reads:** Anthropic Claude API (extraction, commentary, next steps); `yfinance` (2-year weekly price history for beta regression and VaR); peer company data for comps (fixtures for MVP; Screener.in post-hackathon)
- **Does not own:** authentication, live market data feeds, stock brokerage connectivity

---

## 3. Interfaces

### 3.1 APIs

| Method | Path | Request | Response | Errors |
|--------|------|---------|----------|--------|
| POST | `/analyze` | multipart: `files[]` (PDF only), `company_name`, `ticker` (optional), `fiscal_years`, `currency`, `unit` | `{ job_id, status: "queued" }` | 400 bad MIME (non-PDF rejected), 413 too large |
| POST | `/upload-chunk` | multipart: `upload_id`, `chunk_index`, `chunk` | `{ upload_id, received }` | 400 |
| POST | `/upload-finalize/{upload_id}` | — | `{ file_path }` | 404 |
| POST | `/auto-detect` | multipart: `file` | `{ company_name, fiscal_years }` | 400 |
| GET | `/status/{job_id}` | — | `{ status, progress, log[], files?, error? }` | 404 |
| GET | `/download/{job_id}/report` | — | Binary `.docx` stream | 404 |
| GET | `/download/{job_id}/excel` | — | Binary `.xlsx` stream | 404 |
| GET | `/history` | `?status&company&year_from&year_to` | `{ jobs[] }` | — |
| POST | `/chat/{job_id}` | `{ message: string, history: [] }` | `{ reply }` | 404, 400 no commentary |
| POST | `/compare` | `{ job_ids: [id1, id2], message: string, history: [] }` | `{ reply }` | 404 |
| GET | `/health` | — | `{ status: "ok" }` | — |

> **Route note:** For deployment under the hackathon ingress, all routes will be served under the service namespace. A `/api/v1/` prefix wrapper can be added in the FastAPI app router if required by the ingress config.

### 3.2 Background task events

| Trigger | Action | State update |
|---------|--------|-------------|
| POST `/analyze` → job created | `BackgroundTasks.add_task(_run_pipeline_sync, job_id, ...)` | job.status = "processing" |
| Step completion | `job.log(step, message, done=bool)` | job.progress increments |
| Pipeline done | Persist to SQLite; write file paths | job.status = "done" |
| Any unhandled exception | Catch in pipeline; persist error | job.status = "error" |

---

## 4. Data

### 4.1 Core Pydantic Models

**`FinancialData`** — top-level container per company
```
company_name, ticker, exchange, currency, unit
fiscal_years: List[int]
income_statements: List[IncomeStatement]
balance_sheets: List[BalanceSheet]
cash_flow_statements: List[CashFlowStatement]
metadata: ExtractionMetadata
  └─ source_type, overall_confidence, model_used, warnings: List[str]
```

**`IncomeStatement`** (per fiscal year)
```
revenue, other_income, cogs, employee_expenses, gross_profit,
ebitda, depreciation_amortization, ebit, interest_expense,
pbt, tax_expense, pat, eps_basic, eps_diluted,
dividends_per_share, extraction_confidence, extraction_notes
```
All monetary fields: `Optional[float]` — `None` means not reported, not zero.

**`BalanceSheet`** (per fiscal year)
```
current_assets (cash, receivables, inventory, other_current)
non_current_assets (net_fixed_assets, cwip, investments, other_nca)
current_liabilities, non_current_liabilities, total_equity
extraction_confidence, extraction_notes
@model_validator: if |assets − (liabilities + equity)| > 1%, reduce confidence + flag
```

**`CashFlowStatement`** (per fiscal year)
```
cfo, cfi, cff, capex (negative), free_cash_flow, net_change_in_cash
extraction_confidence, extraction_notes
@model_validator: if |net_change − (cfo+cfi+cff)| > 2%, flag in notes
```

### 4.2 Persistence (SQLite — MVP)

**`jobs` table**
```
id TEXT PK, status TEXT, company_name TEXT, ticker TEXT,
currency TEXT, unit TEXT, fiscal_years TEXT (JSON),
error_message TEXT, created_at TEXT, completed_at TEXT
```

**`reports` table**
```
job_id TEXT PK FK→jobs, report_path TEXT, excel_path TEXT,
commentary TEXT (JSON), next_steps TEXT (JSON), created_at TEXT
```

> **Scaling path:** Replace SQLite with MySQL RDS (`in-hack-mysql`, ap-south-1). Schema migration via Alembic. Connection pool via SQLAlchemy 2.0. Thread-local connections → connection pool. No changes to pipeline logic required.

### 4.3 Storage

| Data | Store | Notes |
|------|-------|-------|
| Job metadata + analysis outputs | SQLite `outputs/finanalyse.db` | Permanent; survives restart |
| Uploaded PDF files | `outputs/uploads/` | UUID-named; deleted after pipeline |
| Generated .xlsx | `outputs/excel/` | Served on-demand |
| Generated .docx | `outputs/reports/` | Served on-demand |
| Application logs | `outputs/logs/{YYYYMMDD}.log` | 10 MB max, 5 backups |

---

## 5. Excel Workbook — 19 Sheets

The primary output artifact is an xlsxwriter `.xlsx` workbook. All cells use live Excel formulas unless they are extracted source data. Monetary values use whatever currency/unit the user specified (Crores, Millions, Billions — no conversion). The workbook matches the structure of the reference Reliance Industries Financial Modeling Report, extended with additional sheets from the existing codebase.

| # | Sheet | Contents | Status |
|---|-------|----------|--------|
| 1 | **Cover** | Company profile paragraph, 5-year KPI summary, fiscal years, generated date, disclaimer | Existing |
| 2 | **Income Statement** | Revenue → COGS → Gross Profit → EBITDA → EBIT → EBT → PAT, all years; YoY growth rows; CAGR row | Existing |
| 3 | **Balance Sheet** | Equity + reserves + borrowings + liabilities; fixed assets + investments + current assets; all years; check row (PASS/FAIL) | Existing |
| 4 | **Cash Flow** | CFO / CFI / CFF / FCF; all years; reconciliation check | Existing |
| 5 | **Common Size** | IS as % of Revenue; BS as % of Total Assets/Liabilities — all years | **New** |
| 6 | **Ratio Analysis** | 30+ ratios with full year history; Mean and Median columns; red-highlighted cells for negative inflections | Existing (extended) |
| 7 | **Forecasting** | Weighted moving average projections for Sales, EBITDA, EBT, EPS — 5-year forward; bar charts actuals + estimates | **New** |
| 8 | **Beta Regression** | 2-year weekly returns (stock vs NIFTY 50); Levered raw beta; Blume-adjusted beta (75% raw + 25% market = 1.0) | **New** |
| 9 | **WACC** | Peer comps table (levered/unlevered beta, D/E, tax rate); Cost of Debt (pre/post-tax); CAPM cost of equity; weighted WACC output | **New** |
| 10 | **DCF Valuation** | ROIC + Reinvestment Rate; Intrinsic Growth; 5-year FCFF projection; Terminal Value; EV → Equity Value/Share; 5×5 sensitivity grid (WACC × terminal growth) | Existing |
| 11 | **DDM Valuation** | Dividend growth model intrinsic value (when dividends reported) | Existing |
| 12 | **Comparable Comps** | Peer EV/Revenue, EV/EBITDA, P/E multiples; percentile distribution; implied value per share | Existing |
| 13 | **VaR & Simulation** | Historical VaR at 5%, 1%, 0.5%, 10% confidence; Monte Carlo (10,000 paths); daily returns histogram | **New** |
| 14 | **DuPont Analysis** | 3-factor ROE decomposition (Net Margin × Asset Turnover × Equity Multiplier); ROA decomposition; all years; written summary paragraph | **New** |
| 15 | **Working Capital** | WC trend, DSO, DIO, DPO, cash conversion cycle | Existing |
| 16 | **Valuation Settings** | User-editable input cells: WACC, terminal growth rate, risk-free rate, beta, tax rate — feeds DCF/DDM live | Existing |
| 17 | **Verification** | BS equation check (PASS/FAIL), CF reconciliation check, formula error scan (#DIV/0!, #REF!) | Existing |
| 18 | **Chart Data** | Hidden helper sheet; clean data ranges for all 6 embedded charts | Existing |
| 19 | **Charts** | 6 professional charts: Revenue/EBITDA/PAT trend; Margin trends; CF breakdown; FCF vs PAT; Return metrics; Capital structure | Existing |

**New sheet data sources:**
- **Common Size (5):** Pure Excel formulas referencing IS and BS sheets — no new data needed
- **Forecasting (7):** Pure computation on historical IS data using weighted moving average
- **Beta Regression (8):** `yfinance` fetches 2-year weekly closing prices at job time; stored in sheet as values; OLS beta computed via xlsxwriter formulas + Python pre-computation
- **WACC (9):** Peer beta data from fixture JSON (MVP) or Screener.in (post-hackathon); cost of debt from IS interest expense / total debt
- **VaR & Simulation (13):** Daily returns from `yfinance`; historical VaR computed in Python; Monte Carlo draws written as values; histogram as chart
- **DuPont (14):** Pure cross-sheet formulas referencing IS and BS

---

## 6. Pipeline — 5 Steps

### Step 1 — Extract

```
For each uploaded file (PDF only — non-PDF rejected at upload endpoint):
  └─ Pass 1: pdf_parser.extract_local()
      │   ├─ pdfplumber.extract_tables() (lattice + stream strategies)
      │   ├─ Fuzzy-match rows → canonical line-item names
      │   └─ Assign per-field confidence (1.0 exact / 0.7–0.9 fuzzy / 0.0 missing)
      └─ If aggregate confidence < 0.75:
          ├─ _detect_financial_pages() → Claude identifies relevant pages
          ├─ _call_extraction_api() → Claude tool_use with EXTRACTION_TOOL schema
          ├─ _call_verification_api() → Claude self-checks its own output
          └─ _merge_extractions() → local values win; API fills null fields only

validate_relevance() → raise ValidationError if revenue missing or confidence < 0.25
merge_financial_data() → dedup by confidence across multiple uploaded files
```

### Step 2 — Commentary

```
_build_data_summary() → compact JSON of all extracted metrics + derived ratios
Claude API (claude-sonnet-4-6):
  → 7-section commentary dict (executive_summary, revenue_analysis,
    profitability_analysis, balance_sheet_analysis, cash_flow_analysis,
    key_risks, key_strengths) — ~2–3 paragraphs each, citing specific figures
  → Retry 3× with exponential backoff (tenacity)
```

### Step 3 — Excel (non-fatal)

```
excel_builder.build_workbook(financial_data):
  ├─ Fetch stock price history (yfinance) for beta/VaR sheets if ticker provided
  ├─ Write sheets 1–4 (Cover, IS, BS, CF) — extracted data as values
  ├─ Write sheet 5 (Common Size) — pure formulas referencing IS/BS
  ├─ Write sheet 6 (Ratio Analysis) — cross-sheet formulas; 30+ ratios
  ├─ Write sheet 7 (Forecasting) — weighted moving avg computation + bar charts
  ├─ Write sheets 8–9 (Beta Regression, WACC) — yfinance data + peer comps fixtures
  ├─ valuation_builder.build_valuation_sheets() — DCF (10), DDM (11), Comps (12)
  ├─ Write sheets 13–14 (VaR, DuPont) — Python pre-computed values + formulas
  ├─ Write sheets 15–17 (Working Capital, Settings, Verification)
  ├─ charts_builder.build_charts_sheet() — 6 embedded charts via hidden Chart Data sheet
  └─ Save to outputs/excel/{company}_{timestamp}.xlsx
If exception: log warning; pipeline continues; report generated without Excel reference
```

### Step 4 — Report

```
report_generator.generate_report(financial_data, commentary, excel_path):
  ├─ Cover page (company, ticker, fiscal years, generated date, disclaimer)
  ├─ Executive Summary (commentary["executive_summary"])
  ├─ Revenue & Profitability (commentary + IS table)
  ├─ Balance Sheet Analysis (commentary + BS table)
  ├─ Cash Flow Analysis (commentary + CF table)
  ├─ Key Ratios Dashboard (20+ ratios table)
  ├─ Valuation Summary (references DCF/DDM/Comps in Excel)
  ├─ Key Risks & Strengths (bullet lists from commentary)
  └─ Disclaimer
Styling: Navy (#1F3864) + Gold (#C9A84C), Calibri, 1-inch margins
Save to outputs/reports/{company}_{timestamp}.docx
```

### Step 5 — Next Steps

```
Claude API (claude-sonnet-4-6):
  → Exactly 6 analyst recommendations
  → Each: title, description (citing specific figures), priority (high/medium/low)
  → Enforced: ≥1 high, ≥2 medium, ≥1 low
  → Stored in SQLite reports.next_steps (JSON); surfaced in UI
```

---

## 7. Configuration & Secrets

**Environment variables (from `config/settings.py`):**

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | — | Claude API (required) |
| `MODEL_NAME` | `claude-sonnet-4-6` | Primary model |
| `CONFIDENCE_API_FALLBACK` | `0.75` | Threshold to trigger Claude gap-fill |
| `CONFIDENCE_MIN_ACCEPT` | `0.25` | Below this, reject document entirely |
| `MAX_UPLOAD_SIZE_BYTES` | `52428800` (50 MB) | Per-file upload limit |
| `RISK_FREE_RATE` | `0.067` | WACC / DCF default |
| `EQUITY_RISK_PREMIUM` | `0.055` | CAPM default |
| `TERMINAL_GROWTH_RATE` | `0.04` | DCF terminal value default |
| `CORPORATE_TAX_RATE` | `0.25` | WACC / ROIC computation |
| `MOCK_EXTRACTION` | `false` | If `true`, bypass Claude API; return Infosys FY2024 fixtures |

**Secrets injection:** `service-backend/config/secrets.json` maps env var names → GitHub Secret names → Kubernetes pod env vars. Never committed to source.

---

## 8. Deployment & Operations

- **How it runs:** Single Docker container (Python 3.11-slim) with FastAPI via `uvicorn` on port 8000; all output directories auto-created on startup
- **Dockerfile:** `service-backend/helm/Dockerfile`
- **Health:** `GET /health` returns `{ status: "ok" }`; used as K8s liveness + readiness probe
- **Scaling:** Single replica for hackathon demo (BackgroundTasks handles 1–3 concurrent jobs). Post-hackathon: split into API + Celery worker deployments; HPA on queue depth
- **Namespace:** `team-ppo-nahi-milega`
- **helmReleaseName:** `finanalyse-backend` / `finanalyse-frontend`
- **Rollback:** `helm rollback finanalyse-backend -n team-ppo-nahi-milega`

---

## 9. Failure Modes & Mitigations

| Failure | Impact | Mitigation |
|---------|--------|------------|
| Claude API timeout / rate limit | Gap-fill or commentary fails | Retry 3× with exponential backoff (2–10s, tenacity); fall back to low-confidence extraction with UI warning |
| PDF confidence < 0.25 after both passes | Document rejected | `ValidationError` surfaced in UI; user prompted to check document or use JSON input |
| Balance sheet equation fails | Integrity warning in model | Flagged as WARNING (not error); PASS/FAIL shown in Verification sheet; analysis proceeds with caveat |
| Stock ticker not found / no yfinance data | Beta, VaR sheets empty | Sheets rendered with N/A placeholder; WACC uses user-input beta from Settings sheet |
| Excel generation throws exception | No .xlsx file | Non-fatal — Word report still generated; download card shows "Excel unavailable" |
| App restart mid-job | In-memory job state lost | Job will not resume; user re-uploads. Post-hackathon fix: Celery + persistent queue |
| Demo PDF parsing failure | Live demo broken | `MOCK_EXTRACTION=true` returns validated Infosys FY2024 fixture without any API call |

---

## 10. Trade-offs & Deferred Work

| Simplification (MVP) | What we'd do post-hackathon |
|----------------------|----------------------------|
| SQLite single-file DB | MySQL RDS (in-hack-mysql); SQLAlchemy 2.0 + Alembic |
| FastAPI BackgroundTasks (in-process) | Celery + Valkey (ElastiCache in-hack-cache-01); separate worker deployment |
| Output files on container local volume | S3 with presigned download URLs; files survive pod restart |
| yfinance for stock data | NSE official API / Screener.in for production-grade data |
| Peer comps data from hardcoded fixtures | Live Screener.in scraper or user-provided peer list |
| Single-job chatbot only (`/chat/{job_id}`) | Comparison chat (`/compare`) with structured dual-company context |
| No user authentication | JWT auth + per-user analysis library |
| Max 2 companies in comparison | RAG pipeline for N>2 |
| PDF-only input | XBRL (.xml) support via `arelle` for SEC-filed companies; bypasses PDF pass for near-perfect accuracy |
| No PDF export of Word report | `libreoffice --headless` PDF conversion |
