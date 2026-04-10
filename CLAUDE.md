# CLAUDE.md - FinAnalyse Project Context

> This file is the canonical context document for Claude Code sessions on this project.
> Read this before doing anything. Treat it as the source of truth for architectural decisions,
> constraints, and conventions. Update it whenever a significant decision is made.

---

## Project Identity

| Field | Value |
|-------|-------|
| Product name | FinAnalyse |
| Hackathon | Nurix hack-apr-26 |
| Stage branch | `stage` (default - all work goes here) |
| Repo naming | Must follow `nurixlabs/team-<team-name>` pattern |
| Judge review paths | `docs/PRD.md`, `docs/LLD.md` |
| Reference output | `reference_docs/` - Reliance Industries Financial Modeling Report (PDF) + Colgate Excel model |
| UI design reference | `web-design/` - source of truth for design language (colors, fonts, animations) |

---

## Deadlines (HARD)

| Artifact | File | Deadline | Status |
|----------|------|----------|--------|
| PRD | `docs/PRD.md` | 9 Apr 2026, 5:00 PM IST | Done |
| LLD | `docs/LLD.md` | 10 Apr 2026, 12:00 AM IST | Done |
| Code | `service-*/` | 13 Apr 2026, 12:00 AM IST | In progress |

**All pushes must go to the `stage` branch.**

---

## Product Vision (Summary)

FinAnalyse takes a company's annual report PDF and automatically produces:
1. A **19-sheet Excel workbook** - the primary output artifact - with live formulas, charts, DCF, WACC, beta regression, VaR simulation, DuPont, and more; matching institutional equity research standards
2. A **Word report** - AI-written investment commentary across 7 sections
3. **6 prioritized analyst recommendations** - specific, figure-cited next steps
4. A **contextual chatbot** - grounded in the completed analysis; supports single-company Q&A and two-company comparison
5. **Google login** - per-user report collections; JWT auth

Source of truth for product vision: `idea.md` in project root.
Reference output format: `reference_docs/1757434374099.pdf` (Reliance Financial Modeling Report).

---

## Repo Structure

```
Team-PPO-nahi-milega/
├── docs/
│   ├── PRD.md                      <- judge-reviewed
│   └── LLD.md                      <- judge-reviewed
├── service-backend/                <- Python FastAPI + pipeline
│   ├── helm/
│   │   ├── nurix-service/          <- Helm chart (do not delete)
│   │   └── Dockerfile              <- Python 3.11-slim custom Dockerfile
│   ├── config/
│   │   ├── deploy.yaml             <- helmReleaseName: finanalyse-backend
│   │   └── secrets.json            <- ANTHROPIC_API_KEY, GOOGLE_*, JWT_SECRET
│   └── src/                        <- application source
├── service-frontend/               <- Next.js 14 UI
│   ├── helm/
│   │   ├── nurix-service/          <- Helm chart (do not delete)
│   │   └── nextjs-service.Dockerfile
│   ├── config/
│   │   ├── deploy.yaml             <- helmReleaseName: finanalyse-frontend
│   │   └── secrets.json            <- NEXT_PUBLIC_API_URL, NEXT_PUBLIC_FRONTEND_URL
│   ├── public/                     <- logo assets (logo_cropped.png, logo.png)
│   ├── src/                        <- Next.js App Router source
│   ├── package.json                <- at service-frontend/ root (Dockerfile expects it here)
│   ├── next.config.js              <- output: 'standalone' (required by Dockerfile)
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── postcss.config.js
├── web-design/                     <- UI reference (React prototype - do not deploy)
├── reference_docs/                 <- Reliance PDF + Colgate Excel
├── .github/
│   └── workflows/
│       └── deploy.yml              <- pipeline stub, DO NOT EDIT
└── README.md
```

**Critical rules:**
- Service folders MUST be named `service-<something>` - pipeline only triggers on `service-*/**`
- Do not delete `helm/` directories inside service folders
- `docs/PRD.md` and `docs/LLD.md` must not be renamed or moved
- Do not create a top-level `backend/` or `frontend/` folder
- Do not push to any branch other than `stage`
- Do not edit `.github/workflows/deploy.yml`

---

## Infrastructure (hack-apr-26 AWS Account)

| Resource | Value |
|----------|-------|
| AWS Account | hack-apr-26 (632421564644) |
| Region | ap-south-1 (Mumbai) |
| EKS Cluster | in-hack-eks-01 |
| ECR Registry | 632421564644.dkr.ecr.ap-south-1.amazonaws.com |
| ECR path pattern | `<team-repo>/<service-folder>/` |
| RDS | in-hack-mysql (MySQL 8.0, private subnet, single-AZ) |
| ElastiCache | in-hack-cache-01 (Valkey 8.1, multi-AZ capable) |
| Namespace | `team-ppo-nahi-milega` |
| helmReleaseName (backend) | `finanalyse-backend` |
| helmReleaseName (frontend) | `finanalyse-frontend` |
| Backend URL | `https://finanalyse-backend-in.hack.nurixlabs.tech` |
| Frontend URL | `https://finanalyse-frontend-in.hack.nurixlabs.tech` |

**Networking:** Private subnets for EKS nodes and data stores. VPC: 172.19.0.0/16.

CI/CD flow:
```
push to stage (service-*/** changed)
  -> .github/workflows/deploy.yml (stub, do not touch)
    -> hack-central-apr-26/deploy.yml
      -> detect changed service-* folders
        -> parallel per service:
          -> docker build -> push to ECR
          -> helm upgrade --install -> EKS namespace
```

---

## Technology Stack

### Backend (`service-backend/src/`)

| Layer | Choice | Notes |
|-------|--------|-------|
| Runtime | Python 3.11 | Superior PDF/Excel ecosystem |
| Framework | FastAPI | Async, Pydantic v2, BackgroundTasks |
| Persistence | SQLite WAL (`outputs/finanalyse.db`) | Zero infra; thread-safe; survives restart |
| PDF parsing | `pdfplumber` + Claude API | Two-pass; local first, AI gap-fill if confidence < 0.75 |
| Excel generation | `xlsxwriter` | 19-sheet workbook with live formulas |
| Word generation | `python-docx` | 7-section AI commentary report |
| AI SDK | `anthropic` + `tenacity` | `claude-sonnet-4-6`; retry 3x with backoff |
| Stock data | `yfinance` | 2-year weekly/daily prices for Beta and VaR sheets |
| Auth | `python-jose[cryptography]` + `httpx` | Google OAuth2 + JWT (HS256, 30-day expiry) |
| Rate limiting | `slowapi` | 10 `/analyze` requests/minute per IP |
| CORS | FastAPI `CORSMiddleware` | Origins from `CORS_ORIGINS` env var |
| Container | Python 3.11-slim | `uvicorn web.app:app` on port 8000 |

### Frontend (`service-frontend/`)

| Layer | Choice | Notes |
|-------|--------|-------|
| Framework | Next.js 14 (App Router) | `output: 'standalone'` for Docker |
| Language | TypeScript | Strict mode |
| Styling | Tailwind CSS + custom CSS | Design system in `app/globals.css` |
| Icons | lucide-react | Same icons as web-design reference |
| Auth | JWT in localStorage | Key: `finanalyse_token`; sent as `Authorization: Bearer` |
| API | `lib/api.ts` helpers | `NEXT_PUBLIC_API_URL` env var |
| Container | Node 22 Alpine (standalone) | Yarn build; port 3000 |

### Frontend Design System (from `web-design/` reference - match exactly)

- **Background:** `#070a0f` base; floating radial gradient orbs; 64px grid overlay; animated particles
- **Fonts:** Space Grotesk (headlines/labels), DM Sans (body), JetBrains Mono (code)
- **Primary accent:** Electric Blue `#3B82F6`; secondary: cyan `#06b6d4`, purple `#8b5cf6`, orange `#f97316`, green `#10b981`
- **Components:** Glassmorphism cards (`backdrop-filter: blur(12-24px)`); sticky header with blur
- **Animations:** orb-float, particle-float, fade-in, shimmer, pulse-ring, scroll-triggered `.animate-on-scroll`
- **RULE: Never use the n-dash character (--) in any frontend file.** Use a regular hyphen (-) instead.

### AI / LLM

- **Primary model:** `claude-sonnet-4-6`
- **Key name:** `ANTHROPIC_API_KEY` (injected via secrets.json -> GitHub Secrets -> pod env)
- **Extraction:** tool-use / structured JSON via `EXTRACTION_TOOL` schema
- **Commentary:** freeform; 7 sections; figures cited inline
- **Chatbot:** commentary JSON injected as system prompt; 20-pair history cap

---

## Pipeline Architecture (5 Steps)

Runs as a FastAPI `BackgroundTask`; `job_id` returned immediately; frontend polls `/status/{job_id}`.

```
1. Extract    - pdfplumber (Pass 1) -> confidence scored per field
               -> if aggregate confidence < 0.75 OR no revenue found: Claude API tool-use (Pass 2)
               -> merge: iterate over UNION of local+API fiscal years; local values win; API fills nulls
               -> _merge_stmt uses Pydantic model_fields (NOT dataclasses.fields - these are Pydantic models)
               -> validate relevance (reject if confidence < 0.25 or no revenue)

2. Commentary - Claude API: 7-section narrative dict
               (executive_summary, revenue_analysis, profitability_analysis,
                balance_sheet_analysis, cash_flow_analysis, key_risks, key_strengths)

3. Excel      - xlsxwriter: 19-sheet workbook (non-fatal - Word report still generates if Excel fails)
               -> yfinance fetch for Beta/VaR sheets (if ticker provided)

4. Report     - python-docx: Word report (cover, 7 commentary sections, ratios table, disclaimer)

5. Next Steps - Claude API: 6 prioritized analyst recommendations
               (>=1 high, >=2 medium, >=1 low; each cites specific figures)
```

Commentary JSON + next steps JSON persisted to SQLite at completion - powers chatbot and comparison chat permanently.

---

## Excel Workbook - 19 Sheets (ALL COMPLETE)

| # | Sheet | Source file |
|---|-------|-------------|
| 1 | Cover - company profile, KPI summary | `excel_builder.py` |
| 2 | Income Statement - all years, YoY growth, CAGR | `excel_builder.py` |
| 3 | Balance Sheet - all years, PASS/FAIL check | `excel_builder.py` |
| 4 | Cash Flow - CFO/CFI/CFF/FCF, reconciliation | `excel_builder.py` |
| 5 | Common Size - IS as % of Revenue; BS as % of Total Assets | `new_sheets_builder.py` |
| 6 | Ratio Analysis - 30+ ratios, Mean/Median, red-flag highlights | `excel_builder.py` |
| 7 | Forecasting - WMA 5-year projection (Revenue, EBITDA, EBT, EPS) | `new_sheets_builder.py` |
| 8 | Beta Regression - 2-year weekly vs NIFTY 50; Blume-adjusted beta | `new_sheets_builder.py` |
| 9 | WACC - CAPM cost of equity, cost of debt, capital structure, sanity checks | `valuation_builder.py` |
| 10 | DCF Valuation - FCFF model, terminal value, sensitivity grid | `valuation_builder.py` |
| 11 | DDM Valuation - dividend discount model | `valuation_builder.py` |
| 12 | Comparable Comps - EV/Revenue, EV/EBITDA, P/E vs peers | `valuation_builder.py` |
| 13 | VaR & Simulation - historical VaR (4 levels); Monte Carlo 10k paths | `new_sheets_builder.py` |
| 14 | DuPont Analysis - 3-factor ROE decomposition; Mean/Median columns | `new_sheets_builder.py` |
| 15 | Working Capital - WC trend, DSO, DIO, DPO, cash conversion cycle | `excel_builder.py` |
| 16 | Settings - user-editable Rf, ERP, beta, tax rate, terminal growth | `excel_builder.py` |
| 17 | Verification - BS equation, CF reconciliation, PAT consistency | `excel_builder.py` |
| 18 | Chart Data - hidden helper ranges for 6 embedded charts | `charts_builder.py` |
| 19 | Charts - 6 embedded charts (revenue trend, margins, CF, FCF, returns) | `charts_builder.py` |

**Convention:** All formulas via `formula_registry.py`. All formatting via `excel_styles.py` StyleBook. Never hardcode cell references or format strings in sheet builders.

---

## API Routes (Backend)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/analyze` | Optional | Start pipeline; rate-limited 10/min/IP |
| POST | `/upload-chunk` | - | Chunked upload (large PDFs up to 1 GB) |
| POST | `/upload-finalize/{upload_id}` | - | Assemble chunks |
| POST | `/auto-detect` | - | Detect company name + fiscal years from PDF |
| GET | `/status/{job_id}` | - | Poll progress; falls back to SQLite on pod restart |
| GET | `/download/{job_id}/excel` | - | Download `.xlsx` |
| GET | `/download/{job_id}/report` | - | Download `.docx` |
| GET | `/history` | Optional | List analyses; filters by user when JWT present |
| GET | `/history/{job_id}` | - | Full detail for one analysis |
| DELETE | `/history/{job_id}` | - | Delete a job record |
| POST | `/chat/{job_id}` | - | Single-company chatbot |
| POST | `/compare` | - | Two-company comparison chat (`{job_ids:[id1,id2], message, history}`) |
| GET | `/auth/google` | - | Redirect to Google OAuth consent page |
| GET | `/auth/callback` | - | Exchange code -> upsert user -> issue JWT -> redirect to frontend |
| GET | `/auth/me` | Required | Return current user profile |
| GET | `/health` | - | Liveness/readiness probe |

---

## Auth Architecture

**Backend (`web/auth.py`):**
- Google OAuth2 via `httpx` (no heavy OAuth library)
- JWT issued with `python-jose` (HS256, 30-day expiry)
- `JWT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` from env
- FastAPI dependencies: `get_current_user` (raises 401), `get_optional_user` (returns None)

**Frontend (`lib/auth.ts`):**
- Token stored as `finanalyse_token` in localStorage
- `handleAuthCallback()` reads `?token=` from URL after Google redirect, stores it, strips from URL
- All API calls in `lib/api.ts` add `Authorization: Bearer <token>` when token present

**Flow:**
1. User clicks "Log In" or "Sign Up" -> frontend redirects to `${API_URL}/auth/google`
2. Backend redirects to Google consent
3. Google redirects to `${API_URL}/auth/callback?code=...`
4. Backend exchanges code, upserts user in `users` table, issues JWT
5. Backend redirects to `${FRONTEND_URL}?token=<jwt>`
6. Frontend reads token, stores in localStorage, strips from URL

---

## Database Schema (SQLite)

```sql
users  (id TEXT PK, google_id TEXT UNIQUE, email, name, picture, created_at, last_login)
jobs   (id TEXT PK, status, company_name, currency, unit, fiscal_years JSON,
        error, created_at, finished_at, user_id FK->users)
reports (job_id TEXT PK FK->jobs CASCADE, report_path, excel_path,
         commentary JSON, next_steps JSON, metrics JSON)
```

- WAL mode enabled; parameterized queries only
- `recover_stuck_jobs()` called on startup - marks queued/running jobs as error after pod restart
- `/history` filters by `user_id` when authenticated; returns all jobs when unauthenticated (demo mode)

---

## Backend Source Layout (`service-backend/src/`)

```
agents/
  extractor.py          - two-pass extraction orchestrator
  pdf_parser.py         - pdfplumber local extraction (Pass 1)
  analyzer.py           - Claude API commentary + next steps
  excel_builder.py      - 19-sheet workbook orchestrator + sheets 1-4, 6, 15-19
  new_sheets_builder.py - sheets 5, 7, 8, 13, 14 (Common Size, Forecasting, Beta, VaR, DuPont)
  valuation_builder.py  - sheets 9-12 (WACC, DCF, DDM, Comps)
  charts_builder.py     - sheets 18-19 (Chart Data + Charts)
  report_generator.py   - python-docx Word report
  verifier.py           - post-build cross-checks

utils/
  formula_registry.py   - all Excel formulas (never hardcode in builders)
  excel_styles.py       - StyleBook: navy/gold theme, all format objects
  pdf_handler.py        - PDF load, base64 encode, page extraction
  logger.py             - rotating file log to outputs/logs/

web/
  app.py                - FastAPI routes + BackgroundTasks pipeline + CORS + rate limiting
  auth.py               - Google OAuth2 + JWT issue/verify + FastAPI dependencies
  jobs.py               - in-memory thread-safe job store
  db.py                 - SQLite persistence (users + jobs + reports tables)

config/settings.py      - all constants, thresholds, paths, valuation defaults
schemas/extraction_tool_schema.py - Claude tool-use JSON schema
prompts/                - extraction_system.txt, extraction_user.txt, verification_system.txt
models/                 - FinancialData, IncomeStatement, BalanceSheet, CashFlowStatement
errors.py               - typed exception hierarchy (FinAnalysisError subclasses)
```

---

## Frontend Source Layout (`service-frontend/src/`)

```
app/
  globals.css           - full design system (CSS variables, animations, utilities)
  layout.tsx            - root layout with fonts + animated background particles/shapes
  page.tsx              - landing page (hero, how it works, features, stats, CTA)
  analyse/page.tsx      - analysis page (upload sidebar, progress, downloads, chat widget)
  reports/page.tsx      - reports history (table, filters, download/delete actions)
  api/health/route.ts   - GET /api/health -> {status:'ok'}

lib/
  api.ts                - API helpers; NEXT_PUBLIC_API_URL; auth headers
  auth.ts               - token storage, handleAuthCallback(), decodeTokenPayload()
```

---

## GitHub Secrets Required

Register with: `gh secret set <NAME> --repo nurixlabs/team-ppo-nahi-milega --body '<value>'`

| Secret name | Used by | Purpose |
|-------------|---------|---------|
| `anthropic_api_key` | backend | Claude API |
| `google_client_id` | backend | Google OAuth app client ID |
| `google_client_secret` | backend | Google OAuth app client secret |
| `google_redirect_uri` | backend | `https://finanalyse-backend-in.hack.nurixlabs.tech/auth/callback` |
| `jwt_secret` | backend | Random 256-bit string for JWT signing |
| `next_public_api_url` | frontend | `https://finanalyse-backend-in.hack.nurixlabs.tech` |
| `next_public_frontend_url` | frontend | `https://finanalyse-frontend-in.hack.nurixlabs.tech` |

---

## Security

- All secrets via `config/secrets.json` -> GitHub Secrets -> pod env; never in source code
- File upload: PDF/JSON only; 50 MB direct limit; 1 GB chunked limit; UUID-named temp files
- SQLite: parameterized queries only; no raw SQL string formatting
- Rate limiting: 10 `/analyze` requests/minute per IP (slowapi)
- CORS: origins from `CORS_ORIGINS` env var; defaults include localhost + production frontend URL
- JWT: HS256, 30-day expiry; stored in localStorage (acceptable for hackathon scope)

---

## Observability

- Per-step progress log: `job.log(step, message, done=bool)` - surfaced via `/status/{job_id}`
- Rotating log file: `outputs/logs/{YYYYMMDD}.log` (10 MB max, 5 backups)
- Health endpoint: `GET /health` -> `{status:"ok"}` (backend) and `GET /api/health` (frontend)
- Startup recovery: stuck jobs automatically marked as error on pod restart

---

## Deployment

- Each service deploys independently on push to `stage` when `service-*/**` files change
- Backend: Python 3.11-slim; `uvicorn web.app:app` port 8000; `outputs/` auto-created on startup
- Frontend: Node 22 Alpine standalone build; `node server.js` port 3000
- Rollback backend: `helm rollback finanalyse-backend -n team-ppo-nahi-milega`
- Rollback frontend: `helm rollback finanalyse-frontend -n team-ppo-nahi-milega`

---

## Phase Completion Status

- [x] Phase 1 - Product analysis complete (`idea.md`)
- [x] Phase 2 - PRD v1.2 complete (`docs/PRD.md`)
- [x] Phase 3 - LLD complete (`docs/LLD.md`)
- [x] Phase 4 - Repo scaffolding (`service-backend/`, `service-frontend/`)
- [x] Phase 5 - Backend implementation:
  - [x] All 19 Excel sheets built and wired
  - [x] 5-step pipeline (extract, commentary, Excel, report, next steps)
  - [x] `/compare` two-company comparison chat
  - [x] Google OAuth2 + JWT auth (`web/auth.py`)
  - [x] SQLite users table; per-user job filtering
  - [x] CORS middleware + slowapi rate limiting
  - [x] `/status` SQLite fallback for pod-restart resilience
  - [x] Startup recovery for stuck jobs
- [x] Phase 6 - Frontend implementation:
  - [x] Landing page with scroll animations and Google login
  - [x] Analysis page with upload, progress polling, downloads, chat widget
  - [x] Reports history page with filters and actions
  - [x] JWT auth flow (handleAuthCallback, localStorage, Bearer header)
  - [x] Auto-detect on upload: PDF uploaded -> /auto-detect (first 5 pages) -> fills company name + fiscal years
  - [x] Independent scroll panes on analyse page (sidebar + main content scroll separately)
  - [x] Bug fixes: spinner animation, Image hydration, error field name alignment (error vs error_message)
  - [x] Vision fallback (Pass 3): pymupdf renders IS-keyword pages as JPEG -> Claude vision API when document-API gap-fill returns no revenue
  - [x] PipelineProgress redesigned: 5 numbered steps shown from start; dotted vertical connector acts as progress bar; active step glows white; done steps turn green
  - [x] Chat widget: react-markdown renders AI responses (bold, lists, headings); panel height increased to 700px; width 400px
  - [x] Google OAuth local dev: real credentials in service-backend/src/.env; backend restarts load them; hero badge dot blink removed
  - [x] Dynamic stat cards: `_compute_metrics` in `app.py` extracts revenue, gross margin %, FCF, D/E from FinancialData after extraction; stored on `job.metrics`; returned in `/status` response; `AnalysisHeader` uses real values with currency/unit-aware formatting; falls back to "--" when data is absent
- [ ] Phase 7 - Deploy and verify (push to stage, smoke test on EKS)
- [ ] Phase 8 - Tests (deferred; demo manually with Reliance FY2024 + Infosys FY2024)

---

## Known Bugs Fixed (do not reintroduce)

- **`_merge_stmt` must use `type(stmt).model_fields`** - these are Pydantic v2 `BaseModel` instances; `dataclasses.fields()` will throw `TypeError` on them. This was the root cause of "yielded no revenue data".
- **`_merge_extractions` must iterate over union of local+API years** - not just local years. Claude may find IS data for years pdfplumber didn't detect.
- **Gap-fill trigger**: `needs_gap_fill = conf < CONFIDENCE_API_FALLBACK or not has_revenue` - must include `not has_revenue` condition so gap-fill runs even when pdfplumber confidence is high but revenue is missing.
- **CSS spinner**: Never use `transform: translateY(-50%)` on a spinning element - `@keyframes spin` uses `transform: rotate()` and overwrites it. Use `top: calc(50% - Npx)` instead.
- **Next.js Image**: Do not set CSS `width`/`height` on `<Image>` when `width`/`height` props are already set - causes hydration mismatch. Use only `style={{ objectFit: 'contain' }}`.
- **Vision fallback pdfplumber scan**: `_call_extraction_api_images` uses `pdfplumber.open()` to find IS-keyword pages. These keywords (`revenue`, `total income`, `net profit`, etc.) are defined in `_IS_KEYWORDS` frozenset in `extractor.py`. Do not remove this set.
- **Google OAuth `redirect_uri_mismatch`**: The redirect URI in `.env` (`GOOGLE_REDIRECT_URI`) must match exactly what is registered in Google Cloud Console under the OAuth 2.0 Client ID's "Authorised redirect URIs". For local dev: `http://localhost:8000/auth/callback`. Backend must be restarted after any `.env` change (env vars are loaded at module import time).
- **PAT must NOT use "Total Comprehensive Income"**: Under Ind AS/IFRS, TCI = PAT + OCI. Using TCI as PAT overstates earnings by 6-11% (exactly the OCI amount). `pdf_parser.py` pattern list and `extraction_system.txt` now explicitly exclude TCI from PAT matching.
- **Total Income formula was `=B4+B4` (wrong)**: `total_income()` in `formula_registry.py` had signature `(rev_col, other_col, row)` but was called as `(cx, cx, IS["other_income"])` — both cols the same, row pointing to Other Income row. Generated `=OtherIncome+OtherIncome`. Fixed to `total_income(col, rev_row, other_row)` returning `={col}{rev_row}+{col}{other_row}`. Call updated to `total_income(cx, IS["revenue"], IS["other_income"])`.
- **EBITDA fallback wrote None**: The `elif` branch in `excel_builder.py` called `val(IS["ebitda"], c, stmt.ebitda)` where `stmt.ebitda` is already `None`. Now writes live formula `=IFERROR(PBT+Interest+DA,"")` as fallback.
- **Lease liabilities excluded from debt**: Companies with no traditional borrowings (TCS, Infosys) show zero debt because Ind AS 116 lease liabilities were extracted but ignored. `pdf_parser.py` now merges `lease_nc` into `long_term_debt` and `lease_curr` into `short_term_borrowings` before returning.
- **COGS patterns missed IT company cost structure**: Pattern `r"cost of materials consumed"` matched tiny software licence costs (~₹1,462 Cr) instead of actual cost of revenue (~₹93,276 Cr). Added `r"cost of revenue"`, `r"cost of services"`, `r"subcontracting"` at the top of the COGS pattern list.
- **Shares outstanding unit ambiguity**: Reports express shares in lakhs (e.g., 37,401 lakh = 3,740 Mn). Extraction system prompt now requires normalization to millions with explicit division rule.
- **Reports list only shows user-linked jobs**: `list_jobs` filtered strictly by `user_id = ?`, hiding analyses run before login (user_id IS NULL). Fixed to `(user_id = ? OR user_id IS NULL)` so unclaimed jobs are always visible.
- **Unknown Company in reports**: `upsert_job` SQL overwrote `company_name` with `""` on every update. Fixed with `CASE WHEN excluded.company_name != '' THEN ... ELSE jobs.company_name END` for company_name/currency/unit/fiscal_years. `_fail_job` now passes `company_name=job.company_name` to preserve the name on failure.
- **Eye button shows blank page**: Used `pollStatus` which could fail silently (`.catch(() => setPageState('idle'))`). Now uses `getJobDetail` (calls `/history/{job_id}`) which always reads from SQLite and returns complete data. On error shows an explicit message instead of blank. Also: `deleteJob` was calling wrong URL `/jobs/` instead of `/history/` - fixed. Status SQLite fallback now includes `currency`, `unit`, `fiscal_years`.
- **`/history` returns `id` not `job_id`**: The `list_jobs` SQL returned `j.id` but the frontend `HistoryEntry` interface expected `job_id`. Every `report.job_id` was `undefined` at runtime, making the eye link go to `/analyse?job_id=undefined` (404), download links broken, and deletes broken. Fixed by adding `j.id AS job_id` to the SQL in both `list_jobs` and `get_job_detail`.
- **Stat cards blank when loaded from history**: Metrics (revenue, gross margin, FCF, D/E) were computed in memory only and returned as `null` from `/history/{job_id}`. Fixed by adding a `metrics TEXT` column to the `reports` table, persisting `job.metrics` via `upsert_report(metrics=job.metrics)`, parsing it in `get_job_detail`, and mapping it through `getJobDetail` in api.ts.
- **Form field names mismatched**: Frontend sent `company_name`, `fiscal_years`, `units` in FormData but backend reads `company`, `years`, `unit`. The company name hint was silently discarded — the extractor never received it, and if it couldn't auto-detect from the PDF the name stayed empty forever. Fixed: `fd.append('company', ...)`, `fd.append('years', ...)`, `fd.append('unit', ...)`.

---

## Google OAuth Local Dev Setup

1. Go to [Google Cloud Console > APIs & Services > Credentials](https://console.cloud.google.com/apis/credentials)
2. Click the OAuth 2.0 Client ID (`503986173072-...`)
3. Under **Authorised redirect URIs**, add: `http://localhost:8000/auth/callback`
4. Save - takes effect immediately (no Google propagation delay for localhost)
5. Credentials are already in `service-backend/src/.env` (gitignored)
6. Backend must be running from `service-backend/src/` with conda env `venv`

---

## Local Development

```bash
# Backend
cd service-backend/src
uvicorn web.app:app --reload --port 8000

# Frontend
cd service-frontend
yarn dev   # or npm run dev
```

- Backend must be run from `service-backend/src/` (not `service-backend/`) - module imports are relative to `src/`
- Frontend `.env.local` must be at `service-frontend/.env.local` with `NEXT_PUBLIC_API_URL=http://localhost:8000`
- If port 8000 is in use: `lsof -ti:8000 | xargs kill -9`

---

## What Claude Should NOT Do

- Do not rename or move `docs/`, `docs/PRD.md`, or `docs/LLD.md`
- Do not create a top-level `backend/` or `frontend/` folder
- Do not push to any branch other than `stage`
- Do not edit `.github/workflows/deploy.yml`
- Do not put secrets in source code
- Do not use the n-dash character (--) anywhere in frontend files - use hyphen (-) instead
- Do not hardcode Excel cell references or formula strings - use `formula_registry.py`
- Do not hardcode Excel formatting - use `excel_styles.py` StyleBook
- Do not add features beyond what is needed for a convincing demo
- Do not use `dataclasses.fields()` on Pydantic models - use `model_fields` instead
