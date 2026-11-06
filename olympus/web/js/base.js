/* ============================================================================
   base.js — shared dashboard logic (utilities, header health, shared renderers)
   Split from app.js for the multi-page site. Loaded on every page.
   ========================================================================== */

'use strict';

/* Shared constants & task helpers used by more than one page. */

// Palette for agent nodes/rows (home cortex + system agents table).
const AGENT_COLORS = ['#8f7bff', '#c05cff', '#ff5ca8', '#ff9f45', '#e8b84b',
  '#4ade80', '#37c9a2', '#5cb8ff', '#7bd4ff', '#b08fff'];

// Poll a task until it finishes, then invoke onDone(task). Used by Jarvis
// (home) and the commerce deep-research verdict flow.
async function pollTask(id, onDone) {
  for (let i = 0; i < 120; i++) {
    const t = await j('/api/tasks/' + id);
    if (t.status === 'done' || t.status === 'failed') return onDone(t);
    await new Promise((r) => setTimeout(r, 2000));
  }
  onDone({ status: 'failed', error: 'timed out' });
}

/* -- 0. Utilities ---------------------------------------------------------- */

// Shorthand for document.getElementById
const $ = (id) => document.getElementById(id);

// JSON fetch: throws with the server's error body on any non-2xx response
async function j(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// POST a JSON body and parse the JSON response (consolidates the repeated
// fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body})
// pattern that used to appear on nearly every mutating call)
async function postJson(url, body) {
  return j(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// Escape a value for safe insertion into innerHTML
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s ?? '';
  return d.innerHTML;
}

// CSRF token from cookie + fetch wrapper that auto-attaches it to mutating calls
const _CSRF = (document.cookie.match(/(?:^|; )olympus_csrf=([^;]+)/) || [, ''])[1];
const _origFetch = window.fetch;
window.fetch = (url, opts = {}) => {
  const m = (opts.method || 'GET').toUpperCase();
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(m)) {
    const h = new Headers(opts.headers);
    h.set('x-csrf-token', _CSRF);
    opts.headers = h;
  }
  return _origFetch(url, opts);
};

// Strip control chars, collapse whitespace, and block prompt-injection phrases
function sanitizePromptInput(text) {
  if (typeof text !== 'string') return '';
  const stripped = text
    .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  const blocked = ['ignore previous', 'ignore all', 'disregard', 'system prompt',
    'you are now', 'act as', 'you are a', 'new instruction', 'override'];
  const lower = stripped.toLowerCase();
  for (const pattern of blocked) {
    if (lower.includes(pattern)) return '[filtered: prompt manipulation detected]';
  }
  return stripped.slice(0, 2000);
}

// Toggle a button into a disabled "LOADING…" state and back, preserving its label
function setLoading(element, isLoading) {
  if (!element) return;
  element.disabled = isLoading;
  element.style.opacity = isLoading ? '0.6' : '1';
  element.style.cursor = isLoading ? 'not-allowed' : 'pointer';
  if (isLoading) {
    element.dataset.originalText = element.textContent;
    element.textContent = 'LOADING…';
  } else if (element.dataset.originalText) {
    element.textContent = element.dataset.originalText;
  }
}

// Shared submit wrapper: disables the button, runs fn, restores the button.
// Cuts out the repeated try/catch/finally that used to exist on every form.
async function withLoading(btn, fn) {
  setLoading(btn, true);
  try {
    await fn();
  } catch (err) {
    alert('Error: ' + err.message);
  } finally {
    setLoading(btn, false);
  }
}

// One consolidated handler for "send text to an agent as a task" forms
function bindTaskForm(formId, btnSel, opts) {
  const form = $(formId);
  if (!form) return;
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = form.querySelector(btnSel);
    const input = $(opts.inputId);
    const text = input.value.trim();
    if (!text) return;
    await withLoading(btn, async () => {
      input.value = '';
      await postJson('/api/tasks', opts.body ? opts.body(text) : { text, agent: opts.agent });
      opts.onDone?.();
    });
  });
}


/* -- 1. Navigation ---------------------------------------------------------- */

// Multi-page navigation: each nav link is a real page under /pages/. goPage()
// remains as a helper for in-JS jumps (e.g. cortex search -> wiki).
function goPage(name) { location.href = '/' + name; }


/* -- 3. Health / systems / activity (shared, null-safe) -------------------- */

async function refreshHealth() {
  try {
    const h = await j('/api/health');
    window._health = h;
    const ha = $('hdr-agents'); if (ha) ha.textContent = h.agents;
    const ho = $('hdr-ollama'); if (ho) ho.innerHTML = h.ollama ? '<span class="ok">UP</span>' : '<span class="bad">DOWN</span>';
    const gps = $('gpu-stat');
    const g = h.gpu;
    if (gps) gps.textContent = g.available
      ? `GPU · ${(g.vram_used_mb / 1024).toFixed(1)}/${(g.vram_total_mb / 1024).toFixed(0)} GB`
      : 'GPU · FREE';
  } catch {
    const ho = $('hdr-ollama'); if (ho) ho.innerHTML = '<span class="bad">?</span>';
  }
}

// Service chip markup reused by the Automations, Studio, Voice and home panels
function serviceChip(s) {
  return `<span class="chip"><span class="${s.running ? 'ok' : 'bad'}">●</span> ${esc(s.name)}`
    + (s.running ? '' : `<button class="ghost" onclick="startSvc('${s.name}')">start</button>`)
    + `</span>`;
}

async function refreshSystems() {
  const svcs = await j('/api/services');
  const chips = svcs.map(serviceChip).join('');
  const as = $('auto-services'); if (as) as.innerHTML = chips;
  const ss = $('sys-services'); if (ss) ss.innerHTML = chips;

  // Home right-rail systems list (ollama cannot be restarted from here)
  const sb = $('systems-body');
  if (sb) sb.innerHTML = svcs.map((s) => {
    const noStart = s.name === 'ollama';
    return `<div class="sys-row">
      <span class="dot" style="background:${s.running ? 'var(--green)' : '#2a3a4a'}"></span>
      <span class="nm">${esc(s.name)}</span>
      ${s.running ? '<span class="st up">UP</span>'
        : `<span class="st down">DOWN</span>${noStart ? '' : `<button onclick="startSvc('${s.name}')">start</button>`}`}
    </div>`;
  }).join('');

  // Studio + Voice per-page status chips
  const voice = svcs.find((s) => s.name === 'voice');
  const vs = $('voice-status');
  if (vs) vs.innerHTML = `<span class="chip"><span class="${voice.running ? 'ok' : 'bad'}">●</span> Voice Studio ${voice.running ? 'UP' : 'DOWN'}`
    + (voice.running ? '' : '<button class="ghost" onclick="startSvc(\'voice\')">start</button>') + '</span>';
  if (voice.running && !window._voicesLoaded && typeof loadVoices === 'function') loadVoices();
}

async function startSvc(name) {
  await j(`/api/services/${encodeURIComponent(name)}/start`, { method: 'POST' });
  setTimeout(refreshSystems, 4000);
}

const STATUS_DOT = { done: 'var(--green)', failed: 'var(--pink)', running: 'var(--cyan)', queued: 'var(--gold)' };

// One kanban card for a task
function kcard(t) {
  return `<div class="kcard">
    <div class="khead"><span class="st-dot s-${t.status}"></span>
      <span class="kid">#${t.id}</span><span class="kagent">${esc(t.agent).toUpperCase()}</span></div>
    <div class="ktext">${esc(t.text).slice(0, 140)}</div>
    ${t.result || t.error ? `<div class="kres">${esc((t.result || t.error)).slice(0, 220)}</div>` : ''}
    <div class="kbtns">
      <button class="ghost" onclick="rerunTask(${t.id})">rerun</button>
      ${t.status === 'failed' ? `<button class="ghost" onclick="retryTask(${t.id})">retry</button>` : ''}
    </div></div>`;
}
async function rerunTask(id) { await j(`/api/tasks/${id}/rerun`, { method: 'POST' }); refreshTasks(); }
async function retryTask(id) { await j(`/api/tasks/${id}/retry`, { method: 'POST' }); refreshTasks(); }

async function refreshTasks() {
  const tasks = await j('/api/tasks');
  // Home right-rail activity feed (most recent 9)
  const ab = $('activity-body');
  if (ab) ab.innerHTML = tasks.slice(0, 9).map((t) =>
    `<div class="act-row">
       <span class="dot" style="background:${STATUS_DOT[t.status]}"></span>
       <span class="txt">${esc(t.text)}</span><span class="agent">${esc(t.agent)}</span>
     </div>`).join('') || '<span class="text-dim">no activity yet</span>';

  // Kanban columns by status
  const EMPTY_HINT = {
    queued: 'nothing queued — describe a goal above',
    running: 'nothing running',
    done: 'nothing done yet',
    failed: 'no failures — good',
  };
  for (const st of ['queued', 'running', 'done', 'failed']) {
    const list = tasks.filter((t) => t.status === st);
    const col = $(`col-${st}`); if (col) col.innerHTML = list.map(kcard).join('') || `<div class="text-dim mono-sm">${EMPTY_HINT[st]}</div>`;
    const cnt = $(`cnt-${st}`); if (cnt) cnt.textContent = list.length;
  }

  // Commerce page — Plutus-only tasks table
  const pr = $('plutus-rows');
  if (pr) pr.innerHTML = tasks.filter((t) => t.agent === 'plutus').map((t) =>
    `<tr><td>${t.id}</td>
       <td class="${t.status === 'done' ? 'ok' : t.status === 'failed' ? 'bad' : 'warn'}">${t.status}</td>
       <td>${esc(t.text).slice(0, 110)}</td><td class="kres kres-wide">${esc(t.result || t.error || '')}</td></tr>`
  ).join('');

  // Home briefing — most recent completed wrap/summary, else latest done task
  const brief = tasks.find((t) => t.status === 'done' && /brief|wrap|summary|\[PLAN\]/i.test(t.text))
    || tasks.find((t) => t.status === 'done');
  const bb = $('briefing-body');
  if (brief && bb) {
    bb.innerHTML =
      `<b># ${esc(brief.text.slice(0, 80))}</b>\n&gt; 🤖 ${esc(brief.agent)} · Olympus · ${esc(brief.updated)}\n\n${esc((brief.result || '').slice(0, 300))}`;
  }
}

// Reload everything that has a handler on the current page. Used by the System
// page's "reload agent registry" button; null-safe across pages.
async function refreshAll() {
  const jobs = [refreshHealth(), refreshSystems(), refreshTasks()];
  if (typeof refreshAgents === 'function') jobs.push(refreshAgents());
  if (typeof refreshSystemPage === 'function') jobs.push(refreshSystemPage());
  await Promise.all(jobs);
}

/* -- base boot (runs on every page) ----------------------------------------- */
refreshHealth();
setInterval(refreshHealth, 10000);

/* -- W.A.T. links: the ProDesk dashboards, next to the Olympus pages ------- */
// The W.A.T. shared nav bar links back here ("Studio"); this adds the way back.
// .wat names when browsing via studio.wat (private HTTPS), Tailscale IPs otherwise.
(function addWatLinks() {
  const nav = document.querySelector('header nav') || document.querySelector('nav');
  if (!nav || nav.querySelector('.wat-links')) return;
  const onWat = /\.wat$/i.test(location.hostname);
  const P = 'http://100.103.246.96';
  const links = [
    ['HUB', onWat ? 'https://hub.wat/' : P + ':3003/'],
    ['BOARD', onWat ? 'https://board.wat/' : P + ':8770/'],
    ['LIVE', onWat ? 'https://board.wat/live' : P + ':8770/live'],
    ['FAMILY', (onWat ? 'https://watos.wat' : P + ':8771') + '/shell/family.html'],
    ['WAT-OS', onWat ? 'https://watos.wat/' : P + ':8771/'],
  ];
  const sep = document.createElement('span');
  sep.className = 'wat-links';
  sep.textContent = '│ W.A.T.';
  sep.style.cssText = 'opacity:.55;margin:0 .2em 0 .6em;white-space:nowrap;font-size:.85em';
  nav.appendChild(sep);
  for (const [label, href] of links) {
    const a = document.createElement('a');
    a.href = href;
    a.textContent = label + ' ↗';
    a.style.whiteSpace = 'nowrap';
    a.title = 'W.A.T. (ProDesk): ' + href;
    nav.appendChild(a);
  }
})();
