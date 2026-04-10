# CLAUDE.md — FinAnalyse Project Context

> This file is the canonical context document for Claude Code sessions on this project.
> Read this before doing anything. Treat it as the source of truth for architectural decisions,
> constraints, and conventions. Update it whenever a significant decision is made.

---

## Project Identity

| Field | Value |
|-------|-------|
| Product name | FinAnalyse |
| Hackathon | Nurix hack-apr-26 |
| Stage branch | `stage` (default — all work goes here) |
| Repo naming | Must follow `nurixlabs/team-<team-name>` pattern |
| Judge review paths | `docs/PRD.md`, `docs/LLD.md` |
| Reference output | `reference_docs/` — Reliance Industries Financial Modeling Report (PDF) + Colgate Excel model |

---

## Deadlines (HARD)

| Artifact | File | Deadline | Status |
|----------|------|----------|--------|
| PRD | `docs/PRD.md` | 9 Apr 2026, 5:00 PM IST | ✅ Done |
| LLD | `docs/LLD.md` | 10 Apr 2026, 12:00 AM IST | ✅ Done |
| Code | `service-*/` | 13 Apr 2026, 12:00 AM IST | In progress |

**All pushes must go to the `stage` branch.**

---

## Product Vision (Summary)

FinAnalyse takes a company's annual report PDF and automatically produces:
1. A **19-sheet Excel workbook** — the primary output artifact — with live formulas, charts, DCF, WACC, beta regression, VaR simulation, DuPont, and more; matching institutional equity research standards
2. A **9-section Word report** — AI-written investment commentary grounded in the extracted figures
3. **6 prioritized analyst recommendations** — specific, figure-cited next steps
4. A **contextual chatbot** — grounded in the completed analysis; supports single-company Q&A and two-company comparison

Source of truth for product vision: `idea.md` in project root.
Reference output format: `reference_docs/1757434374099.pdf` (Reliance Financial Modeling Report).

---

## Repo Structure (Mandated by Hackathon)

```
Team-PPO-nahi-milega/
├── docs/
│   ├── PRD.md                    ← judge-reviewed ✅
│   └── LLD.md                    ← judge-reviewed ✅
├── service-backend/              ← Python FastAPI + pipeline (custom Dockerfile)
│   ├── helm/
│   │   ├── nurix-service/        ← Helm chart (do not delete)
│   │   └── Dockerfile            ← Python 3.11-slim custom Dockerfile
│   ├── config/
│   │   ├── deploy.yaml           ← helmReleaseName, namespace, dockerfilePath
│   │   └── secrets.json          ← maps env var names → GitHub secret names
│   └── src/                      ← application source (see codebase section)
├── service-frontend/             ← Next.js 14 UI (nextjs-service.Dockerfile)
│   ├── helm/
│   │   ├── nurix-service/
│   │   └── nextjs-service.Dockerfile
│   ├── config/
│   │   ├── deploy.yaml
│   │   └── secrets.json
│   └── src/
├── Nurix-2026-Hackathon .../     ← Working codebase (Python) — source of truth for implementation
├── reference_docs/               ← Reliance PDF + Colgate Excel — target output format
├── .github/
│   └── workflows/
│       └── deploy.yml            ← pipeline stub, DO NOT EDIT
└── README.md
```

**Critical rules:**
- Service folders MUST be named `service-<something>` — pipeline only triggers on `service-*/**`
- Do not delete `helm/` directories inside service folders
- `docs/PRD.md` and `docs/LLD.md` must not be renamed or moved
- Do not create a top-level `backend/` or `frontend/` folder

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

**Networking:** Private subnets for EKS nodes and data stores. VPC: 172.19.0.0/16.

CI/CD flow:
```
push to stage (service-*/** changed)
  → .github/workflows/deploy.yml (stub, do not touch)
    → hack-central-apr-26/deploy.yml
      → detect changed service-* folders
        → parallel per service:
          → docker build → push to ECR
          → helm upgrade --install → EKS namespace
```

---

## Technology Stack

### Backend (`service-backend/`)

| Layer | Choice | Notes |
|-------|--------|-------|
| Runtime | Python 3.11 | Superior PDF/Excel ecosystem vs Node.js |
| Framework | FastAPI | Async, Pydantic v2, auto OpenAPI docs |
| Async jobs (MVP) | FastAPI `BackgroundTasks` | In-process; zero infra; sufficient for 1–3 demo jobs |
| Async jobs (scale) | Celery + Valkey (ElastiCache `in-hack-cache-01`) | Post-hackathon scaling path |
| Persistence (MVP) | SQLite (`outputs/finanalyse.db`) | Single file; zero infra; thread-safe; survives restart |
| Persistence (scale) | MySQL RDS (`in-hack-mysql`) | Post-hackathon; SQLAlchemy 2.0 + Alembic migration |
| PDF parsing | `pdfplumber` | Pass 1 (local); superior table detection for Indian annual reports |
| AI gap-fill | Claude API tool-use | Pass 2; triggered when extraction confidence < 0.75 |
| Excel generation | `xlsxwriter` | Live formulas, 6 charts, 19-sheet workbook; streams to disk |
| Word generation | `python-docx` | 9-section AI commentary report |
| AI SDK | `anthropic` Python SDK + `tenacity` retry | `claude-sonnet-4-6` primary; retry 3× with backoff |
| Stock data | `yfinance` | 2-year weekly prices for beta regression and VaR sheets |
| Logging | Python `logging` | Rotating daily file; `outputs/logs/`; structured format |
| Container | Single Python 3.11-slim image | FastAPI via `uvicorn` port 8000 |

### Frontend (`service-frontend/`)

| Layer | Choice |
|-------|--------|
| Framework | Next.js 14 (App Router) |
| Language | TypeScript |
| UI | Tailwind CSS + shadcn/ui |
| Server state | React Query (TanStack Query) — polling `/status/{job_id}` |
| Client state | Zustand |
| File upload | react-dropzone (PDF only) |
| Chat UI | Custom component, streaming-friendly fetch |

### AI / LLM

- **Primary model:** `claude-sonnet-4-6` — extraction gap-fill + all 7 commentary sections + next steps
- **Key:** `CLAUDE_API_KEY` — injected via `secrets.json` → GitHub Secrets → pod env; never in source
- **Extraction:** tool-use / structured JSON mode via `EXTRACTION_TOOL` schema
- **Commentary:** freeform text; 2–3 paragraphs per section; figures cited inline
- **Fallback:** Gemini (Google Cloud $300 free trial) if Claude quota runs out

---

## Pipeline Architecture (5 Steps)

Runs as a FastAPI `BackgroundTask` — non-blocking; `job_id` returned immediately; frontend polls `/status/{job_id}`.

```
1. Extract    — pdfplumber (Pass 1) → confidence scored per field
               → if aggregate confidence < 0.75: Claude API tool-use (Pass 2)
               → merge (local values win; API fills nulls only)
               → validate relevance (reject if confidence < 0.25 or no revenue)

2. Commentary — Claude API: 7-section narrative dict
               (executive_summary, revenue_analysis, profitability_analysis,
                balance_sheet_analysis, cash_flow_analysis, key_risks, key_strengths)

3. Excel      — xlsxwriter: 19-sheet workbook (non-fatal — Word report still generates if this fails)
               → yfinance fetch for beta/VaR sheets (if ticker provided)

4. Report     — python-docx: 9-section Word report (cover, 7 commentary sections, ratios table, disclaimer)

5. Next Steps — Claude API: 6 prioritized analyst recommendations
               (≥1 high, ≥2 medium, ≥1 low; each cites specific figures)
```

Commentary JSON + next steps JSON persisted to SQLite at completion — powers chatbot and comparison chat permanently.

---

## Excel Workbook — 19 Sheets

| # | Sheet | Status |
|---|-------|--------|
| 1 | Cover — company profile, 5-year KPI summary | Existing |
| 2 | Income Statement — all years, YoY growth, CAGR | Existing |
| 3 | Balance Sheet — all years, check row (PASS/FAIL) | Existing |
| 4 | Cash Flow — CFO/CFI/CFF/FCF, reconciliation check | Existing |
| 5 | Common Size — IS as % of Revenue; BS as % of Total Assets | **New** |
| 6 | Ratio Analysis — 30+ ratios, Mean/Median columns, red-flag highlights | Existing (extended) |
| 7 | Forecasting — weighted moving avg; 5-year forward for Sales/EBITDA/EBT/EPS; bar charts | **New** |
| 8 | Beta Regression — 2-year weekly returns vs NIFTY 50; Blume-adjusted beta | **New** |
| 9 | WACC — peer comps table; Cost of Debt; CAPM cost of equity; WACC output | **New** |
| 10 | DCF Valuation — ROIC → FCFF → terminal value → equity value/share; 5×5 sensitivity grid | Existing |
| 11 | DDM Valuation — dividend growth model (when dividends reported) | Existing |
| 12 | Comparable Comps — EV/Revenue, EV/EBITDA, P/E vs peers; implied value/share | Existing |
| 13 | VaR & Simulation — historical VaR (4 confidence levels); Monte Carlo 10,000 paths; histogram | **New** |
| 14 | DuPont Analysis — 3-factor ROE/ROA decomposition; all years; written summary | **New** |
| 15 | Working Capital — WC trend, DSO, DIO, DPO, cash conversion cycle | Existing |
| 16 | Valuation Settings — user-editable WACC, terminal growth, beta inputs (feeds DCF/DDM live) | Existing |
| 17 | Verification — BS equation PASS/FAIL; CF reconciliation; formula error scan | Existing |
| 18 | Chart Data — hidden helper sheet; clean ranges for 6 embedded charts | Existing |
| 19 | Charts — 6 charts: Revenue/EBITDA/PAT trend, margin trends, CF breakdown, FCF vs PAT, returns, capital structure | Existing |

**6 new sheets to build:** Common Size (5), Forecasting (7), Beta Regression (8), WACC (9), VaR & Simulation (13), DuPont Analysis (14).

---

## API Routes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/analyze` | Upload PDF(s), create job, start pipeline |
| POST | `/upload-chunk` | Chunked upload for large PDFs (up to 1 GB) |
| POST | `/upload-finalize/{upload_id}` | Assemble chunks |
| POST | `/auto-detect` | Detect company name + fiscal years from PDF |
| GET | `/status/{job_id}` | Poll job progress + step log |
| GET | `/download/{job_id}/excel` | Download `.xlsx` |
| GET | `/download/{job_id}/report` | Download `.docx` |
| GET | `/history` | List all past analyses from SQLite |
| POST | `/chat/{job_id}` | Single-company chatbot (grounded in commentary JSON) |
| POST | `/compare` | Two-company comparison chat (`{ job_ids: [id1, id2], message, history }`) |
| GET | `/health` | Liveness / readiness probe |

---

## Data Models

**SQLite tables:**
- `jobs` — id, status, company_name, ticker, currency, unit, fiscal_years (JSON), error_message, created_at, completed_at
- `reports` — job_id, report_path, excel_path, commentary (JSON text), next_steps (JSON text), created_at

**Pydantic models (in `src/models/`):**
- `FinancialData` — top-level container: company_name, ticker, currency, unit, fiscal_years, income_statements[], balance_sheets[], cash_flow_statements[], metadata
- `IncomeStatement` — per fiscal year; all monetary fields `Optional[float]` (None = not reported)
- `BalanceSheet` — per fiscal year; `@model_validator` flags imbalance > 1% by reducing confidence
- `CashFlowStatement` — per fiscal year; `@model_validator` flags reconciliation failure > 2%
- `ExtractionMetadata` — source_type, overall_confidence, model_used, warnings[]

---

## Existing Codebase (Working Foundation)

The working Python codebase lives in `Nurix-2026-Hackathon 11.03.33 13.33.22/` and is mirrored at [sunirasrapelli/hackathon_first_draft](https://github.com/sunirasrapelli/hackathon_first_draft).

Key files:
```
agents/
  extractor.py        — two-pass extraction orchestrator
  pdf_parser.py       — pdfplumber local extraction (Pass 1)
  analyzer.py         — Claude API commentary + next steps
  excel_builder.py    — xlsxwriter 13-sheet workbook (needs 6 new sheets)
  charts_builder.py   — 6 embedded charts
  valuation_builder.py — DCF, DDM, Comps sheets
  report_generator.py — python-docx Word report
  verifier.py         — post-build cross-checks

utils/
  formula_registry.py — all Excel formulas centralised (never hardcode in builders)
  excel_styles.py     — StyleBook: navy/gold theme, all format objects
  pdf_handler.py      — PDF load, base64 encode, page extraction
  logger.py           — rotating daily log to outputs/logs/

web/
  app.py              — FastAPI routes + BackgroundTasks pipeline
  jobs.py             — in-memory thread-safe job store
  db.py               — SQLite persistence (jobs + reports tables)

config/settings.py    — all constants, thresholds, paths, valuation defaults
schemas/extraction_tool_schema.py — Claude tool-use JSON schema for extraction
prompts/              — extraction_system.txt, extraction_user.txt, verification_system.txt
errors.py             — typed exception hierarchy
```

**When building the 6 new Excel sheets:** follow the patterns in `excel_builder.py`, use `formula_registry.py` for all formulas, use `excel_styles.py` `StyleBook` for all formatting. Never hardcode cell references or formula strings directly in sheet-building functions.

---

## Security

- `CLAUDE_API_KEY` and all secrets: never in source; always via `config/secrets.json` → GitHub Secrets → pod env
- File upload: validate MIME type (PDF only); reject all other formats; enforce 50 MB per file; UUID-named temp files
- No auth in MVP (single-session hackathon demo)
- SQLite: parameterized queries only; no raw SQL string formatting
- No rate limiting needed for hackathon scale

---

## Observability

- Per-step progress log on every job: `job.log(step, message, done=bool)` — surfaced via `/status/{job_id}`
- Rotating daily log file: `outputs/logs/{YYYYMMDD}.log` (10 MB max, 5 backups)
- Log format: `%(asctime)s [%(levelname)-8s] %(name)s — %(message)s`
- Health endpoint: `GET /health` → `{ status: "ok" }`
- Frontend: errors surfaced via toast; no Sentry in MVP

---

## Testing Strategy

- **Unit:** `pytest` for pure functions — ratio computations, validators, formula generators
- **Integration:** FastAPI `TestClient` against the full app with fixture PDF
- **AI mocking:** `MOCK_EXTRACTION=true` env flag bypasses Claude API; returns Infosys FY2024 fixture data for demo reliability
- **E2E:** Not in hackathon scope — demo manually with Reliance FY2024, Infosys FY2024, Apple 10-K 2023

---

## Deployment Notes

- Each service deploys independently on push to `stage` when `service-*/**` files change
- Backend: single Python 3.11-slim container; `uvicorn` on port 8000
- Frontend: Next.js via `nextjs-service.Dockerfile`
- `outputs/` directory auto-created on startup; SQLite DB initialised on first request
- Rollback: `helm rollback finanalyse-backend -n team-ppo-nahi-milega`

---

## Key Decisions Log

| Decision | Choice | Reason |
|----------|--------|--------|
| Backend language | Python 3.11 | Superior PDF (pdfplumber), Excel (xlsxwriter), and financial compute ecosystem |
| Backend framework | FastAPI | Async, Pydantic v2, auto OpenAPI; already implemented in codebase |
| Async jobs (MVP) | FastAPI `BackgroundTasks` | Already implemented; zero infra; sufficient for demo |
| Async jobs (scale) | Celery + Valkey | Valkey provisioned; survives pod restarts; scales to N workers |
| Persistence (MVP) | SQLite | Already implemented; zero infra; survives restart; thread-safe with WAL |
| Persistence (scale) | MySQL RDS | Required for multi-replica; clean SQLAlchemy + Alembic migration path |
| Input format | PDF only | Simplest for MVP; XBRL post-hackathon |
| PDF parse strategy | Two-pass (pdfplumber → Claude API) | pdfplumber at zero cost; Claude gap-fill only when confidence < 0.75 |
| Confidence threshold | 0.75 for gap-fill; 0.25 to reject | Configurable in `config/settings.py` |
| LLM | `claude-sonnet-4-6` | Strong structured output; tool-use for extraction; 200K context |
| Excel generation | `xlsxwriter` | Only Python lib with native live formula support; streams to disk |
| Excel scope | 19 sheets | 13 existing + 6 new to match Reliance reference output |
| Word generation | `python-docx` | Mature; no system deps |
| Stock data | `yfinance` | Free; NSE/BSE coverage; sufficient for beta and VaR |
| Chat — single | `/chat/{job_id}` | Commentary JSON from SQLite; always available post-completion |
| Chat — comparison | `/compare` with `[id1, id2]` | Structured injection of both commentary JSONs; ~6K tokens; no RAG needed |
| Max comparison | 2 companies | Context grows non-linearly; RAG needed for N>2 |
| Auth | None in MVP | Adds complexity without demo value |

---

## What Claude Should NOT Do

- Do not rename or move `docs/`, `docs/PRD.md`, or `docs/LLD.md`
- Do not create a top-level `backend/` or `frontend/` folder — services live in `service-*`
- Do not push to any branch other than `stage`
- Do not edit `.github/workflows/deploy.yml`
- Do not put secrets in source code
- Do not add features beyond what is needed for a convincing demo
- Do not hardcode Excel cell references or formula strings — use `formula_registry.py`
- Do not hardcode formatting — use `excel_styles.py` StyleBook

---

## Phase Completion Status

- [x] Phase 1 — Product analysis complete (`idea.md`)
- [x] Phase 2 — PRD v1.2 complete (`docs/PRD.md`) — pushed to `stage`
- [x] Phase 3 — LLD complete (`docs/LLD.md`) — 19-sheet Excel, Python stack, PDF-only input — pushed to `stage`
- [ ] Phase 4 — Repo scaffolding (`service-backend/`, `service-frontend/`) — move codebase into hackathon structure
- [ ] Phase 5 — Implementation — build 6 new Excel sheets; wire comparison chat; deploy
