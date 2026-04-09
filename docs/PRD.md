# Product Requirements Document (PRD)

**Team:** Team PPO Nahi Milega (Suniras Ram Rapelli, Shikhar Kansal)
**Product:** FinAnalyse AI - Financial Analysis Automation Platform
**Last updated:** 9 April 2026

---

## 1. Summary

FinAnalyse AI transforms any company's annual report PDF into a complete, investment-grade financial analysis package: a professional 11-sheet Excel model and an AI-written Word report, delivered in under 5 minutes. What an experienced financial analyst does in 4-8 hours, FinAnalyse does in 3-8 minutes, at zero marginal cost per analysis. The platform targets institutional buyers first - asset managers, equity research firms, and investment banks - with a self-serve consumer tier for independent analysts and students.

---

## 2. Problem

### The Manual Process (Before FinAnalyse)

Every financial analysis starts with the same brutal workflow:

1. Download annual report PDF (200–400 pages)
2. Navigate to financial statements section
3. Manually transcribe Income Statement + Balance Sheet + Cash Flow into Excel - line by line, year by year
4. Build 20+ ratio formulas from scratch
5. Build a DCF model (WACC, terminal value, sensitivity table)
6. Create charts - revenue trends, margin trends, cash flows
7. Write an analysis report with commentary
8. Cross-check numbers for errors

**Time cost:** 4–8 hours per company for an experienced analyst. 8–16 hours for a student.  
**Error rate:** High. Manual transcription introduces rounding errors, copy-paste mistakes, and wrong row references - which cascade through dependent model formulas.

### The Gap in the Market

| Tool | Problem |
|------|---------|
| Bloomberg / FactSet | $25,000+/year. Data only - no model builder |
| Generic AI (ChatGPT) | No PDF extraction, no Excel output, hallucination risk |
| Daloopa / Pascal AI | Enterprise-only, $10k+/year. Built for hedge funds only |
| Free screeners (Screener.in, Finviz) | Aggregated data only - no model, no valuation, no download |

**FinAnalyse fills:** End-to-end PDF → model automation, accessible to students, independent analysts, and boutique firms at zero cost per run. No existing tool goes from a raw PDF to a complete valuation model with AI-written commentary in a single pipeline.

---

## 3. Goals & success criteria

| Goal | How we will know it worked |
|------|----------------------------|
| Complete end-to-end pipeline: PDF upload → Excel model + Word report | Demonstrated live on 3 real annual reports (Infosys, Sun Pharma, Apple 10-K) during hackathon demo |
| Extraction accuracy investors can trust | > 97% accuracy on revenue, EBITDA, net income vs. source document |
| Balance sheet integrity guaranteed | 100% of outputs pass BS equation check (verifier.py) |
| Speed advantage vs. manual | Clean PDF (3 years) → download in < 3 minutes; complex PDF → < 8 minutes |
| Output quality matches institutional tools | Excel output indistinguishable from analyst-built model when opened side by side |
| AI commentary reads as professional analysis | Word report passes review against a manually written equity research note |
| Users complete the flow without instructions | > 70% of first-time users successfully upload and download without documentation |
| Chatbot answers grounded in the specific analysis | Chatbot correctly answers ≥ 3 targeted questions without hallucinating numbers |

**Out of scope (explicit non-goals):**

- Real-time market data, live stock price feeds, or order management
- Investment ratings (Buy / Hold / Sell) - requires normalised benchmarks and regulatory clearance
- Quantitative / factor model construction
- Multi-language annual report support (English only for MVP)
- User authentication and persistent accounts (post-hackathon)
- Integration with Bloomberg, FactSet, or external data terminals (post-hackathon)
- Trade execution or OMS/EMS connectivity

---

## 4. Users & personas

### Primary: B2B Institutional (Revenue-Generating)

| Persona | Needs | Notes |
|---------|-------|-------|
| **Economic Buyer** (Vikram, Head of Equity Research, mid-sized AMC) | ROI justification for CFO; accuracy audit trail; data security and SEBI compliance | Signs the contract; needs accuracy, security, integration, and a clear 5x ROI calc |
| **Enterprise Analyst** (Neha, Senior Analyst at AMC, covers 18 pharma + FMCG companies) | Auditable extraction - every number traceable to source PDF page; must verify every cell before trusting output | Earns season is her breaking point: 12-hour days just updating models. Won't adopt without source-linking and a verification sheet |
| **PE Associate** (Sarah, $2B PE fund, due diligence and portfolio monitoring) | Extract financials from data room PDFs, normalise across inconsistent formats, populate draft model | Spends 2 weeks on data extraction before modelling even begins; FinAnalyse cuts that to hours |
| **IT / Compliance Lead** (Rajesh, VP Technology at AMC) | SSO, data residency, API key management, full audit trail | Blockers: Okta integration, DPDP Act 2023 compliance, no shared API keys across 25 analysts |

### Secondary: B2C Self-Serve (Brand and Pipeline)

| Persona | Needs | Notes |
|---------|-------|-------|
| **Boutique Fund Analyst** (Priya, ₹500Cr long/short fund, 20 companies) | Fast model refresh during earnings season; time on investment judgment not data entry | Entry point to enterprise; referred upward to Head of Research if they find value |
| **Independent Investor** (Karan, ₹50L personal portfolio) | DCF model and ratio analysis on any company without Bloomberg subscription | Wants institutional-quality output; can't justify ₹1.5L/yr for a data terminal |
| **Finance Student** (Aditya, MBA Finance) | Complete Excel model + Word report for internship applications without 2 days of data entry | Volume driver; viral via college finance clubs; builds brand credibility |
| **Finance Educator** (Dr. Ananya, equity valuation professor) | Use in class - feed a report, show students the output, teach interpretation not construction | Classroom pilots create institutional credibility and inbound from students entering the workforce |

---

## 5. User journeys / flows

**Flow 1 - Standard Analysis (Core)**

1. User opens web app; drag-drop PDF annual report into upload zone
2. User enters: company name, fiscal years, currency (INR/USD/EUR/GBP), units (Crores/Millions/Billions)
3. User clicks "Run Analysis"
4. Progress tracker shows live stage updates: Extract → Excel → Verify → Report (4 labelled steps with animated indicators)
5. Pipeline runs: pdfplumber parses PDF → Claude API fills gaps (if confidence < 75%) → verifier checks BS equation and cash reconciliation → xlsxwriter builds 11-sheet Excel → Claude generates 7-section Word commentary
6. Analysis completes (< 3 min clean PDF / < 8 min complex PDF)
7. Download cards appear: `.xlsx` (11-sheet model) + `.docx` (AI Word report)
8. User opens Excel → navigates 11 sheets → adjusts WACC assumptions → model recalculates live
9. User opens Word report → reads investment-grade commentary with specific figure citations

**Flow 2 - Analysis Library & Re-access**

1. User returns to the application home screen
2. Analysis Library shows all previously completed analyses: company name, date, fiscal years, confidence scores
3. User clicks a past analysis → full dashboard opens (financial tables, commentary, recommendations, download links)
4. User re-enters the single-company chatbot or initiates a cross-document comparison

**Flow 3 - Cross-Document Comparison Chat**

1. User has just completed analysis for Company A
2. User selects Company B from the Analysis Library → clicks "Compare"
3. System builds a structured context: key financial metrics, ratios, and condensed commentary for both companies
4. User asks: "Which company has stronger operating margins?" → chatbot cites specific figures for both, attributing correctly
5. User asks follow-up questions; chatbot maintains conversation context and stays grounded in the two analyses only

**Flow 4 - Low-Confidence Extraction**

1. User uploads an annual report with non-standard multi-column table formatting (common in Indian annual reports)
2. Local pdfplumber pass yields incomplete data (confidence < 0.75 on Balance Sheet)
3. Claude API gap-fill pass supplements missing fields
4. Confidence scores displayed per statement in the UI - low-confidence cells highlighted in Verification sheet
5. User sees "3 values flagged low confidence" → clicks through to Verification sheet → confirms or overrides values manually

---

## 6. Functional requirements

### Core Pipeline

| ID | Requirement | Priority |
|----|-------------|----------|
| F1 | Accept PDF annual report uploads via drag-drop and file picker (up to 5 PDFs per submission, 50MB each) | P0 |
| F2 | Accept XBRL (.xml) files for SEC-filed companies as a high-accuracy alternative input format - bypasses PDF parsing for near-perfect extraction | P1 |
| F3 | Two-pass extraction: local pdfplumber first; Claude API gap-fill if confidence < 75% | P0 |
| F4 | Extract Income Statement: revenue, COGS, gross profit, EBITDA, EBIT, net income, EPS across all reported fiscal years | P0 |
| F5 | Extract Balance Sheet: current assets, non-current assets, total assets, liabilities, long-term debt, equity | P0 |
| F6 | Extract Cash Flow Statement: operating, investing, financing flows and free cash flow | P0 |
| F7 | Assign confidence score (0.0–1.0) per extracted field; aggregate per statement | P0 |
| F8 | Validate: balance sheet equation (assets = liabilities + equity), net income → retained earnings delta, cash flow reconciliation | P0 |
| F9 | Flag validation failures as warnings (not errors) - analysis proceeds with a caveat visible in UI | P0 |
| F10 | Compute 20+ financial ratios: margins, growth rates, liquidity, leverage, returns (ROE, ROA, ROIC) | P0 |

### Excel Output (11 Sheets)

| ID | Requirement | Priority |
|----|-------------|----------|
| F11 | Generate Cover, Income Statement, Balance Sheet, Cash Flow, Ratios, Verification, Settings, WACC, DCF Valuation, DDM, Comps sheets | P0 |
| F12 | DCF sheet: 5-year FCF projection + terminal value + sensitivity table (WACC × growth rate grid) | P0 |
| F13 | All cells use live Excel formulas - no hardcoded values; changing WACC assumptions in Settings propagates through the model | P0 |
| F14 | Charts: Revenue & EBITDA trends, margin trends, cash flow breakdown, return metrics | P0 |
| F15 | Professional navy/gold investment bank style formatting throughout | P0 |
| F16 | Verification sheet: balance check result (PASS/FAIL), cash reconciliation, low-confidence cell flags (yellow highlight) | P0 |

### Word Report Output

| ID | Requirement | Priority |
|----|-------------|----------|
| F17 | Generate `.docx` Word report with 7 sections: Executive Summary, Revenue Analysis, Profitability Analysis, Balance Sheet Analysis, Cash Flow Analysis, Key Risks, Key Strengths | P0 |
| F18 | All commentary grounded in actual extracted figures - cites specific numbers (e.g., "Revenue grew 14% YoY to ₹94,432 Cr in FY2024") | P0 |
| F19 | Embed Excel charts as images in Word report (`add_picture()`) | P1 |
| F20 | Include valuation summary section in Word report: DCF implied price range, DDM price, comps-implied range | P1 |

### Analysis Library & Persistence

| ID | Requirement | Priority |
|----|-------------|----------|
| F21 | All completed analyses stored persistently; accessible from home screen Analysis Library | P0 |
| F22 | Library shows: company name, date, fiscal years covered, per-statement confidence scores | P0 |
| F23 | User can re-open any past analysis, re-download files, re-enter chatbot | P0 |
| F24 | Library supports search/filter by company name | P1 |

### Contextual Chatbot

| ID | Requirement | Priority |
|----|-------------|----------|
| F25 | After analysis completes, user accesses a chatbot grounded exclusively in that job's extracted data and commentary | P0 |
| F26 | Chatbot cites specific figures and section sources in its responses; declines to speculate beyond the document | P0 |
| F27 | Chatbot maintains conversation context across multiple turns in a session | P0 |

### Cross-Document Comparison Chat

| ID | Requirement | Priority |
|----|-------------|----------|
| F28 | User can select exactly two analyses from the Library and initiate a Comparison Chat session | P0 |
| F29 | System builds a structured context from both analyses: key metrics, ratios, condensed commentary - injected into LLM system prompt | P0 |
| F30 | Chatbot explicitly attributes figures to the correct company; does not confuse datasets | P0 |
| F31 | Chatbot degrades gracefully when a metric is available for one company but not the other | P0 |

### Source-Linking & Red-Flag Detection

| ID | Requirement | Priority |
|----|-------------|----------|
| F32 | Every extracted numeric value stores: document filename, page number, section/table reference | P1 |
| F33 | Source citations shown as cell comments or in a Sources sheet in the Excel workbook | P1 |
| F34 | Red-flag detection: automatically flags metrics with ≥ 15% YoY margin swing or ≥ 20% absolute revenue/debt change | P1 |
| F35 | Red flags surfaced as "Alerts" panel in UI with metric name, deviation magnitude, and years compared | P1 |

### Additional Ingestion Formats

| ID | Requirement | Priority |
|----|-------------|----------|
| F36 | Accept XBRL (.xml) files for SEC-filed companies - bypasses PDF parsing pass for near-perfect extraction accuracy | P1 |
| F37 | Accept plain-text earnings call transcripts as supplementary document - enriches commentary with management guidance and tone | P2 |

---

## 7. Non-functional requirements

**Performance:**
- Clean PDF (3 fiscal years) → downloaded outputs: < 3 minutes end-to-end
- Complex PDF (5 years + API gap-fill): < 8 minutes
- XBRL input (when provided): < 60 seconds
- API endpoints (status polling, chatbot, library): < 200ms response time
- Analysis Library renders up to 50 entries: < 1 second

**Reliability / Availability:**
- Failed pipeline jobs retry automatically up to 3 times with exponential backoff
- All job state persists in database - survives backend restart
- `mockExtraction` mode exists for demo reliability - returns fixture data without calling Claude API
- Target uptime: 99.5% (enforced SLA in enterprise tier)
- Earnings season load: auto-scaling via EKS HPA; queue-based job dispatch prevents overload

**Security & Privacy:**
- API keys (Claude, DB credentials) never in source code - managed via GitHub Secrets → Kubernetes pod env vars
- Uploaded files validated for MIME type and size before processing; UUID-named to prevent path traversal
- No SQL injection: Prisma/SQLAlchemy parameterized queries only
- Rate limiting on upload endpoint
- Enterprise tier: tenant-isolated VPC, AES-256 at rest, TLS 1.3 in transit
- Zero training on client data - Anthropic API calls do not use client data for model training
- DPDP Act 2023 (India) compliance: data residency configurable; right to deletion; DPA available
- SEBI Research Analyst Regulations 2014: disclaimer management for enterprise research output

**Observability:**
- Every HTTP request logged with requestId, method, path, status code, duration
- Every pipeline stage transition logged with jobId, stage name, and duration
- All Claude API calls log: model, prompt tokens, completion tokens, latency
- Health endpoint: `GET /health` returns database and queue connectivity status
- Per-tenant usage metrics for enterprise: analyses run, avg processing time, error rate

---

## 8. Dependencies & assumptions

**External dependencies:**
- `CLAUDE_API_KEY` (Anthropic Claude Sonnet 4.6) - available in `.env`; required for gap-fill pass and all commentary generation
- AWS EKS (in-hack-eks-01, ap-south-1) - container orchestration
- Amazon RDS MySQL 8.0 (in-hack-mysql) - persistent storage for jobs, analyses, chat sessions
- Amazon ElastiCache Valkey 8.1 (in-hack-cache-01) - BullMQ job queue backend
- `pdfplumber` / `pymupdf` - local PDF parsing (no API cost for first pass)
- `xlsxwriter` - Excel generation (11-sheet workbook with live formulas and charts)
- `python-docx` - Word report generation
- `anthropic` Python SDK - structured extraction via tool_use and commentary generation

**Assumptions:**
- Annual reports are in English; non-English reports are out of scope for MVP
- PDF upload is the only supported input format for MVP; XBRL is a P1 addition for SEC-filed companies
- No user authentication required for hackathon demo - all analyses are globally accessible by Job ID
- A single demo instance will process 1–3 concurrent analyses during the hackathon; no horizontal scaling tested
- Confidence threshold for triggering Claude API gap-fill: 0.75 (configurable)
- The `.docx` Word report is the primary shareable artifact; PDF export is post-hackathon

---

## 9. Open questions

- [ ] **Excel column detection accuracy on Indian annual reports** - Word-position-based detection is the fix; needs validation on Reliance, HDFC, and Infosys FY2024 PDFs before demo - *owner: Shikhar*
- [ ] **Charts in Word report** - `add_picture()` approach confirmed viable; needs chart-to-PNG export step wired into pipeline - *owner: Shikhar*
- [ ] **Multi-year extraction from single PDF** - most Indian annual reports include 5-year history; current pipeline may truncate at 3 years - *resolve before demo*
- [ ] **XBRL parser library** - `fast-xml-parser` (Node.js) or `arelle` (Python) for SEC XBRL files; decision needed before P1 sprint - *owner: TBD*
- [ ] **Comparison chat context window safety** - at 2 companies × ~3K tokens per structured context, total is ~6K + conversation history; well within Claude 200K limit, but verify with a real stress test
- [ ] **Demo PDF set** - confirm Infosys FY2024, Sun Pharma FY2024, Apple 10-K 2023 all parse cleanly before demo day; have fallback fixture data ready

---

## Appendix A: Output Artifact Inventory

| Output | Format | Status |
|--------|--------|--------|
| Excel Workbook | `.xlsx` - 11 sheets, live formulas, charts | ✅ Built |
| Word Report | `.docx` - 7-section AI commentary | ✅ Built |
| Charts embedded in Word | PNG images via `add_picture()` | ❌ P1 - Phase 6 |
| Valuation section in Word | DCF range, DDM price, comps range | ❌ P1 - Phase 6 |
| PDF Report | `.pdf` - same as Word, for sharing | ❌ P2 - Phase 7 |
| Source Links Sheet | Excel tab - cell → PDF page mapping | ❌ P1 - Phase 7 |

---

## Appendix B: Enterprise B2B Positioning

FinAnalyse targets two distinct markets with the same core product:

**Consumer / Prosumer (free, self-serve):** Students, independent investors, small boutiques. Proves the technology and builds brand. The Excel + Word output is the marketing - every shared file is an ad.

**Enterprise B2B (paid, institutional):** Asset managers, equity research firms, investment banks, Big 4 advisory teams. Revenue model.

### Enterprise Pricing

| Tier | Seats | Annual Price | Key Additions |
|------|-------|-------------|---------------|
| Starter | 1–5 | ₹3.6L/yr | Core features, standard templates, email support |
| Growth | 6–20 | ₹9.6L/yr | Batch processing, custom templates, audit log, SSO |
| Enterprise | 21–100 | ₹24–96L/yr | API access, VPC deployment, SLA, dedicated CSM |
| Enterprise+ | 100+ | Custom | Bloomberg/FactSet connectors, on-premises, custom build |

### Enterprise ROI Justification

```
10-analyst team at AMC
Fully-loaded analyst cost: ₹25L/yr
Models updated per analyst per year: 100 (25 companies × 4 quarters)
Time per model update (manual): 4 hrs
Hours saved per analyst: 400 hrs/yr = 20% of working time

Value generated: 20% × ₹25L × 10 analysts = ₹50L/yr
FinAnalyse cost (Growth tier, 10 seats): ₹9.6L/yr
ROI: 5.2x in Year 1
```

### Enterprise Feature Requirements (post-hackathon)

| Feature | Priority |
|---------|----------|
| SSO / SAML (Okta, Azure AD, Google Workspace) | P0 |
| RBAC (Admin / Analyst / Viewer) | P0 |
| Audit log (who ran what, when, on what file) | P0 |
| Tenant-isolated data storage | P0 |
| Batch processing (20 PDFs → ZIP) | P0 |
| Team workspace (shared analysis library) | P0 |
| Custom output templates (firm logo, branding, disclaimer) | P1 |
| REST API access (programmatic analysis trigger) | P1 |
| Webhook notifications (analysis complete → Slack / Teams) | P1 |
| VPC / on-premises deployment | P1 |
| Bloomberg / FactSet data connector | P2 |
| Model versioning (quarter-over-quarter diff) | P1 |
| SEBI Research Analyst Regulations 2014 compliance mode | P1 |
| SOC 2 Type II (target: 12 months post-launch) | P2 |

---

## Appendix C: Competitive Landscape

| Competitor | Price | Gap vs. FinAnalyse |
|------------|-------|--------------------|
| Bloomberg Excel | $25k/yr | Data only - no model builder, no AI commentary |
| Daloopa | $10–50k/yr | Extraction + Excel only; no valuation model; US-only; enterprise-gated |
| Pascal AI | $10–100k/yr | Full hedge fund platform; overkill for mid-market; no India coverage |
| AlphaSense | $15–50k/yr | Search + NLP; not a model builder |
| Generic AI (ChatGPT) | $20/month | No structured output, no Excel, hallucination risk |
| Manual + screeners | Free | 4–8 hrs/company; high error rate; no valuation |

**FinAnalyse's unique position:** Only tool that goes from raw PDF → complete valuation model (DCF, DDM, comps) + AI-written research report in one pipeline. Priced for mid-market. Purpose-built for Indian financial reporting formats (Indian GAAP, Ind AS, SEBI filings). Free for consumers, enterprise-priced for institutions.
