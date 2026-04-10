/**
 * FinAnalyse AI — Frontend v4
 * Unified black + purple theme. Chunked upload, split-screen analysis,
 * Financial Reports with filters + delete, modal detail view, chatbot.
 */

/* ══════════════════════════════════════════════════════════════════════════
   STATE
══════════════════════════════════════════════════════════════════════════ */
let selectedFiles  = [];  // { file, uploadId, path, progress }
let pollTimer      = null;
let currentJobId   = null;
let chatHistory    = [];
let chatBusy       = false;
let chatPanelOpen  = false;
let autoDetecting  = false;

const CHUNK_SIZE   = 5 * 1024 * 1024;  // 5 MB
const DIRECT_LIMIT = 50 * 1024 * 1024; // 50 MB — direct upload below this

/* ══════════════════════════════════════════════════════════════════════════
   DOM REFS
══════════════════════════════════════════════════════════════════════════ */
const dropZone       = document.getElementById('drop-zone');
const fileInput      = document.getElementById('file-input');
const fileListEl     = document.getElementById('file-list');
const fileCountHint  = document.getElementById('file-count-hint');
const companyInput   = document.getElementById('company-input');
const yearsInput     = document.getElementById('years-input');
const currencySelect = document.getElementById('currency-select');
const unitSelect     = document.getElementById('unit-select');
const analyzeBtn     = document.getElementById('analyze-btn');
const errorBanner    = document.getElementById('error-banner');
const autoBanner     = document.getElementById('auto-banner');
const autoSpin       = document.getElementById('auto-spin');
const autoText       = document.getElementById('auto-text');
const companyBadge   = document.getElementById('company-badge');
const yearsBadge     = document.getElementById('years-badge');
const rightIdle      = document.getElementById('right-idle');
const progressOvl    = document.getElementById('progress-overlay');
const resultsOvl     = document.getElementById('results-overlay');
const progTitle      = document.getElementById('prog-title');
const progSub        = document.getElementById('prog-sub');
const chatWidget     = document.getElementById('chat-widget');
const chatFab        = document.getElementById('chat-fab');
const chatUnread     = document.getElementById('chat-unread');
const chatPanelEl    = document.getElementById('chat-panel');
const chatClose      = document.getElementById('chat-close');
const chatSubEl      = document.getElementById('chat-sub');
const chatMessages   = document.getElementById('chat-messages');
const chatInputEl    = document.getElementById('chat-input');
const chatSendBtn    = document.getElementById('chat-send');
const newAnalysisBtn = document.getElementById('new-analysis-btn');

/* ══════════════════════════════════════════════════════════════════════════
   VIEW ROUTING
══════════════════════════════════════════════════════════════════════════ */
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById(name + '-view').classList.add('active');
  document.querySelectorAll('.nav-pill').forEach(b => b.classList.remove('active'));
  const pill = document.getElementById('nav-' + name);
  if (pill) pill.classList.add('active');
  if (name === 'reports') loadReports();
}

/* ══════════════════════════════════════════════════════════════════════════
   UTILITIES
══════════════════════════════════════════════════════════════════════════ */
function esc(str) {
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmtBytes(b) {
  if (b < 1024)       return b + ' B';
  if (b < 1048576)    return (b/1024).toFixed(1) + ' KB';
  if (b < 1073741824) return (b/1048576).toFixed(1) + ' MB';
  return (b/1073741824).toFixed(2) + ' GB';
}

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-GB', {day:'numeric',month:'short',year:'numeric'});
}

function md(text) {
  let s = esc(text);
  s = s.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
  s = s.replace(/\n/g, '<br>');
  return s;
}

function uid() {
  return 'up_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2,8);
}

/* ══════════════════════════════════════════════════════════════════════════
   YEAR PARSER
══════════════════════════════════════════════════════════════════════════ */
function parseYears(raw) {
  const years = [];
  for (const token of raw.split(',')) {
    const t = token.trim();
    if (!t) continue;
    const r = t.match(/^(\d{4})\s*-\s*(\d{4})$/);
    if (r) {
      const s = +r[1], e = +r[2];
      if (s > e) throw new Error(`Invalid range: ${t}`);
      for (let y = s; y <= e; y++) years.push(y);
    } else {
      const n = parseInt(t, 10);
      if (isNaN(n)) throw new Error(`Not a year: "${t}"`);
      years.push(n);
    }
  }
  return [...new Set(years)].sort((a,b)=>a-b);
}

/* ══════════════════════════════════════════════════════════════════════════
   FILE MANAGEMENT
══════════════════════════════════════════════════════════════════════════ */
function addFiles(list) {
  let added = 0;
  for (const f of list) {
    const ext = f.name.split('.').pop().toLowerCase();
    if (!['json','pdf'].includes(ext)) { showError(`'${f.name}' — only .pdf or .json supported.`); continue; }
    if (!selectedFiles.find(x => x.file.name === f.name && x.file.size === f.size)) {
      selectedFiles.push({ file: f, uploadId: null, path: null, progress: 0 });
      added++;
    }
  }
  if (added) { hideError(); triggerAutoDetect(); }
  renderFiles(); validateForm();
}

function removeFile(i) {
  selectedFiles.splice(i, 1);
  renderFiles(); validateForm();
  if (!selectedFiles.length) hideAutoBanner();
}

function renderFiles() {
  fileListEl.innerHTML = selectedFiles.map((item, i) => {
    const { file, progress } = item;
    const ext   = file.name.split('.').pop().toLowerCase();
    const icon  = ext === 'pdf' ? '📕' : '📋';
    const large = file.size > DIRECT_LIMIT;
    const tag   = large ? `<span style="font-size:10px;color:var(--warn);margin-left:6px;font-weight:600;">chunked</span>` : '';
    return `<div class="file-badge">
      <span class="file-icon">${icon}</span>
      <div class="file-info">
        <div class="file-name">${esc(file.name)}${tag}</div>
        <div class="file-size">${fmtBytes(file.size)}</div>
        ${large ? `<div class="file-prog"><div class="file-prog-bar" id="fbar-${i}" style="width:${progress}%"></div></div>` : ''}
      </div>
      <button class="file-remove" onclick="removeFile(${i})" title="Remove">✕</button>
    </div>`;
  }).join('');

  if (!selectedFiles.length) {
    fileCountHint.style.display = 'none';
    return;
  }
  fileCountHint.style.display = 'block';
  if (selectedFiles.length < 3) {
    fileCountHint.className = 'file-hint warn';
    fileCountHint.textContent = `${selectedFiles.length} file(s) — upload 3+ for full trend analysis`;
  } else {
    fileCountHint.className = 'file-hint';
    fileCountHint.textContent = `${selectedFiles.length} file(s) ready`;
  }
}

/* ══════════════════════════════════════════════════════════════════════════
   CHUNKED UPLOAD
══════════════════════════════════════════════════════════════════════════ */
async function uploadFilesBeforeAnalysis() {
  const directFiles = [], preUploadedPaths = [];

  for (let i = 0; i < selectedFiles.length; i++) {
    const item = selectedFiles[i];
    if (item.file.size <= DIRECT_LIMIT) { directFiles.push(item.file); continue; }

    const uploadId    = uid();
    item.uploadId     = uploadId;
    const totalChunks = Math.ceil(item.file.size / CHUNK_SIZE);

    for (let c = 0; c < totalChunks; c++) {
      const blob = item.file.slice(c * CHUNK_SIZE, Math.min((c+1)*CHUNK_SIZE, item.file.size));
      const fd   = new FormData();
      fd.append('upload_id', uploadId);
      fd.append('chunk_index', c);
      fd.append('total_chunks', totalChunks);
      fd.append('filename', item.file.name);
      fd.append('chunk', blob, item.file.name);

      const r = await fetch('/upload-chunk', { method:'POST', body: fd });
      if (!r.ok) throw new Error(`Chunk upload failed for '${item.file.name}'`);

      item.progress = Math.round(((c+1)/totalChunks) * 90);
      const bar = document.getElementById('fbar-' + i);
      if (bar) bar.style.width = item.progress + '%';
    }

    const fd2 = new FormData();
    fd2.append('filename', item.file.name);
    fd2.append('total_chunks', totalChunks);
    const r2 = await fetch(`/upload-finalize/${uploadId}`, { method:'POST', body: fd2 });
    if (!r2.ok) throw new Error(`Failed to finalize '${item.file.name}'`);
    const data = await r2.json();

    item.path = data.path; item.progress = 100;
    const bar = document.getElementById('fbar-' + i);
    if (bar) bar.style.width = '100%';
    preUploadedPaths.push(data.path);
  }
  return { directFiles, preUploadedPaths };
}

/* ══════════════════════════════════════════════════════════════════════════
   AUTO-DETECT
══════════════════════════════════════════════════════════════════════════ */
async function triggerAutoDetect() {
  if (!selectedFiles.length || autoDetecting) return;
  const item = selectedFiles[0];
  if (item.file.size > DIRECT_LIMIT) return;

  autoDetecting = true;
  autoBanner.classList.add('show');
  autoSpin.style.display = 'block';
  autoText.textContent = 'Detecting company and fiscal years…';
  companyBadge.classList.remove('show');
  yearsBadge.classList.remove('show');

  try {
    const fd = new FormData(); fd.append('file', item.file);
    const res = await fetch('/auto-detect', { method:'POST', body: fd });
    const d   = await res.json();

    let hit = false;
    if (d.company_name && !companyInput.value.trim()) {
      companyInput.value = d.company_name; companyBadge.classList.add('show'); hit = true;
    }
    if (d.fiscal_years?.length && !yearsInput.value.trim()) {
      yearsInput.value = d.fiscal_years.join(','); yearsBadge.classList.add('show'); hit = true;
    }
    autoSpin.style.display = 'none';
    if (hit) autoText.textContent = '✓ Company and fiscal years detected';
    else     autoBanner.classList.remove('show');
    validateForm();
  } catch { autoBanner.classList.remove('show'); }
  finally  { autoDetecting = false; }
}

function hideAutoBanner() {
  autoBanner.classList.remove('show');
  companyBadge.classList.remove('show');
  yearsBadge.classList.remove('show');
}

/* ══════════════════════════════════════════════════════════════════════════
   DRAG & DROP
══════════════════════════════════════════════════════════════════════════ */
dropZone.addEventListener('dragover',  e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault(); dropZone.classList.remove('dragover');
  if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files.length) addFiles(fileInput.files);
  fileInput.value = '';
});

/* ══════════════════════════════════════════════════════════════════════════
   FORM VALIDATION
══════════════════════════════════════════════════════════════════════════ */
function validateForm() {
  const hasFiles   = selectedFiles.length > 0;
  const hasPdf     = selectedFiles.some(f => f.file.name.endsWith('.pdf'));
  const hasCompany = companyInput.value.trim().length > 0;
  let yearsOk = true;
  const raw = yearsInput.value.trim();
  if (raw) { try { parseYears(raw); } catch { yearsOk = false; } }
  analyzeBtn.disabled = !hasFiles || (hasPdf && !hasCompany) || !yearsOk;
}

companyInput.addEventListener('input', () => { companyBadge.classList.remove('show'); validateForm(); });
yearsInput.addEventListener('input',   () => { yearsBadge.classList.remove('show');  validateForm(); });

function showError(msg) { errorBanner.textContent = '⚠  ' + msg; errorBanner.classList.add('show'); }
function hideError()    { errorBanner.classList.remove('show'); }

/* ══════════════════════════════════════════════════════════════════════════
   SUBMIT
══════════════════════════════════════════════════════════════════════════ */
analyzeBtn.addEventListener('click', async () => {
  if (!selectedFiles.length) return;
  hideError();
  analyzeBtn.disabled = true;
  analyzeBtn.innerHTML = `<span class="spinner"></span> Uploading…`;
  showProgress('Uploading files…', 'Preparing for analysis');

  try {
    const { directFiles, preUploadedPaths } = await uploadFilesBeforeAnalysis();
    progTitle.textContent = 'Running Analysis…';
    progSub.textContent   = 'Processing your financial reports';

    const fd = new FormData();
    directFiles.forEach(f => fd.append('files', f));
    fd.append('pre_uploaded', JSON.stringify(preUploadedPaths));
    fd.append('company',  companyInput.value.trim());
    fd.append('years',    yearsInput.value.trim());
    fd.append('currency', currencySelect.value);
    fd.append('unit',     unitSelect.value);

    const res  = await fetch('/analyze', { method:'POST', body: fd });
    const data = await res.json();
    if (!res.ok) { showError(data.detail || 'Server error'); resetToUpload(); return; }

    currentJobId = data.job_id;
    startPolling(data.job_id);
  } catch (err) {
    showError('Upload error: ' + err.message);
    resetToUpload();
  }
});

function resetBtn() {
  analyzeBtn.disabled = false;
  analyzeBtn.innerHTML = 'Run Analysis';
}

/* ══════════════════════════════════════════════════════════════════════════
   PANEL SWITCHING
══════════════════════════════════════════════════════════════════════════ */
function showProgress(title, sub) {
  rightIdle.style.display = 'none';
  progressOvl.classList.add('show');
  resultsOvl.classList.remove('show');
  progTitle.textContent = title;
  progSub.textContent   = sub;
  resetOrbs();
}

function showResults(jobId, data) {
  progressOvl.classList.remove('show');
  resultsOvl.classList.add('show');

  document.getElementById('res-title').textContent =
    (data.company_name ? data.company_name + ' — ' : '') + 'Analysis Complete';
  document.getElementById('res-sub').textContent =
    `${data.company_name || 'Analysis'} · ${(data.fiscal_years || []).join(', ') || ''}`;

  document.getElementById('dl-word').href  = `/download/${jobId}/report`;
  document.getElementById('dl-excel').href = `/download/${jobId}/excel`;
  if (!data.files?.excel) document.getElementById('dl-excel').classList.add('disabled');

  // Commentary accordions
  const commentarySection = document.getElementById('commentary-section');
  const commentaryList    = document.getElementById('commentary-list');
  if (data.commentary && typeof data.commentary === 'object') {
    const sections = [
      ['executive_summary',      'Executive Summary'],
      ['revenue_analysis',       'Revenue Analysis'],
      ['profitability_analysis', 'Profitability Analysis'],
      ['balance_sheet_analysis', 'Balance Sheet Analysis'],
      ['cash_flow_analysis',     'Cash Flow Analysis'],
      ['key_risks',              'Key Risks'],
      ['key_strengths',          'Key Strengths'],
    ];
    const html = sections.filter(([k]) => data.commentary[k]).map(([k, label], idx) => `
      <div class="accordion${idx===0?' open':''}">
        <div class="accordion-hd" onclick="toggleAccordion(this)">
          <span class="accordion-title">${label}</span>
          <span class="accordion-chevron">▼</span>
        </div>
        <div class="accordion-body">${esc(data.commentary[k])}</div>
      </div>`).join('');
    if (html) { commentaryList.innerHTML = html; commentarySection.style.display = 'block'; }
  }

  // Next steps
  const nsSection = document.getElementById('ns-section');
  const nsList    = document.getElementById('ns-list');
  const ns = data.next_steps || [];
  if (ns.length) {
    nsList.innerHTML = ns.map((s, i) => {
      const p = (s.priority || 'medium').toLowerCase();
      return `<div class="ns-item" style="animation-delay:${i*0.06}s">
        <span class="ns-badge ${p}">${p.toUpperCase()}</span>
        <div>
          <div class="ns-title">${esc(s.title||'')}</div>
          <div class="ns-desc">${esc(s.description||'')}</div>
        </div>
      </div>`;
    }).join('');
    nsSection.style.display = 'block';
  }

  // Chat
  const co = data.company_name || 'this company';
  chatHistory = []; chatMessages.innerHTML = '';
  if (chatSubEl) chatSubEl.textContent = co;
  appendChat('ai', `Hi! I've analysed **${co}**. Ask me anything about the financials, trends, risks, or next steps.`);
  chatWidget.style.display = 'block';
  chatUnread.classList.add('show');
}

function resetToUpload() {
  rightIdle.style.display = '';
  progressOvl.classList.remove('show');
  resultsOvl.classList.remove('show');
  selectedFiles = []; chatHistory = []; currentJobId = null;
  fileInput.value = ''; renderFiles();
  companyInput.value = ''; yearsInput.value = '';
  hideAutoBanner(); resetOrbs(); resetBtn();
  document.getElementById('ns-section').style.display = 'none';
  document.getElementById('commentary-section').style.display = 'none';
  document.getElementById('dl-excel').classList.remove('disabled');
  chatWidget.style.display = 'none'; closeChatPanel();
  // clear pipeline error block
  const eb = document.getElementById('pipe-err'); if (eb) eb.remove();
}

function toggleAccordion(hd) {
  hd.closest('.accordion').classList.toggle('open');
}

newAnalysisBtn.addEventListener('click', resetToUpload);

/* ══════════════════════════════════════════════════════════════════════════
   PIPELINE STEPS
══════════════════════════════════════════════════════════════════════════ */
const STEPS = ['extract','commentary','excel','report','next_steps'];

function resetOrbs() {
  STEPS.forEach((s, i) => {
    const o = document.getElementById('orb-'+s);
    if (o) { o.className = 'pipe-orb pending'; o.textContent = i+1; }
    const m = document.getElementById('msg-'+s);
    if (m) m.textContent = 'Waiting…';
  });
}

function applyProgress(progress) {
  progress.forEach(p => {
    const o = document.getElementById('orb-'+p.step);
    const m = document.getElementById('msg-'+p.step);
    if (!o) return;
    m.textContent = p.message;
    if (p.done) { o.className = 'pipe-orb done'; o.textContent = '✓'; }
    else        { o.className = 'pipe-orb active'; }
  });
  if (progress.length) progTitle.textContent = progress[progress.length-1].message;
}

/* ══════════════════════════════════════════════════════════════════════════
   POLLING
══════════════════════════════════════════════════════════════════════════ */
function startPolling(jobId) { pollTimer = setInterval(() => pollStatus(jobId), 1500); }

async function pollStatus(jobId) {
  try {
    const res  = await fetch(`/status/${jobId}`);
    const data = await res.json();
    applyProgress(data.progress || []);
    if (data.status === 'done')  { clearInterval(pollTimer); showResults(jobId, data); resetBtn(); }
    if (data.status === 'error') { clearInterval(pollTimer); showPipelineError(data.error || 'Unknown error.'); resetBtn(); }
  } catch (e) { console.warn('Poll error:', e); }
}

function showPipelineError(msg) {
  progTitle.textContent = 'Analysis failed';
  for (let i = STEPS.length-1; i >= 0; i--) {
    const o = document.getElementById('orb-'+STEPS[i]);
    if (o && o.classList.contains('active')) { o.className = 'pipe-orb err'; o.textContent = '✕'; break; }
  }
  const old = document.getElementById('pipe-err'); if (old) old.remove();
  const b = document.createElement('div'); b.id = 'pipe-err';
  Object.assign(b.style, {
    marginTop:'20px', background:'var(--error-dim)',
    border:'1px solid rgba(248,113,113,0.2)', borderRadius:'var(--r-md)',
    padding:'14px 16px', color:'var(--error)', fontSize:'13px',
  });
  b.innerHTML = `<div style="font-weight:700;margin-bottom:6px;">Error</div>
    <div style="margin-bottom:12px;word-break:break-word;">${esc(msg)}</div>
    <button onclick="resetToUpload()" style="background:none;border:1px solid rgba(248,113,113,0.3);
      border-radius:6px;color:var(--error);padding:6px 14px;font-size:12.5px;cursor:pointer;font-family:inherit;">
      ← Try Again</button>`;
  progressOvl.appendChild(b);
}

/* ══════════════════════════════════════════════════════════════════════════
   FINANCIAL REPORTS
══════════════════════════════════════════════════════════════════════════ */
async function loadReports() {
  const tbody = document.getElementById('reports-tbody');
  const empty = document.getElementById('reports-empty');
  const count = document.getElementById('reports-count');
  empty.style.display = 'none'; count.textContent = '';

  tbody.innerHTML = [1,2,3,4,5].map(() => `<tr class="skel">${
    [80,50,60,40,55,70].map(w =>
      `<td><div class="skel-bar" style="width:${w}%"></div></td>`).join('')}</tr>`).join('');

  const company = document.getElementById('f-company').value.trim();
  const status  = document.getElementById('f-status').value;
  const year    = document.getElementById('f-year').value.trim();

  const p = new URLSearchParams({ limit: 200 });
  if (company) p.set('company',   company);
  if (status)  p.set('status',    status);
  if (year)    p.set('year_from', year);

  try {
    const res  = await fetch('/history?' + p);
    const jobs = await res.json();
    renderReports(jobs);
  } catch {
    tbody.innerHTML = `<tr><td colspan="6" style="padding:20px;color:var(--error);font-size:13px;">Failed to load reports.</td></tr>`;
  }
}

function renderReports(jobs) {
  const tbody = document.getElementById('reports-tbody');
  const empty = document.getElementById('reports-empty');
  const count = document.getElementById('reports-count');

  count.textContent = jobs.length ? `· ${jobs.length} report${jobs.length!==1?'s':''}` : '';

  if (!jobs.length) { tbody.innerHTML = ''; empty.style.display = 'block'; return; }
  empty.style.display = 'none';

  tbody.innerHTML = jobs.map(j => {
    const sc = j.status === 'done' ? 'done' : j.status === 'error' ? 'error' : j.status === 'running' ? 'running' : 'queued';
    const sl = j.status === 'done' ? 'Completed' : j.status === 'error' ? 'Failed' : j.status === 'running' ? 'Running' : 'Queued';
    const years = Array.isArray(j.fiscal_years) && j.fiscal_years.length
      ? j.fiscal_years.map(y => `<span class="ytag">${y}</span>`).join('')
      : '<span style="color:var(--text-faint)">—</span>';
    const date = fmtDate(j.finished_at || j.created_at);
    const jid  = esc(j.id);
    const jco  = esc(j.company_name || '');

    const dlReport = j.status==='done' && j.report_path
      ? `<a class="act-btn" href="/download/${jid}/report" download onclick="event.stopPropagation()">↓ Report</a>` : '';
    const dlExcel  = j.status==='done' && j.excel_path
      ? `<a class="act-btn" href="/download/${jid}/excel" download onclick="event.stopPropagation()">↓ Excel</a>` : '';
    const chatBtn  = j.status==='done'
      ? `<button class="act-btn" onclick="event.stopPropagation();openReportChat('${jid}','${jco}')">💬</button>` : '';
    const delBtn   = `<button class="act-btn danger" onclick="event.stopPropagation();confirmDelete('${jid}','${jco}')" title="Delete">🗑</button>`;

    return `<tr class="rrow" onclick="openReportDetail('${jid}')">
      <td class="company-cell">${esc(j.company_name || 'Unknown')}</td>
      <td><span class="status-chip ${sc}"><span class="chip-dot"></span>${sl}</span></td>
      <td><div class="year-tags">${years}</div></td>
      <td style="color:var(--text-secondary);font-size:12.5px;">${esc(j.currency||'')} · ${esc(j.unit||'')}</td>
      <td style="color:var(--text-secondary);font-size:12.5px;white-space:nowrap;">${esc(date)}</td>
      <td><div class="action-group">${dlReport}${dlExcel}${chatBtn}${delBtn}</div></td>
    </tr>`;
  }).join('');
}

function applyFilters() { loadReports(); }

function clearFilters() {
  document.getElementById('f-company').value = '';
  document.getElementById('f-status').value  = '';
  document.getElementById('f-year').value    = '';
  loadReports();
}

['f-company','f-year'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('keydown', e => { if (e.key==='Enter') applyFilters(); });
});

/* ══════════════════════════════════════════════════════════════════════════
   DELETE
══════════════════════════════════════════════════════════════════════════ */
let pendingDeleteId = null;

function confirmDelete(jobId, companyName) {
  pendingDeleteId = jobId;
  document.getElementById('del-body').textContent =
    `"${companyName || 'This report'}" will be permanently removed from the database. Downloaded files on your device will not be affected.`;
  document.getElementById('delete-confirm').classList.add('open');
}

function closeDeleteConfirm(e) {
  if (e && e.target !== document.getElementById('delete-confirm')) return;
  document.getElementById('delete-confirm').classList.remove('open');
  pendingDeleteId = null;
}

document.getElementById('del-confirm-btn').addEventListener('click', async () => {
  if (!pendingDeleteId) return;
  const id = pendingDeleteId;
  document.getElementById('delete-confirm').classList.remove('open');
  pendingDeleteId = null;

  try {
    const res = await fetch(`/history/${id}`, { method:'DELETE' });
    if (!res.ok) { alert('Delete failed.'); return; }
    // Close modal if it was showing this job
    if (document.getElementById('modal-backdrop').classList.contains('open')) {
      document.getElementById('modal-backdrop').classList.remove('open');
    }
    loadReports();
  } catch { alert('Network error. Could not delete.'); }
});

/* ══════════════════════════════════════════════════════════════════════════
   REPORT DETAIL MODAL
══════════════════════════════════════════════════════════════════════════ */
async function openReportDetail(jobId) {
  const backdrop = document.getElementById('modal-backdrop');
  const bodyEl   = document.getElementById('modal-body');
  const ftEl     = document.getElementById('modal-ft');
  document.getElementById('modal-title').textContent = 'Loading…';
  document.getElementById('modal-sub').textContent   = '';
  bodyEl.innerHTML = '<div style="padding:20px;color:var(--text-secondary);font-size:13px;">Loading…</div>';
  ftEl.innerHTML   = '';
  backdrop.classList.add('open');

  try {
    const res = await fetch(`/history/${jobId}`);
    if (!res.ok) throw new Error('Not found');
    const job = await res.json();

    const co    = job.company_name || 'Unknown Company';
    const years = Array.isArray(job.fiscal_years) ? job.fiscal_years.join(', ') : '—';
    document.getElementById('modal-title').textContent = co;
    document.getElementById('modal-sub').textContent   = `${years} · ${job.currency||''} · ${job.unit||''}`;

    const sc = job.status === 'done' ? 'done' : job.status === 'error' ? 'error' : 'running';
    const sl = job.status === 'done' ? 'Completed' : job.status === 'error' ? 'Failed' : 'Running';

    let html = `<div style="margin-bottom:16px;"><span class="status-chip ${sc}"><span class="chip-dot"></span>${sl}</span></div>`;

    if (job.error) {
      html += `<div style="background:var(--error-dim);border:1px solid rgba(248,113,113,0.2);border-radius:var(--r-md);padding:12px;color:var(--error);font-size:13px;margin-bottom:16px;">${esc(job.error)}</div>`;
    }

    const SECTIONS = [
      ['executive_summary','Executive Summary'],
      ['revenue_analysis','Revenue Analysis'],
      ['profitability_analysis','Profitability Analysis'],
      ['balance_sheet_analysis','Balance Sheet Analysis'],
      ['cash_flow_analysis','Cash Flow Analysis'],
      ['key_risks','Key Risks'],
      ['key_strengths','Key Strengths'],
    ];

    if (job.commentary && typeof job.commentary === 'object') {
      html += SECTIONS.filter(([k]) => job.commentary[k]).map(([k, label]) => `
        <div class="modal-section">
          <div class="modal-sec-label">${label}</div>
          <div class="modal-sec-body">${esc(job.commentary[k])}</div>
        </div>`).join('');
    }

    if (job.next_steps?.length) {
      html += `<div class="modal-section"><div class="modal-sec-label">Recommended Next Steps</div>`;
      html += job.next_steps.map(s => {
        const p = (s.priority||'medium').toLowerCase();
        return `<div class="ns-item" style="margin-bottom:7px;">
          <span class="ns-badge ${p}">${p.toUpperCase()}</span>
          <div><div class="ns-title">${esc(s.title||'')}</div><div class="ns-desc">${esc(s.description||'')}</div></div>
        </div>`;
      }).join('') + '</div>';
    }

    bodyEl.innerHTML = html;

    // Footer actions
    const jid = esc(job.id), jco = esc(co);
    const dlR  = job.status==='done' && job.report_path ? `<a class="modal-btn primary" href="/download/${jid}/report" download>📘 Download Report</a>` : '';
    const dlX  = job.status==='done' && job.excel_path  ? `<a class="modal-btn secondary" href="/download/${jid}/excel" download>📗 Excel Model</a>`    : '';
    const chat = job.status==='done' ? `<button class="modal-btn secondary" onclick="closeModal(null);openReportChat('${jid}','${jco}')">💬 Chat</button>` : '';
    const del  = `<button class="modal-btn danger" style="margin-left:auto;" onclick="closeModal(null);confirmDelete('${jid}','${jco}')">🗑 Delete</button>`;
    ftEl.innerHTML = dlR + dlX + chat + del;

  } catch (e) {
    bodyEl.innerHTML = `<div style="padding:20px;color:var(--error);font-size:13px;">Failed to load: ${esc(e.message)}</div>`;
  }
}

function closeModal(e) {
  if (e && e.target !== document.getElementById('modal-backdrop')) return;
  document.getElementById('modal-backdrop').classList.remove('open');
}

function openReportChat(jobId, companyName) {
  showView('analyze');
  currentJobId = jobId; chatHistory = [];
  chatMessages.innerHTML = '';
  if (chatSubEl) chatSubEl.textContent = companyName || 'this company';
  appendChat('ai', `Hi! I have the analysis for **${companyName || 'this company'}** available. Ask me anything.`);
  chatWidget.style.display = 'block';
  openChatPanel();
}

/* ══════════════════════════════════════════════════════════════════════════
   CHAT
══════════════════════════════════════════════════════════════════════════ */
function openChatPanel() {
  chatPanelEl.classList.add('open');
  chatPanelOpen = true;
  chatUnread.classList.remove('show');
  chatFab.style.display = 'none';
  chatMessages.scrollTop = chatMessages.scrollHeight;
  chatInputEl.focus();
}
function closeChatPanel() {
  chatPanelEl.classList.remove('open');
  chatPanelOpen = false;
  chatFab.style.display = 'flex';
}

chatFab.addEventListener('click', openChatPanel);
chatClose.addEventListener('click', closeChatPanel);

function appendChat(role, text) {
  const isUser = role === 'user';
  const div    = document.createElement('div');
  div.className = `cmsg ${isUser ? 'user' : 'ai'}`;
  div.innerHTML = `
    <div class="cmsg-av">${isUser ? 'You' : 'AI'}</div>
    <div class="cmsg-bubble">${isUser ? esc(text) : md(text)}</div>`;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

function showTyping() {
  const d = document.createElement('div');
  d.className = 'cmsg ai'; d.id = 'chat-typing';
  d.innerHTML = `<div class="cmsg-av">AI</div>
    <div class="cmsg-bubble" style="padding:10px 12px;">
      <span class="tdot"></span><span class="tdot"></span><span class="tdot"></span>
    </div>`;
  chatMessages.appendChild(d);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}
function hideTyping() { const el=document.getElementById('chat-typing'); if(el) el.remove(); }

async function sendChat() {
  const text = chatInputEl.value.trim();
  if (!text || chatBusy || !currentJobId) return;
  chatInputEl.value = ''; chatInputEl.style.height = 'auto';
  chatBusy = true; chatSendBtn.disabled = true; chatInputEl.disabled = true;
  appendChat('user', text);
  chatHistory.push({ role:'user', content: text });
  showTyping();
  try {
    const res = await fetch(`/chat/${currentJobId}`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ message: text, history: chatHistory.slice(0,-1) }),
    });
    const data = await res.json();
    hideTyping();
    const reply = res.ok ? data.reply||'' : `⚠  ${esc(data.detail||'Failed to get a response.')}`;
    appendChat('ai', reply);
    if (res.ok) chatHistory.push({ role:'assistant', content: reply });
  } catch (err) {
    hideTyping(); appendChat('ai', `⚠  Network error: ${esc(err.message)}`);
  } finally {
    chatBusy = false; chatSendBtn.disabled = false; chatInputEl.disabled = false;
    chatInputEl.focus();
    if (!chatPanelOpen) chatUnread.classList.add('show');
  }
}

chatSendBtn.addEventListener('click', sendChat);
chatInputEl.addEventListener('keydown', e => { if (e.key==='Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } });
chatInputEl.addEventListener('input', () => {
  chatInputEl.style.height = 'auto';
  chatInputEl.style.height = Math.min(chatInputEl.scrollHeight, 90) + 'px';
});
