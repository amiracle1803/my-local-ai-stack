/* ============================================================================
   OLYMPUS DASHBOARD — app.js
   ----------------------------------------------------------------------------
   Single-page dashboard logic. Organized top-to-bottom as:
      0.  Utilities (fetch helpers, escaping, CSRF, prompt sanitizer, forms)
      1.  Navigation
      2.  Home / Cortex knowledge graph
      3.  Health, systems, activity
      4.  Jarvis chat
      5.  Capture
      6.  Cortex search
      7.  Wiki browser
      8.  Tasks page
      9.  Commerce
     10.  Voice studio
     11.  Studio pipeline (stage grid, run controls, modals, artifact viewer)
     12.  System page
     13.  Boot (initial load + polling timers)
   ========================================================================== */

'use strict';

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

function goPage(name) {
  document.querySelector(`header nav a[data-page="${name}"]`).click();
}

// Wire up the top nav: swap the active page, and (re)load the wiki when opened
document.querySelectorAll('header nav a').forEach((a) =>
  a.addEventListener('click', () => {
    document.querySelectorAll('header nav a').forEach((x) => x.classList.remove('active'));
    document.querySelectorAll('.page').forEach((x) => x.classList.remove('active'));
    a.classList.add('active');
    $(`page-${a.dataset.page}`).classList.add('active');
    if (a.dataset.page === 'wiki') loadWiki(wikiFolder);
  })
);

/* -- 2. Home / Cortex knowledge graph --------------------------------------- */

const AGENT_COLORS = ['#8f7bff', '#c05cff', '#ff5ca8', '#ff9f45', '#e8b84b',
  '#4ade80', '#37c9a2', '#5cb8ff', '#7bd4ff', '#b08fff'];
const HOME_ROT_X = 0.25, HOME_VEL = 0.0018;

// Mutable state for the 3D-ish graph renderer (nodes, edges, camera, focus)
let cortex = {
  nodes: [], edges: [], nuclei: [], rotY: 0, rotX: HOME_ROT_X, vel: HOME_VEL,
  firing: -1, fireT: 0, lastDrag: 0, zoom: 1, zoomT: 1, userZoom: 1,
  userZoomT: 1, offX: 0, offY: 0, focus: -1, hover: -1, proj: [], _paused: false,
};

// Build the 3D-ish node/edge graph: agent nuclei + one node per vault note
function buildCortex(agents, notePaths) {
  const R = 1, nodes = [];
  // Place each agent as a "nucleus" distributed on a Fibonacci sphere
  agents.forEach((a, i) => {
    const phi = Math.acos(1 - 2 * (i + 0.5) / agents.length);
    const th = Math.PI * (1 + Math.sqrt(5)) * i;
    nodes.push({
      x: 0.55 * R * Math.sin(phi) * Math.cos(th), y: 0.55 * R * Math.cos(phi),
      z: 0.55 * R * Math.sin(phi) * Math.sin(th), r: 5.5,
      color: AGENT_COLORS[i % AGENT_COLORS.length], nucleus: true,
      name: a.name, label: a.name.toUpperCase(), desc: a.description,
    });
  });
  const nNuc = nodes.length;
  // Scatter one satellite node per vault note (capped) and tint near-nuclei ones
  const paths = (notePaths || []).slice(0, 240);
  const N = Math.max(paths.length, 120);
  for (let i = 0; i < N; i++) {
    const phi = Math.acos(1 - 2 * (i + 0.5) / N), th = Math.PI * (1 + Math.sqrt(5)) * i;
    const x = R * Math.sin(phi) * Math.cos(th) + (Math.random() - 0.5) * 0.25;
    const y = R * Math.cos(phi) + (Math.random() - 0.5) * 0.25;
    const z = R * Math.sin(phi) * Math.sin(th) + (Math.random() - 0.5) * 0.25;
    let best = 0, bd = 9;
    for (let k = 0; k < nNuc; k++) {
      const d = (x - nodes[k].x) ** 2 + (y - nodes[k].y) ** 2 + (z - nodes[k].z) ** 2;
      if (d < bd) { bd = d; best = k; }
    }
    const path = paths[i] || null;
    nodes.push({
      x, y, z, r: path ? 2.4 + Math.random() * 1.6 : 1.6 + Math.random() * 1.4,
      color: (bd < 0.55 && Math.random() < 0.55) ? nodes[best].color : '#a8d4f2',
      nucleus: false, cluster: best, path,
      label: path ? path.split('/').pop().replace(/\.md$/, '') : null,
    });
  }
  // Connect nearby satellites to each other and each satellite to its nucleus
  const edges = [];
  for (let i = nNuc; i < nodes.length; i++) {
    let bi = -1, bd = 9;
    for (let k = nNuc; k < nodes.length; k++) {
      if (k === i) continue;
      const d = (nodes[i].x - nodes[k].x) ** 2 + (nodes[i].y - nodes[k].y) ** 2 + (nodes[i].z - nodes[k].z) ** 2;
      if (d < bd) { bd = d; bi = k; }
    }
    if (bi >= 0 && bd < 0.5) edges.push([i, bi]);
    if (Math.random() < 0.35) edges.push([i, nodes[i].cluster]);
  }
  cortex.nodes = nodes; cortex.edges = edges; cortex.nuclei = nodes.slice(0, nNuc);
  const named = nodes.filter((n) => n.path).length;
  $('cortex-stats').textContent =
    `CORTEX · ${nodes.length} NODES (${named} NOTES) · ${edges.length} NERVES · ${nNuc} NUCLEI · LIVE`;
}

// Render one animation frame of the rotating knowledge graph
function drawCortex() {
  if (cortex._paused) return; // caller restarts when appropriate

  const cv = $('cortex'), ctx = cv.getContext('2d');
  const dpr = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (cv.width !== W * dpr || cv.height !== H * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const cx = W / 2, cy = H / 2;
  const now = performance.now();
  const focused = cortex.focus >= 0;

  // Ease spin/tilt toward the right resting state based on interaction
  if (focused) { cortex.vel += (0 - cortex.vel) * 0.08; cortex.zoomT = 1.85; }
  else if (cortex.dragging || cortex.hover >= 0) { cortex.vel += (0 - cortex.vel) * 0.25; cortex.zoomT = 1; }
  else {
    cortex.zoomT = 1;
    if (now - cortex.lastDrag > 3000) {
      cortex.rotX += (HOME_ROT_X - cortex.rotX) * 0.03;
      cortex.vel += (HOME_VEL - cortex.vel) * 0.03;
    }
  }
  cortex.zoom += (cortex.zoomT - cortex.zoom) * 0.07;
  cortex.userZoom += (cortex.userZoomT - cortex.userZoom) * 0.12;
  cortex.rotY += cortex.vel;
  const scale = Math.min(W * 0.62, H) * 0.42 * cortex.zoom * cortex.userZoom;
  const sy = Math.sin(cortex.rotY), cyr = Math.cos(cortex.rotY);
  const sx = Math.sin(cortex.rotX), cxr = Math.cos(cortex.rotX);

  // Project each 3D point to 2D with a simple perspective divide
  const raw = cortex.nodes.map((n) => {
    const x = n.x * cyr + n.z * sy, z = -n.x * sy + n.z * cyr, y = n.y;
    const y2 = y * cxr - z * sx, z2 = y * sx + z * cxr;
    const p = 1.6 / (1.6 + z2);
    return { X: cx + x * scale * p, Y: cy + y2 * scale * p, d: p, n };
  });

  // Ease pan so a focused node sits below the reader, else back to center
  if (focused) {
    const f = raw[cortex.focus];
    cortex.offX += ((cx - f.X) - cortex.offX) * 0.07;
    cortex.offY += ((cy + H * 0.18 - f.Y) - cortex.offY) * 0.07;
  } else {
    cortex.offX += (0 - cortex.offX) * 0.07;
    cortex.offY += (0 - cortex.offY) * 0.07;
  }
  const proj = raw.map((p) => ({ X: p.X + cortex.offX, Y: p.Y + cortex.offY, d: p.d, n: p.n }));
  cortex.proj = proj;

  // Draw edges (highlight ones linked to the currently "firing" agent)
  for (const [a, b] of cortex.edges) {
    const A = proj[a], B = proj[b];
    let alpha = 0.10 * Math.min(A.d, B.d), color = '150,190,220';
    if (cortex.firing >= 0 &&
        (cortex.nodes[a].cluster === cortex.firing || a === cortex.firing || b === cortex.firing)) {
      alpha += 0.35 * Math.max(0, 1 - (now - cortex.fireT) / 900);
      color = '190,160,255';
    }
    ctx.strokeStyle = `rgba(${color},${alpha})`;
    ctx.beginPath(); ctx.moveTo(A.X, A.Y); ctx.lineTo(B.X, B.Y); ctx.stroke();
  }

  // Draw nodes back-to-front so nearer ones overdraw
  const order = proj.map((p, i) => i).sort((a, b) => proj[a].d - proj[b].d);
  for (const i of order) {
    const p = proj[i];
    const hot = i === cortex.hover || i === cortex.focus;
    const r = p.n.r * p.d * 1.15 * (hot ? 1.6 : 1);
    ctx.beginPath();
    ctx.arc(p.X, p.Y, r, 0, 2 * Math.PI);
    ctx.fillStyle = p.n.color;
    ctx.globalAlpha = 0.35 + 0.65 * (p.d - 0.55) / 0.9;
    if (p.n.nucleus || hot) { ctx.shadowColor = p.n.color; ctx.shadowBlur = hot ? 20 : 14; }
    ctx.fill(); ctx.shadowBlur = 0; ctx.globalAlpha = 1;
  }

  // Label the hovered / focused node
  const lbl = cortex.hover >= 0 ? cortex.hover : cortex.focus;
  if (lbl >= 0 && cortex.nodes[lbl].label) {
    const p = proj[lbl], text = cortex.nodes[lbl].label;
    ctx.font = '11px Consolas, monospace';
    const w = ctx.measureText(text).width;
    ctx.fillStyle = 'rgba(6,10,18,.9)';
    ctx.fillRect(p.X + 10, p.Y - 18, w + 12, 18);
    ctx.strokeStyle = 'rgba(87,199,227,.4)';
    ctx.strokeRect(p.X + 10, p.Y - 18, w + 12, 18);
    ctx.fillStyle = '#9fe3f7';
    ctx.fillText(text, p.X + 16, p.Y - 5);
  }
  requestAnimationFrame(drawCortex);
}

// Periodically flash a random agent nucleus to simulate "routing" activity
setInterval(() => {
  if (!cortex.nuclei.length || cortex.focus >= 0) return;
  cortex.firing = Math.floor(Math.random() * cortex.nuclei.length);
  cortex.fireT = performance.now();
  const nuc = cortex.nuclei[cortex.firing];
  $('firing').textContent = `● ${nuc.name.toUpperCase()} FIRING`;
  $('firing').style.color = nuc.color;
}, 1700);

// Find the closest clickable (note or nucleus) node within a hit radius
function cortexHit(x, y) {
  let best = -1, bd = 14 * 14;
  for (let i = 0; i < cortex.proj.length; i++) {
    const p = cortex.proj[i];
    const d = (p.X - x) ** 2 + (p.Y - y) ** 2;
    if (d < bd && (cortex.nodes[i].path || cortex.nodes[i].nucleus)) { bd = d; best = i; }
  }
  return best;
}

// Focus a node: pause the graph and read its details in the floating panel
async function focusCortexNode(i) {
  const n = cortex.nodes[i];
  cortex.focus = i;
  cortex._paused = true;
  $('note-float').classList.add('open');
  if (n.nucleus) {
    // Agent nucleus → just show its description
    $('nf-title').textContent = 'AGENT · ' + n.label;
    $('nf-body').innerHTML =
      `<p>${esc(n.desc || '')}</p><p class="mono text-dim mono-xs mt-sm">click ✕ to release the cortex</p>`;
    return;
  }
  // Vault note → load and render its markdown
  $('nf-title').textContent = n.label;
  $('nf-body').innerHTML = '<em class="text-dim">reading…</em>';
  try {
    const note = await j('/api/brain/note?path=' + encodeURIComponent(n.path));
    $('nf-body').innerHTML = note.html || '<em>empty note</em>';
  } catch {
    $('nf-body').innerHTML = '<em>could not load this note</em>';
  }
}

function releaseCortex() {
  cortex.focus = -1;     // pan/zoom ease back to center automatically
  cortex.lastDrag = 0;   // resume default rotation immediately
  cortex._paused = false;
  $('note-float').classList.remove('open');
}

function cortexResume() {
  if (cortex._paused) { cortex._paused = false; requestAnimationFrame(drawCortex); }
}

// Resume the graph when the tab becomes visible again
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && cortex._paused && cortex.focus < 0) cortexResume();
});

$('nf-close').addEventListener('click', releaseCortex);
addEventListener('keydown', (e) => { if (e.key === 'Escape') releaseCortex(); });

// Canvas mouse interaction: drag to spin, wheel to zoom, click node to read
(() => {
  let drag = false, moved = 0, lx = 0, ly = 0;
  const cv = $('cortex');
  cv.addEventListener('wheel', (e) => {
    e.preventDefault();
    cortex.userZoomT = Math.min(3, Math.max(0.25, cortex.userZoomT * (e.deltaY > 0 ? 0.88 : 1.14)));
    cortex.lastDrag = performance.now(); // zooming counts as interaction: pause spin
  }, { passive: false });
  cv.addEventListener('dblclick', (e) => {
    const rect = cv.getBoundingClientRect();
    if (cortexHit(e.clientX - rect.left, e.clientY - rect.top) < 0) {
      cortex.userZoomT = 1;
      cortexResume();
    }
  });
  cv.addEventListener('mousedown', (e) => {
    drag = true; cortex.dragging = true; moved = 0; lx = e.clientX; ly = e.clientY;
    cv.style.cursor = 'grabbing';
  });
  addEventListener('mouseup', (e) => {
    if (drag && moved < 5 && e.target === cv) {
      const rect = cv.getBoundingClientRect();
      const hit = cortexHit(e.clientX - rect.left, e.clientY - rect.top);
      if (hit >= 0) focusCortexNode(hit);
      else if (cortex.focus >= 0) releaseCortex();
      else if (cortex._paused) cortexResume();
    }
    drag = false; cortex.dragging = false; cortex.lastDrag = performance.now();
    cv.style.cursor = 'grab';
  });
  addEventListener('mousemove', (e) => {
    if (drag) {
      moved += Math.abs(e.clientX - lx) + Math.abs(e.clientY - ly);
      cortex.rotY += (e.clientX - lx) * 0.005;
      cortex.rotX += (e.clientY - ly) * 0.003;
      cortex.lastDrag = performance.now();
    } else if (e.target === cv) {
      const rect = cv.getBoundingClientRect();
      const prev = cortex.hover;
      cortex.hover = cortexHit(e.clientX - rect.left, e.clientY - rect.top);
      if (prev >= 0 && cortex.hover < 0) cortex.lastDrag = performance.now();
      cv.style.cursor = cortex.hover >= 0 ? 'pointer' : 'grab';
    } else if (cortex.hover >= 0) { cortex.hover = -1; cortex.lastDrag = performance.now(); }
    lx = e.clientX; ly = e.clientY;
  });
})();

/* -- 3. Health / systems / activity ----------------------------------------- */

async function refreshHealth() {
  try {
    const h = await j('/api/health');
    window._health = h;
    $('hdr-agents').textContent = h.agents;
    $('hdr-ollama').innerHTML = h.ollama ? '<span class="ok">UP</span>' : '<span class="bad">DOWN</span>';
    const g = h.gpu;
    $('gpu-stat').textContent = g.available
      ? `GPU · ${(g.vram_used_mb / 1024).toFixed(1)}/${(g.vram_total_mb / 1024).toFixed(0)} GB`
      : 'GPU · FREE';
  } catch {
    $('hdr-ollama').innerHTML = '<span class="bad">?</span>';
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
  $('auto-services').innerHTML = chips;
  $('sys-services').innerHTML = chips;

  // Home right-rail systems list (ollama cannot be restarted from here)
  $('systems-body').innerHTML = svcs.map((s) => {
    const noStart = s.name === 'ollama';
    return `<div class="sys-row">
      <span class="dot" style="background:${s.running ? 'var(--green)' : '#2a3a4a'}"></span>
      <span class="nm">${esc(s.name)}</span>
      ${s.running ? '<span class="st up">UP</span>'
        : `<span class="st down">DOWN</span>${noStart ? '' : `<button onclick="startSvc('${s.name}')">start</button>`}`}
    </div>`;
  }).join('');

  // Studio + Voice per-page status chips
  const comfy = svcs.find((s) => s.name === 'comfyui');
  $('studio-status').innerHTML = `<span class="chip"><span class="${comfy.running ? 'ok' : 'bad'}">●</span> ComfyUI ${comfy.running ? 'UP' : 'DOWN'}`
    + (comfy.running ? '' : '<button class="ghost" onclick="startSvc(\'comfyui\')">start</button>') + '</span>';
  window._comfyUp = comfy.running;
  const voice = svcs.find((s) => s.name === 'voice');
  $('voice-status').innerHTML = `<span class="chip"><span class="${voice.running ? 'ok' : 'bad'}">●</span> Voice Studio ${voice.running ? 'UP' : 'DOWN'}`
    + (voice.running ? '' : '<button class="ghost" onclick="startSvc(\'voice\')">start</button>') + '</span>';
  if (voice.running && !window._voicesLoaded) loadVoices();
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
  $('activity-body').innerHTML = tasks.slice(0, 9).map((t) =>
    `<div class="act-row">
       <span class="dot" style="background:${STATUS_DOT[t.status]}"></span>
       <span class="txt">${esc(t.text)}</span><span class="agent">${esc(t.agent)}</span>
     </div>`).join('') || '<span class="text-dim">no activity yet</span>';

  // Kanban columns by status
  for (const st of ['queued', 'running', 'done', 'failed']) {
    const list = tasks.filter((t) => t.status === st);
    $(`col-${st}`).innerHTML = list.map(kcard).join('') || '<div class="text-dim mono-sm">empty</div>';
    $(`cnt-${st}`).textContent = list.length;
  }

  // Commerce page — Plutus-only tasks table
  $('plutus-rows').innerHTML = tasks.filter((t) => t.agent === 'plutus').map((t) =>
    `<tr><td>${t.id}</td>
       <td class="${t.status === 'done' ? 'ok' : t.status === 'failed' ? 'bad' : 'warn'}">${t.status}</td>
       <td>${esc(t.text).slice(0, 110)}</td><td class="kres kres-wide">${esc(t.result || t.error || '')}</td></tr>`
  ).join('');

  // Home briefing — most recent completed wrap/summary, else latest done task
  const brief = tasks.find((t) => t.status === 'done' && /brief|wrap|summary|\[PLAN\]/i.test(t.text))
    || tasks.find((t) => t.status === 'done');
  if (brief) {
    $('briefing-body').innerHTML =
      `<b># ${esc(brief.text.slice(0, 80))}</b>\n&gt; 🤖 ${esc(brief.agent)} · Olympus · ${esc(brief.updated)}\n\n${esc((brief.result || '').slice(0, 300))}`;
  }
}

async function refreshAgents() {
  window._agents = await j('/api/agents');
  buildCortex(window._agents, noteIndex || []);
  // once the vault index is loaded, rebuild so every neuron is a real note
  buildNoteIndex().then((idx) => buildCortex(window._agents, idx));
}

/* -- 4. Jarvis chat ---------------------------------------------------------- */

// Poll a task until it finishes (or times out), then call onDone
async function pollTask(id, onDone) {
  for (let i = 0; i < 120; i++) {
    const t = await j('/api/tasks/' + id);
    if (t.status === 'done' || t.status === 'failed') return onDone(t);
    await new Promise((r) => setTimeout(r, 2000));
  }
  onDone({ status: 'failed', error: 'timed out' });
}

// Speak a reply aloud via the voice TTS endpoint (fallback: browser synth)
async function speak(text) {
  if (!$('speak-replies').checked) return;
  try {
    const r = await fetch('/api/voice/tts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 400) }),
    });
    if (r.ok) { new Audio(URL.createObjectURL(await r.blob())).play(); return; }
  } catch { /* fall through to browser TTS */ }
  try { speechSynthesis.speak(new SpeechSynthesisUtterance(text.slice(0, 400))); } catch { /* ignore */ }
}

$('jarvis-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = $('jarvis-form').querySelector('button[type="submit"]');
  const text = $('jarvis-in').value.trim();
  if (!text) return;
  await withLoading(btn, async () => {
    $('jarvis-in').value = '';
    const log = $('jarvis-log');
    log.insertAdjacentHTML('beforeend', `<div class="jmsg you"><span class="who">YOU ›</span>${esc(text)}</div>`);
    const el = document.createElement('div');
    el.className = 'jmsg bot';
    el.innerHTML = '<span class="who">JARVIS ~</span><em class="text-dim">thinking…</em>';
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    $('jstatus').textContent = 'PROCESSING';
    $('jstatus').className = 'processing mono';
    const t = await postJson('/api/tasks', { text, agent: 'jarvis' });
    pollTask(t.id, (done) => {
      const reply = done.result || ('⚠ ' + (done.error || 'failed'));
      el.innerHTML = `<span class="who">JARVIS ~</span>${esc(reply)}<span class="tlink">→ task ${done.id ?? t.id}</span>`;
      log.scrollTop = log.scrollHeight;
      $('jstatus').textContent = 'ONLINE';
      $('jstatus').className = 'online mono';
      speak(reply);
      refreshTasks();
    });
  });
});

// Collapse / expand the Jarvis panel
$('jarvis-title').addEventListener('click', (e) => {
  if (e.target.tagName === 'INPUT') return;
  const p = $('jarvis-panel');
  p.classList.toggle('collapsed');
  $('jarvis-caret').textContent = p.classList.contains('collapsed') ? '▸' : '▾';
});

// Mic input via the Web Speech API where supported
$('mic-btn').addEventListener('click', () => {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { $('jarvis-in').placeholder = 'voice input not supported in this browser'; return; }
  const rec = new SR();
  rec.lang = 'en-US';
  rec.onresult = (e) => { $('jarvis-in').value = e.results[0][0].transcript; };
  rec.start();
});

/* -- 5. Capture -------------------------------------------------------------- */

$('capture-btn').addEventListener('click', () => {
  const v = $('capture-in').value.trim();
  if (!v) return;
  withLoading($('capture-btn'), async () => {
    $('capture-in').value = '';
    const sanitized = sanitizePromptInput(v);
    await postJson('/api/tasks', { text: 'Capture this note for the inbox: ' + sanitized, agent: 'archivist' });
    refreshTasks();
  });
});

/* -- 6. Cortex search --------------------------------------------------------- */

let noteIndex = null;
async function buildNoteIndex() {
  if (noteIndex) return noteIndex;
  noteIndex = [];
  async function walk(folder, depth) {
    let items;
    try { items = await j('/api/brain/notes?folder=' + encodeURIComponent(folder)); } catch { return; }
    for (const it of items) {
      const p = folder ? folder + '/' + it.name : it.name;
      if (it.type === 'note') noteIndex.push(p);
      else if (depth < 2) await walk(p, depth + 1);
    }
  }
  await walk('', 0);
  return noteIndex;
}

$('cortex-search').addEventListener('input', async (e) => {
  const q = e.target.value.trim().toLowerCase(), box = $('search-results');
  if (!q) { box.style.display = 'none'; return; }
  const idx = await buildNoteIndex();
  const hits = idx.filter((p) => p.toLowerCase().includes(q)).slice(0, 12);
  box.innerHTML = hits.map((p) => `<div data-p="${esc(p)}">📄 ${esc(p)}</div>`).join('')
    || '<div>no matches — press Enter to ask Archivist</div>';
  box.style.display = 'block';
  box.querySelectorAll('[data-p]').forEach((el) =>
    el.addEventListener('click', async () => {
      box.style.display = 'none';
      goPage('wiki');
      openWikiNote(el.dataset.p);
    }));
});

$('cortex-search').addEventListener('keydown', async (e) => {
  if (e.key !== 'Enter') return;
  const q = e.target.value.trim();
  if (!q) return;
  e.target.value = '';
  $('search-results').style.display = 'none';
  await postJson('/api/tasks', { text: 'Search the vault/wiki for: ' + q, agent: 'archivist' });
  refreshTasks();
});

/* -- 7. Wiki browser ----------------------------------------------------------- */

let wikiFolder = '', wikiItems = [], wikiNoteCache = {};

async function loadWiki(folder) {
  try { wikiItems = await j('/api/brain/notes?folder=' + encodeURIComponent(folder)); }
  catch { if (folder) return loadWiki(''); wikiItems = []; }
  wikiFolder = folder;
  // Breadcrumb trail; each segment is clickable to jump back up the tree
  const parts = folder ? folder.split('/') : [];
  $('wiki-crumb').innerHTML =
    '<span data-dir="">📂 vault root</span>' +
    parts.map((p, i) => {
      const d = parts.slice(0, i + 1).join('/');
      return `<span class="text-dim"> / </span><span data-dir="${esc(d)}">${esc(p)}</span>`;
    }).join('');
  $('wiki-crumb').querySelectorAll('[data-dir]').forEach((el) =>
    el.addEventListener('click', () => loadWiki(el.dataset.dir)));
  const fc = wikiItems.filter((i) => i.type === 'note').length;
  const dc = wikiItems.filter((i) => i.type === 'dir').length;
  $('wiki-count').textContent = `${fc} notes${dc ? ', ' + dc + ' folders' : ''}`;
  renderWiki();
}

function renderWiki() {
  const f = $('wiki-filter').value.trim().toLowerCase();
  const items = wikiItems.filter((it) => !f || it.name.toLowerCase().includes(f));
  const up = wikiFolder
    ? `<div class="wiki-up" data-dir="${esc(wikiFolder.split('/').slice(0, -1).join('/'))}">⬆ ..</div>` : '';
  $('wiki-files').innerHTML = up + items.map((it) => it.type === 'dir'
    ? `<div class="wiki-dir" data-dir="${esc(wikiFolder ? wikiFolder + '/' + it.name : it.name)}"><span class="wiki-ic">📁</span><div><b>${esc(it.name)}</b><div class="mono-xs text-dim">folder</div></div></div>`
    : `<div class="wiki-note" data-note="${esc(wikiFolder ? wikiFolder + '/' + it.name : it.name)}"><span class="wiki-ic">📄</span><div><b>${esc(it.name)}</b><div class="mono-xs text-dim">markdown note</div></div></div>`
  ).join('') || '<div class="sm-empty">nothing in this folder</div>';
  $('wiki-files').querySelectorAll('[data-dir]').forEach((el) =>
    el.addEventListener('click', () => loadWiki(el.dataset.dir)));
  $('wiki-files').querySelectorAll('[data-note]').forEach((el) =>
    el.addEventListener('click', () => openWikiNote(el.dataset.note)));
}

async function openWikiNote(path) {
  if (wikiNoteCache[path]) {
    $('wiki-note').innerHTML = `<div class="mono-sm text-cyan-dim mb-sm">${esc(path)}</div>` + wikiNoteCache[path];
    return;
  }
  $('wiki-note').innerHTML = '<em class="text-dim">loading…</em>';
  try {
    const n = await j('/api/brain/note?path=' + encodeURIComponent(path));
    wikiNoteCache[path] = n.html || '<em>empty note</em>';
    $('wiki-note').innerHTML = `<div class="mono-sm text-cyan-dim mb-sm">${esc(path)}</div>` + wikiNoteCache[path];
  } catch {
    $('wiki-note').innerHTML = '<em>could not load note — check vault path in stack.toml</em>';
  }
}
$('wiki-filter').addEventListener('input', renderWiki);

/* -- 8. Tasks page ------------------------------------------------------------- */

$('orchestrate-btn').addEventListener('click', () => {
  const goal = $('orchestrate-goal').value.trim();
  if (!goal) return;
  withLoading($('orchestrate-btn'), async () => {
    $('orchestrate-goal').value = '';
    await postJson('/api/orchestrate', { goal });
    refreshTasks();
  });
});

$('quick-btn').addEventListener('click', () => {
  const text = $('quick-task').value.trim();
  if (!text) return;
  withLoading($('quick-btn'), async () => {
    $('quick-task').value = '';
    await postJson('/api/tasks', { text });
    refreshTasks();
  });
});

// Hide finished cards (done + failed) off the board to reduce clutter. This is
// client-side only (no DELETE endpoint) so the next refreshTasks() restores them.
$('clear-done-btn').addEventListener('click', () => {
  const gone = document.querySelectorAll('#col-done .kcard, #col-failed .kcard').length;
  if (!gone) return;
  if (!confirm(`Hide ${gone} done/failed cards? (they reappear on the next refresh)`)) return;
  document.querySelectorAll('#col-done .kcard, #col-failed .kcard').forEach((c) => c.remove());
});

/* -- 9. Commerce ---------------------------------------------------------------- */

bindTaskForm('plutus-form', 'button[type="submit"]', {
  inputId: 'plutus-text', agent: 'plutus',
  onDone() { refreshTasks(); },
});

/* -- 10. Voice studio ------------------------------------------------------------- */

let selectedVoice = 'af_heart';

async function loadVoices() {
  try {
    const vs = await j('/api/voice/voices');
    window._voicesLoaded = true;
    $('voice-list').innerHTML = vs.map((v) =>
      `<div class="vrow ${v === selectedVoice ? 'sel' : ''}" data-v="${v}">
         <span class="vico">${v.split('_')[0].toUpperCase()}</span> ${esc(v)}</div>`).join('');
    $('voice-list').querySelectorAll('.vrow').forEach((el) =>
      el.addEventListener('click', () => {
        selectedVoice = el.dataset.v;
        $('voice-list').querySelectorAll('.vrow').forEach((x) =>
          x.classList.toggle('sel', x.dataset.v === selectedVoice));
      }));
  } catch { /* voice list unavailable until the service is up */ }
}

$('voice-speed').addEventListener('input', (e) =>
  $('speed-val').textContent = Number(e.target.value).toFixed(2));

$('voice-gen').addEventListener('click', () => {
  const text = $('voice-text').value.trim();
  if (!text) return;
  withLoading($('voice-gen'), async () => {
    const r = await fetch('/api/voice/tts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice: selectedVoice, speed: Number($('voice-speed').value) }),
    });
    if (!r.ok) throw new Error(await r.text());
    const url = URL.createObjectURL(await r.blob());
    const div = document.createElement('div');
    div.className = 'clip hud';
    div.innerHTML = `<div class="cmeta"><span>${esc(selectedVoice)}</span><span>x${$('voice-speed').value}</span>
        <span>${new Date().toLocaleTimeString()}</span>
        <a href="${esc(url)}" download="tts.wav" class="text-cyan">download</a>
        <button class="clip-del" title="remove">✕</button></div>
      <div class="mono-xs text-dim">${esc(text.slice(0, 120))}</div>
      <audio controls src="${esc(url)}"></audio>`;
    $('clips').prepend(div);
    // Revoke the blob URL once the clip is done/aborted, and allow deletion
    const audio = div.querySelector('audio');
    const revoke = () => URL.revokeObjectURL(url);
    audio.addEventListener('ended', revoke, { once: true });
    audio.addEventListener('abort', revoke, { once: true });
    div.querySelector('.clip-del').addEventListener('click', () => {
      revoke();
      div.remove();
    });
    audio.play();
  });
});

/* -- 11. Studio pipeline ------------------------------------------------------------ */

// 11a. Canonical stage metadata ---------------------------------------------
// The stage ids and ORDER mirror pipeline/blueprint.py STAGE_ORDER exactly, so
// the cards, gate checks and RUN ALL all reflect the real pipeline.
const STAGE_META = [
  { id: 'stage0',           icon: '📥', title: 'STAGE 0 · INTAKE',
    sst: 'script.txt → project blueprint · FPS 24–60 · story-pollution guard' },
  { id: 'stage0_dossier',   icon: '🗂️', title: 'STAGE 0D · DOSSIER',
    sst: 'rich intake extraction — characters, locations, 360-views, scene facts, dialogue log' },
  { id: 'stage1',           icon: '🌍', title: 'STAGE 1 · WORLD BIBLE',
    sst: 'chunked full-script character extraction · era/tech · relationships · outfits · contradictions' },
  { id: 'stage1_world',     icon: '🗺️', title: 'STAGE 1W · WORLD',
    sst: 'world enrichment — locations, era, magic, economy, lore, power system' },
  { id: 'stage1r',          icon: '👤', title: 'STAGE 1R · REFERENCES',
    sst: '10+ refs per character (360° full body) · locations + assets · style pick · voice ID' },
  { id: 'stage3',           icon: '🎞️', title: 'STAGE 2 · STORYBOARD',
    sst: 'scene blocks · last-frame seeds next · panel lock + regenerate · shot direction' },
  { id: 'stage2',           icon: '📝', title: 'STAGE 3A · SCREENPLAY',
    sst: 'narration + dialogue + SFX · composition prompts · pacing · quality audit' },
  { id: 'stage3b',          icon: '🎨', title: 'STAGE 3B · IMAGES',
    sst: 'one krea2 image per shot · same anchors = consistent characters' },
  { id: 'stage4',           icon: '🎙', title: 'STAGE 4 · AUDIO',
    sst: 'Kokoro TTS · narration + per-character voices · thinking pauses' },
  { id: 'stage3c',          icon: '🎞️', title: 'STAGE 3C · ANIMATION',
    sst: 'LTX-Video motion per panel → clips · motion tiers · facial anchors' },
  { id: 'stage_vlm_review', icon: '🔍', title: 'STAGE · VLM REVIEW',
    sst: 'vision-model consistency check · prompt-adherence scoring · blunder gating' },
  { id: 'stage5',           icon: '🎬', title: 'STAGE 5 · ASSEMBLY',
    sst: 'audio→frame timing · transitions · generated music · chapters/SRT · final MP4' },
];
const STAGE_IDS = STAGE_META.map((s) => s.id);
const STAGE_TITLES = Object.fromEntries(STAGE_META.map((s) => [s.id, s.title]));

// Human labels for the status dot tooltips + stage card sub-label
const STAGE_LABEL_MAP = {
  pending: 'pending — click RUN', running: '⏳ running…', done: '✓ done',
  failed: '✗ failed — click VIEW for log', awaiting_approval: '⏸ awaiting approval',
  not_built: '○ not built',
};

// Metrics that indicate a stage produced something questionable. The UI shows
// a warning badge on the stage card whenever any of these exceed a threshold.
// Each rule: [metricKey, test(value) -> bool, humanLabel]
const STAGE_WARNINGS = {
  stage0:    [['structure_completeness', (v) => v < 0.5, 'weak intake structure (<50%)']],
  stage1r:   [['failed_generations', (v) => v > 0, 'failed_generations refs failed'],
              ['refs_per_character', (v) => v > 0 && v < 10, 'too few refs/character (<10)']],
  stage3b:   [['vision_fail_rate', (v) => v > 0.3, 'high vision fail rate (>30%)'],
              ['panels_generated', (v) => v === 0, 'no panels generated']],
  stage3c:   [['ltx_failed', (v) => v > 0, 'LTX renders failed'],
              ['ltx_rendered', (v) => v === 0, 'no clips rendered']],
  stage4:    [['qc_flags', (v) => v > 0, 'QC flags raised'],
              ['lines_rendered', (v) => v === 0, 'no audio lines rendered']],
  stage_vlm_review: [['pass_rate', (v) => v === 0, '0% clips passed'],
              ['needs_review', (v) => v > 0, 'clips need review'],
              ['rejects', (v) => v > 0, 'clips rejected']],
  stage5:    [['missing_panels', (v) => v > 0, 'missing panels'],
              ['av_sync_error_ms', (v) => v > 200, 'AV sync error >200ms']],
};

// Build the warning text for a stage given its latest metrics
function stageWarnings(stage, metrics) {
  const rules = STAGE_WARNINGS[stage];
  if (!rules || !metrics) return '';
  return rules
    .filter(([key, test]) => metrics[key] !== undefined && test(metrics[key]))
    .map(([, , label]) => label)
    .join(' · ');
}

const DOT_CLASSES = new Set(['pending', 'running', 'done', 'failed', 'awaiting_approval', 'not_built']);
const INTAKE_HINTS = {
  '0b': 'GENERATE — from a creative brief (frontmatter word_target). Paste the brief below.',
  '0a': 'TRANSFORM — from a source story. Paste the source text below; the pipeline designs an original rewrite.',
  '0i': 'IMPORT — from existing panels (PNG/JPG/WEBP zip). Upload a zip below; the pipeline reads panels into a screenplay.',
};

let studioProject = localStorage.getItem('studio-project') || '';
let _studioBusy = false;

// Build a pipeline API URL for the active project. Centralizes the repeated
// '/api/pipeline/{slug}/...' string concatenation that was scattered everywhere.
const pipelineFor = (slug, path = '') =>
  `/api/pipeline/${encodeURIComponent(slug)}${path ? '/' + path : ''}`;
const pipeline = (path = '') => pipelineFor(studioProject, path);

function setBusy(busy) {
  _studioBusy = busy;
  $('run-all-btn').disabled = busy;
  document.querySelectorAll('.srun').forEach((b) => (b.disabled = busy));
  document.querySelectorAll('.sforce').forEach((b) => (b.disabled = busy));
}

function setLastMsg(text, kind) {
  const el = $('studio-last-msg');
  el.textContent = text || '';
  el.className = 'mono ' + (kind === 'ok' ? 'ok' : kind === 'err' ? 'err' : kind === 'warn' ? 'warn' : '');
}

// 11b. NIM model selector ------------------------------------------------------

async function loadNimModels() {
  try {
    const data = await j('/api/nim/models');
    const sel = $('studio-nim-select');
    if (!sel) return;
    sel.innerHTML = data.models.map((m) =>
      `<option value="${esc(m)}" ${m === data.active ? 'selected' : ''}>${esc(m)}${m === data.active ? ' ● active' : ''}</option>`
    ).join('');
    $('studio-nim-status').textContent = data.enabled ? '● enabled' : '○ disabled';
    $('studio-nim-status').style.color = data.enabled ? 'var(--green)' : 'var(--dim)';
  } catch {
    const sel = $('studio-nim-select');
    if (sel) sel.innerHTML = '<option>unavailable</option>';
  }
}

async function setNimModel(model) {
  const status = $('studio-nim-status');
  status.textContent = 'switching…';
  try {
    await postJson('/api/nim/model', { model });
    status.textContent = '● switched to ' + model.split('/').pop();
    status.style.color = 'var(--green)';
    setLastMsg('NIM model switched to ' + model + ' (permanent — saved to stack.toml)', 'ok');
    await loadNimModels();
  } catch (e) {
    status.textContent = '✗ ' + (e.message || e).slice(0, 60);
    status.style.color = 'var(--red)';
    alert('Failed to switch NIM model: ' + (e.message || e));
    await loadNimModels();
  }
}

// 11c. Project list / new project ------------------------------------------------

async function loadStudioProjects() {
  let projects = [];
  try { projects = await j('/api/pipeline/projects'); } catch { return projects; }
  const sel = $('studio-project-select');
  sel.innerHTML = projects.length
    ? projects.map((p) => `<option value="${esc(p.slug)}">${esc(p.slug)}</option>`).join('')
    : '<option value="">(no projects yet)</option>';
  if (!projects.find((p) => p.slug === studioProject)) studioProject = projects.length ? projects[0].slug : '';
  if (studioProject) { sel.value = studioProject; localStorage.setItem('studio-project', studioProject); }
  return projects;
}

$('studio-project-select').addEventListener('change', (e) => {
  studioProject = e.target.value;
  localStorage.setItem('studio-project', studioProject);
  setLastMsg('');
  pollStudioStatus();
});

$('studio-new-toggle').addEventListener('click', () => {
  const f = $('studio-new-form');
  f.style.display = f.style.display === 'none' ? 'block' : 'none';
  syncIntakeHint();
});

$('np-fps').addEventListener('input', (e) => ($('np-fps-val').textContent = e.target.value));
$('np-intake').addEventListener('change', syncIntakeHint);

// Update the placeholder + hidden panel fields based on the intake mode
function syncIntakeHint() {
  const intake = $('np-intake').value;
  const hint = $('np-intake-hint');
  if (hint) hint.textContent = INTAKE_HINTS[intake] || '';
  const text = $('np-text');
  if (intake === '0b') {
    text.placeholder = 'Creative brief (frontmatter: word_target: 600) — body: genre, tone, protagonist, themes, plot beats…';
    text.style.display = '';
    $('np-panels-file').style.display = 'none';
  } else if (intake === '0a') {
    text.placeholder = 'Source story text — the pipeline extracts mechanics and designs an original transformation…';
    text.style.display = '';
    $('np-panels-file').style.display = 'none';
  } else {
    text.placeholder = 'Optional: a one-line premise to seed the project (panels drive the real content)…';
    text.style.display = 'none';
    $('np-panels-file').style.display = '';
  }
}

$('studio-new-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('np-error').textContent = '';
  const slug = $('np-slug').value.trim();
  const fps = Number($('np-fps').value);
  const mode = document.querySelector('input[name="np-mode"]:checked').value;
  const intake = $('np-intake').value;
  const text = $('np-text').value;
  if (!slug) { $('np-error').textContent = 'slug is required'; return; }
  if (intake !== '0i' && !text.trim()) { $('np-error').textContent = 'brief / source text is required'; return; }
  const body = { slug, fps, mode: intake };
  if (mode === 'brief') body.brief_text = text; else body.script_text = text;
  try {
    await postJson('/api/pipeline/projects', body);
    // Optional panels upload for 0i — send as a separate call after creation
    const pf = $('np-panels-file').files[0];
    if (intake === '0i' && pf) await uploadPanels(slug, pf);
    $('np-slug').value = ''; $('np-text').value = ''; $('np-panels-file').value = '';
    $('studio-new-form').style.display = 'none';
    studioProject = slug;
    localStorage.setItem('studio-project', slug);
    await loadStudioProjects();
    pollStudioStatus();
    setLastMsg('project created — run the first stage or hit RUN ALL', 'ok');
  } catch (err) {
    $('np-error').textContent = 'failed: ' + (err.message || err).slice(0, 200);
  }
});

async function uploadPanels(slug, file) {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch(pipelineFor(slug, 'panels'), { method: 'POST', body: fd });
  if (!r.ok) throw new Error(await r.text());
}

// 11d. Stage grid render + gate health / warnings ---------------------------------

function pollStudioStatus() {
  if (!studioProject) {
    // No project selected — grey everything out
    STAGE_IDS.forEach((s) => {
      const d = $(`sdot-${s}`);
      if (d) d.className = 'sdot pending';
      const lb = $(`slabel-${s}`);
      if (lb) lb.textContent = 'no project';
      const card = document.querySelector(`.stage[data-stage="${s}"]`);
      if (card) card.style.opacity = '.55';
    });
    $('studio-project-meta').textContent = '';
    $('studio-progress').textContent = '';
    return;
  }
  j(pipeline('status'))
    .then((st) => {
      $('studio-project-meta').textContent =
        `fps ${st.fps} · mode ${st.mode || '0b'} · story_id ${st.story_id.slice(0, 8)}…`;
      // Animation disabled = panels mode: stage3c + clip VLM review are skipped
      // by the backend, so treat them as done-without-clips on the board (no
      // misleading "no clips rendered" / "0% passed" warnings).
      const animOff = st.animation_enabled === false;
      _animationEnabled = st.animation_enabled;
      renderAnimToggle();
      let done = 0, running = 0, failed = 0, warnings = 0;
      STAGE_IDS.forEach((s) => {
        const d = $(`sdot-${s}`);
        if (!d) return;
        const info = st.stages[s] || {};
        const status = DOT_CLASSES.has(info.status) ? info.status : 'pending';
        d.className = 'sdot ' + status;
        d.title = status + (info.error ? ': ' + info.error : '');
        const lb = $(`slabel-${s}`);
        if (lb) {
          if (animOff && (s === 'stage3c' || s === 'stage_vlm_review')) {
            lb.textContent = 'skipped · panels mode';
            lb.style.color = 'var(--cyan-dim)';
          } else {
            lb.textContent = STAGE_LABEL_MAP[status] || status;
            lb.style.color = status === 'done' ? 'var(--green)'
              : status === 'failed' ? 'var(--red)'
              : status === 'running' ? 'var(--cyan)' : 'var(--dim)';
          }
        }
        const card = document.querySelector(`.stage[data-stage="${s}"]`);
        if (card) {
          card.style.opacity = status === 'done' ? '1' : status === 'running' ? '1' : '.92';
          card.style.borderColor = status === 'failed' ? 'rgba(239,107,115,.5)'
            : status === 'running' ? 'var(--cyan)' : '';
        }
        // Warning badge: metrics problem OR missing mandatory proof metrics
        // (suppressed entirely for the skipped animation stages in panels mode)
        const w = animOff && (s === 'stage3c' || s === 'stage_vlm_review')
          ? '' : stageWarnings(s, info.metrics);
        const missingArr = info.missing_metrics || [];
        const warnText = [w, missingArr.length ? `missing proof: ${missingArr.join(', ')}` : ''].filter(Boolean).join(' · ');
        const wb = $(`swarn-${s}`);
        if (wb) {
          wb.style.display = warnText ? 'block' : 'none';
          wb.title = warnText || 'no warnings';
          if (warnText) warnings++;
        }
        if (status === 'done') done++;
        if (status === 'running') running++;
        if (status === 'failed') failed++;
      });
      const total = STAGE_IDS.length;
      $('studio-progress').textContent = running
        ? `${done}/${total} done · ${running} running — polling…`
        : failed ? `${done}/${total} done · ${failed} failed`
        : `${done}/${total} stages complete${done === total ? ' — ✓ pipeline complete!' : ''}`
        + (warnings ? ` · ⚠ ${warnings} flagged` : '');
      if (failed) setLastMsg(`${failed} stage(s) failed — click VIEW on red cards for logs, or FORCE to retry`, 'err');
      else if (warnings) setLastMsg(`${warnings} stage(s) flagged — click VIEW to inspect`, 'warn');
      else if (running) setLastMsg(`running… ${done}/${total} done`, '');
    })
    .catch((e) => { /* project may not exist yet / kernel hiccup — skip tick */
      if (window.__olympusDebug) console.error('pollStudioStatus:', e);
    });
}

// Render the stage grid once (called at boot). Cards are generated from
// STAGE_META so the grid always matches the canonical pipeline order.
function renderStageGrid() {
  $('stage-grid').innerHTML = STAGE_META.map((m) => `
    <div class="stage hud" data-stage="${m.id}">
      <span class="swarn" id="swarn-${m.id}" title="" style="display:none">⚠</span>
      <div class="sdot" id="sdot-${m.id}"></div>
      <div class="sic">${m.icon}</div>
      <div class="snm">${m.title}</div>
      <div class="sst">${m.sst}</div>
      <div class="sst-label" id="slabel-${m.id}">pending — click RUN to start</div>
      <div class="sbtns">
        <button class="ghost srun" data-stage="${m.id}">RUN ▶</button>
        <button class="ghost sview" data-stage="${m.id}">VIEW</button>
        <button class="ghost sforce" data-stage="${m.id}" title="Force rerun">FORCE</button>
      </div>
    </div>`).join('');

  // Card click opens the viewer (unless a button was pressed)
  document.querySelectorAll('.stage').forEach((card) => {
    card.addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      openStageModal(card.dataset.stage);
    });
  });
  // Per-stage buttons: RUN / VIEW / FORCE
  document.querySelectorAll('.srun').forEach((btn) =>
    btn.addEventListener('click', (e) => { e.stopPropagation(); runStage(btn.dataset.stage, false); }));
  document.querySelectorAll('.sview').forEach((btn) =>
    btn.addEventListener('click', (e) => { e.stopPropagation(); openStageModal(btn.dataset.stage); }));
  document.querySelectorAll('.sforce').forEach((btn) =>
    btn.addEventListener('click', (e) => { e.stopPropagation(); runStage(btn.dataset.stage, true); }));
}

// 11e. Run / run-all / per-stage controls ----------------------------------------

async function runStage(stage, force = false) {
  if (_studioBusy) { alert('a run is already in progress — wait for it to finish'); return; }
  if (!studioProject) { alert('create or select a project first'); return; }
  if (force && !confirm(`Force rerun ${stage}? This will clear its previous outputs and run it again even though it is marked done.`)) return;
  setBusy(true);
  setLastMsg(`${stage} ${force ? 'force rerunning' : 'running'}…`, '');
  try {
    // stage0 intake needs its inputs (brief/source/panels) — open the setup modal
    if (stage === 'stage0') {
      await openStage0Setup(false, force);
    } else {
      await postJson(pipeline('run/' + stage), { force });
      setLastMsg(`${stage} ${force ? 'force started' : 'started'}`, 'ok');
    }
  } catch (err) {
    setLastMsg(`${stage} failed to start: ` + (err.message || err).slice(0, 200), 'err');
    alert(stage + ' run failed: ' + (err.message || err).slice(0, 300));
  } finally {
    setBusy(false);
    pollStudioStatus();
  }
}

async function runAll() {
  if (_studioBusy) { alert('a run is already in progress — wait for it to finish'); return; }
  if (!studioProject) { alert('create or select a project first'); return; }
  const step = $('studio-step-check')?.checked || false;
  const what = step ? 'the next stage' : 'all remaining stages';
  if (!confirm(`Run ${what} in order?${step ? ' The pipeline will stop after this stage so you can review before continuing.' : ' This resumes from where the project left off.'}`)) return;
  setBusy(true);
  setLastMsg(`running ${what}…`, '');
  try {
    // If stage0 hasn't produced intake yet, collect its inputs through the same
    // modal the per-stage run uses, then hand them to /run-all so any intake
    // mode (0b/0a/0i) works end-to-end.
    let body = {};
    const st = await j(pipeline('status'));
    const s0 = (st.stages && st.stages.stage0) || {};
    if ((st.mode || '0b') !== '0b' || s0.status !== 'done') {
      const intake = await openStage0Setup(true);
      if (!intake) { setBusy(false); setLastMsg('full run cancelled', ''); return; }
      body = intake;
    }
    body.step = step;
    await postJson(pipeline('run-all'), body);
    setLastMsg(step
      ? `stage running — the pipeline will stop after it completes; then hit RUN NEXT / CONTINUE`
      : 'full run started — poll the stage dots / open the video tab when done', 'ok');
  } catch (err) {
    setLastMsg('run-all failed to start: ' + (err.message || err).slice(0, 200), 'err');
    alert(err.message || err);
  } finally {
    setBusy(false);
    pollStudioStatus();
  }
}

// 11f. Stage0 intake setup modal -------------------------------------------------
// collectOnly=true resolves with the intake inputs WITHOUT starting a run; used
// by RUN ALL so it can hand the same brief/source/panels to /run-all.
// force=true sends the force flag so a completed stage0 is cleared + re-run.
function openStage0Setup(collectOnly = false, force = false) {
  return new Promise((resolve) => {
    $('setup-title').textContent = 'STAGE 0 · INTAKE (' + (studioProject || 'project') + ')' + (force ? ' — FORCE RERUN' : '');
    const body = $('setup-body');
    j(pipeline('status')).then((st) => {
      const mode = st.mode || '0b';
      body.innerHTML = `
        <div class="sm-hint">${esc(INTAKE_HINTS[mode] || '')}</div>
        <div class="sm-step">PROJECT</div>
        <div class="sm-hint">slug: <b>${esc(studioProject)}</b> · fps ${st.fps} · mode ${esc(mode)}</div>
        ${mode === '0b' ? `
          <div class="sm-step">CREATIVE BRIEF</div>
          <textarea id="setup-brief" placeholder="---&#10;word_target: 800&#10;---&#10;&#10;Genre, tone, protagonist, themes, plot beats…">${esc($('np-text').value)}</textarea>` : ''}
        ${mode === '0a' ? `
          <div class="sm-step">SOURCE TEXT</div>
          <textarea id="setup-source" placeholder="Paste the source story text here…"></textarea>
          <div class="sm-hint" style="margin-top:.4rem">word target: <input type="number" id="setup-wordtarget" value="800" min="200" step="50" style="width:90px;background:#0b1522;color:#cfe3f0;border:1px solid var(--line)"></div>` : ''}
        ${mode === '0i' ? `
          <div class="sm-step">PANEL UPLOAD</div>
          <input type="file" id="setup-panels" accept=".zip,.png,.jpg,.jpeg,.webp" multiple>
          <div class="sm-hint" style="margin-top:.4rem">Upload a .zip (or a folder of panels). If panels were already attached at project creation, leave empty to reuse them.</div>` : ''}
        <div class="flex mt-sm">
          <button class="primary" id="setup-run">${collectOnly ? 'USE FOR FULL RUN ▶' : 'RUN STAGE 0 ▶'}</button>
          <button class="ghost" id="setup-close2">CANCEL</button>
          <span id="setup-error"></span>
        </div>`;
      $('setup-modal').classList.add('open');
      // Use onclick (not addEventListener) for the dismiss controls so repeated
      // modal openings never stack duplicate handlers and each resolves once.
      $('setup-close').onclick = () => { $('setup-modal').classList.remove('open'); resolve(false); };
      $('setup-close2').onclick = () => { $('setup-modal').classList.remove('open'); resolve(false); };
      $('setup-modal').onclick = (e) => {
        if (e.target === $('setup-modal')) { $('setup-modal').classList.remove('open'); resolve(false); }
      };
      $('setup-run').onclick = async () => {
        const errEl = $('setup-error');
        errEl.textContent = '';
        try {
          const out = {};
          if (mode === '0b') {
            const brief = ($('setup-brief') || {}).value || '';
            if (!brief.trim()) throw new Error('brief is required');
            out.brief = brief;
          } else if (mode === '0a') {
            const source = ($('setup-source') || {}).value || '';
            if (!source.trim()) throw new Error('source text is required');
            out.source_text = source;
            out.word_target = Number(($('setup-wordtarget') || {}).value || 800);
          } else if (mode === '0i') {
            const pf = ($('setup-panels') || {}).files && $('setup-panels').files[0];
            if (pf) await uploadPanels(studioProject, pf);
          }
          if (collectOnly) { $('setup-modal').classList.remove('open'); resolve(out); return; }
          await postJson(pipeline('run/stage0'), { ...out, force });
          $('setup-modal').classList.remove('open');
          setLastMsg(force ? 'stage0 force rerun started' : 'stage0 started', 'ok');
          resolve(true);
        } catch (err) {
          errEl.textContent = (err.message || err).slice(0, 250);
        }
      };
    }).catch((err) => {
      body.innerHTML = '<div class="sm-errline">error loading status: ' + esc(err.message) + '</div>';
      resolve(false);
    });
  });
}

// 11g. Stage artifact viewer ----------------------------------------------------------

const smModal = $('stage-modal'), smBody = $('stage-modal-body'), smTitle = $('stage-modal-title');

// Render a metric chip row
function smTags(metrics) {
  if (!metrics) return '';
  const m = Object.entries(metrics).map(([k, v]) =>
    `<span>${esc(k)} <b>${typeof v === 'number' ? v.toLocaleString() : esc(v)}</b></span>`).join('');
  return m ? `<div class="sm-metrics">${m}</div>` : '';
}

// URL to stream one artifact file for the current project
function smUrl(path) { return pipeline('file?path=' + encodeURIComponent(path)); }

// Render one image/video/audio artifact tile
function smFile(a) {
  const src = smUrl(a.path);
  if (a.kind === 'image') return `<div class="sm-item"><img loading="lazy" src="${esc(src)}" alt="${esc(a.name)}"><div class="sm-cap">${esc(a.name)}</div></div>`;
  if (a.kind === 'video') return `<div class="sm-item"><video controls src="${esc(src)}"></video><div class="sm-cap">${esc(a.name)}</div></div>`;
  if (a.kind === 'audio') return `<div class="sm-item"><audio controls src="${esc(src)}"></audio><div class="sm-cap">${esc(a.name)}</div></div>`;
  return '';
}

// Fetch and pretty-print a JSON document artifact for the raw viewers
function smDocHtml(path) {
  return `<h3 class="mono-sm text-cyan">${esc(path)}</h3><pre class="sm-doc" data-doc-path="${esc(path)}">loading…</pre>`;
}

// ---- Human-readable viewers ---------------------------------------------------
// Each returns a string of HTML given the artifact index list. They turn the
// raw JSON docs into cards/tables so you can "see what happened" per stage.

// Shared: reduce a possibly-array / possibly-object JSON value to an array
const asList = (v) => (Array.isArray(v) ? v : Object.values(v || {}));

async function viewStage0(list) {
  let html = '';
  const sceneFile = list.find((a) => a.path === 'stage0_scenes.json');
  const scriptFile = list.find((a) => a.path === 'input/script.txt');
  if (scriptFile) {
    html += `<div class="sm-section-title">SCRIPT</div>
      <h3 class="mono-sm text-cyan">${esc(scriptFile.name)}</h3><pre class="sm-doc" data-doc-path="${esc(scriptFile.path)}">loading…</pre>`;
  }
  if (sceneFile) {
    html += `<div class="sm-section-title">SCENE BREAKDOWN</div>`;
    try {
      const scenes = await fetchJson(sceneFile.path);
      const sceneList = asList(scenes);
      if (sceneList.length) {
        html += sceneList.map((sc, i) => `<div class="char-card">
          <div class="cname">SCENE ${i + 1}</div>
          <div class="crole">${esc(sc.location || sc.setting || sc.scene_heading || '')}</div>
          <div class="capp">${esc(sc.summary || sc.synopsis || sc.description || sc.content || '')}</div>
        </div>`).join('');
      } else html += '<div class="sm-empty">empty scene list</div>';
    } catch { html += smDocHtml(sceneFile.path); }
  }
  return html;
}

async function viewWorldBible(list) {
  let html = '';
  const wb = list.find((a) => a.path === 'worldbible/world_bible.json');
  const contra = list.find((a) => a.path === 'worldbible/contradictions.json');
  if (wb) {
    html += `<div class="sm-section-title">CHARACTERS · LOCATIONS · WORLD</div>`;
    try {
      const data = await fetchJson(wb.path);
      const charList = asList(data.characters);
      if (charList.length) {
        html += charList.map((c) => {
          const ap = c.appearance || {};
          const appText = [ap.hair, ap.eyes, ap.skin, ap.build, ap.clothing_primary]
            .filter(Boolean).join(' · ');
          return `<div class="char-card">
            <div class="cname">${esc(c.name || c.id)}</div>
            <div class="crole">${esc(c.role || '')}</div>
            ${c.aliases && c.aliases.length ? `<div class="mono-xs text-dim">aka: ${esc(c.aliases.join(', '))}</div>` : ''}
            <div class="capp">${esc(appText || '')}</div>
            ${c.sd_prompt ? `<div class="csd">${esc(c.sd_prompt)}</div>` : ''}
          </div>`;
        }).join('');
      }
      const locList = asList(data.locations);
      if (locList.length) {
        html += `<div class="sm-section-title">LOCATIONS</div>`;
        html += locList.map((l) => `<div class="char-card"><div class="cname">${esc(l.name || l.id)}</div>
          <div class="capp">${esc((l.description || '').slice(0, 200))}</div></div>`).join('');
      }
    } catch { html += smDocHtml(wb.path); }
  }
  if (contra) html += `<div class="sm-section-title">CONTRADICTIONS</div>` + smDocHtml(contra.path);
  return html;
}

async function viewStoryboard(list) {
  let html = '';
  const sb = list.find((a) => a.path === 'storyboard/storyboard.json');
  if (sb) {
    html += `<div class="sm-section-title">STORYBOARD</div>`;
    try {
      const data = await fetchJson(sb.path);
      // Blocks are the high-level scene groupings
      if (Array.isArray(data.blocks)) {
        html += data.blocks.map((b, i) => `<div class="block-card">
          <div class="cname">BLOCK ${i + 1}</div>
          <div class="capp">${esc(b.summary || b.description || b.title || '')}</div>
        </div>`).join('');
      }
      // shot_detail is the per-shot breakdown (id, tier, direction, prompt)
      const shotList = asList(data.shot_detail);
      if (shotList.length) {
        html += `<div class="sm-section-title">SHOTS (${shotList.length})</div>`;
        html += shotList.map((s) => {
          const tier = s.tier !== undefined ? `tier ${s.tier}` : '';
          return `<div class="shot-card"><div class="cname">${esc(s.id || s.shot_id || 'shot')} ${tier ? `<span class="text-dim">· ${tier}</span>` : ''}</div>
            <div class="capp">${esc(s.direction || s.description || s.prompt || '')}</div></div>`;
        }).join('');
      }
    } catch { html += smDocHtml(sb.path); }
  }
  return html;
}

async function viewScreenplay(list) {
  let html = '';
  const sp = list.find((a) => a.path === 'screenplay/screenplay.json');
  if (sp) {
    html += `<div class="sm-section-title">SCREENPLAY</div>`;
    try {
      const data = await fetchJson(sp.path);
      const scenes = Array.isArray(data.scenes) ? data.scenes : [];
      if (scenes.length) {
        html += scenes.map((sc, i) => {
          const shots = Array.isArray(sc.shots) ? sc.shots : [];
          const shotHtml = shots.map((sh) => {
            const parts = [];
            if (sh.narration) parts.push(`<div class="text-cyan"><b>NARRATION:</b> ${esc(sh.narration)}</div>`);
            if (sh.dialogue) parts.push(`<div><b>${esc(sh.character || 'DIALOGUE')}:</b> ${esc(sh.dialogue)}</div>`);
            if (sh.sfx) parts.push(`<div class="text-gold"><b>SFX:</b> ${esc(sh.sfx)}</div>`);
            if (sh.description) parts.push(`<div class="text-dim">${esc(sh.description)}</div>`);
            return parts.join('') ? `<div class="shot-card">${parts.join('')}</div>` : '';
          }).join('');
          return `<div class="block-card"><div class="cname">SCENE ${i + 1}</div>
            <div class="crole">${esc(sc.location || sc.heading || '')}</div>
            ${sc.summary ? `<div class="capp">${esc(sc.summary)}</div>` : ''}
            ${shotHtml}</div>`;
        }).join('');
      } else html += smDocHtml(sp.path);
    } catch { html += smDocHtml(sp.path); }
  }
  return html;
}

// Simple "gallery of a given media kind" viewers (images / animation / audio)
async function viewMedia(list, kind, emptyMsg) {
  const items = list.filter((a) => a.kind === kind);
  if (!items.length) return `<div class="sm-empty">${emptyMsg}</div>`;
  return `<div class="sm-grid">${items.map(smFile).join('')}</div>`;
}

// Stage 3B viewer: show the manga vertical page(s) first, then the individual
// panels in story order. The manga composite stacks every block's panels
// one-under-the-other (webtoon style) so the whole scene reads like manga.
async function viewPanels(list) {
  let html = '';
  const manga = list.filter((a) => a.path.endsWith('_manga.png'));
  if (manga.length) {
    html += `<div class="sm-section-title">MANGA PAGE (one panel under the next)</div>`;
    html += manga.map((a) => `<div class="sm-item manga-page" style="margin-bottom:1rem"><img loading="lazy" src="${esc(smUrl(a.path))}" alt="${esc(a.name)}"><div class="sm-cap">${esc(a.name)}</div></div>`).join('');
  }
  const panels = list.filter((a) => a.kind === 'image' && !a.path.endsWith('_manga.png'));
  if (panels.length) {
    html += `<div class="sm-section-title">PANELS (${panels.length})</div>`;
    html += `<div class="sm-grid">${panels.map(smFile).join('')}</div>`;
  }
  if (!html) return `<div class="sm-empty">no panel images generated yet — run stage 3B</div>`;
  return html;
}

async function viewVlmReview(list) {
  let html = '';
  const vr = list.find((a) => a.path === 'reviews/vlm_review.json');
  if (vr) {
    html += `<div class="sm-section-title">VLM REVIEW</div>`;
    try {
      const data = await fetchJson(vr.path);
      // summary header
      if (data.total_clips !== undefined) {
        html += `<div class="sm-metrics">
          <span>total_clips <b>${data.total_clips}</b></span>
          <span>reviewed <b>${data.reviewed ?? data.reviews ? Object.keys(data.reviews || {}).length : '?'}</b></span>
          <span>pass <b>${data.pass ?? ''}</b></span>
          <span>reject <b>${data.reject ?? ''}</b></span>
          <span>avg_score <b>${data.avg_score ?? ''}</b></span>
          <span>pass_rate <b>${data.pass_rate ?? ''}</b></span>
        </div>`;
      }
      // per-clip reviews table
      const rev = data.reviews;
      if (rev && typeof rev === 'object') {
        html += `<div class="sm-section-title">PER-CLIP SCORES</div>`;
        html += Object.entries(rev).map(([clipId, r]) => {
          const score = Number(r.overall_score || 0);
          const barClass = score >= 8 ? 'green' : score >= 5 ? 'gold' : 'red';
          const verdict = String(r.verdict || 'REVIEW').toLowerCase();
          const details = r.details && typeof r.details === 'object'
            ? Object.entries(r.details).map(([k, v]) => `<span>${esc(k)} <b>${v}</b></span>`).join('')
            : '';
          return `<div class="review-card">
            <div class="rv-head"><span class="mono-sm text-cyan">${esc(clipId)}</span>
              <span class="rv-verdict ${esc(verdict)}">${esc(String(r.verdict || 'REVIEW'))}</span>
              <span class="mono-sm text-dim auto-left">score <b>${score}</b></span></div>
            <div class="scorebar ${barClass}" style="margin-top:.3rem"><i style="width:${Math.max(2, Math.min(100, score * 10))}%"></i></div>
            ${details ? `<div class="rv-details">${details}</div>` : ''}
            ${r.raw_response ? `<div class="rv-raw">${esc(r.raw_response.slice(0, 300))}</div>` : ''}
          </div>`;
        }).join('');
      }
    } catch { html += smDocHtml(vr.path); }
  }
  return html;
}

async function viewAssembly(list) {
  let html = '';
  const vid = list.find((a) => a.kind === 'video');
  if (vid) html += `<div class="sm-section-title">FINAL VIDEO</div>` + smFile(vid);
  const srt = list.find((a) => a.path === 'video/final.srt');
  const chapters = list.find((a) => a.path === 'video/chapters.ffmetadata');
  if (srt) html += `<div class="sm-section-title">SUBTITLES (.srt)</div>` + smDocHtml(srt.path);
  if (chapters) html += `<div class="sm-section-title">CHAPTERS</div>` + smDocHtml(chapters.path);
  return html;
}

// Map each stage to its human-readable viewer; fall back to a plain JSON doc
const STAGE_VIEWERS = {
  stage0: viewStage0, stage0_dossier: viewWorldBible, stage1: viewWorldBible,
  stage1_world: viewWorldBible, stage1r: (l) => viewMedia(l, 'image', 'no reference images generated yet — run stage 1R'),
  stage3: viewStoryboard, stage2: viewScreenplay,
  stage3b: viewPanels,
  stage4: (l) => viewMedia(l, 'audio', 'no audio rendered yet — run stage 4'),
  stage3c: (l) => viewMedia(l, 'video',
    _animationEnabled === false
      ? 'Animation is OFF (panels mode) — panels were assembled with Ken Burns zoom/pan + fades in stage 5. Enable ANIMATION in the banner to render LTX/Wan clips here.'
      : 'no animation clips yet — run stage 3C'),
  stage_vlm_review: viewVlmReview, stage5: viewAssembly,
};

async function fetchText(path) {
  const r = await fetch(smUrl(path));
  if (!r.ok) throw new Error('fetch failed');
  return r.text();
}
async function fetchJson(path) { return JSON.parse(await fetchText(path)); }

function loadStageArtifacts(stage, arts, st) {
  smBody.innerHTML = `
    <div class="sm-actions">
      <button class="ghost sm-run" data-stage="${esc(stage)}">▶ RUN ${stage === 'stage0' ? 'STAGE 0 (INTAKE)' : 'THIS STAGE'}</button>
      ${stage === 'stage0' ? '<span class="sm-hint" style="margin:0">Runs the intake for this project (brief/source/panels).</span>' : ''}
    </div>
    ${smTags(st.stages[stage] && st.stages[stage].metrics)}
    ${st.stages[stage] && st.stages[stage].status === 'failed' ? '<div class="sm-errline" id="sm-fail-line">loading error…</div>' : ''}
    ${st.stages[stage] && st.stages[stage].missing_metrics && st.stages[stage].missing_metrics.length
      ? `<div class="sm-errline">⚠ missing mandatory proof metrics: ${esc(st.stages[stage].missing_metrics.join(', '))} — the next stage is blocked until these are recorded.</div>` : ''}
    <div id="sm-viewer"><div class="sm-empty">loading…</div></div>
    <div class="sm-log" id="sm-log"></div>
    ${smNextHint(stage, st)}
  `;
  const runBtn = smBody.querySelector('.sm-run');
  if (runBtn) runBtn.onclick = () => { smModal.classList.remove('open'); runStage(runBtn.dataset.stage); };

  // Load the human-readable viewer for this stage
  const viewer = STAGE_VIEWERS[stage] || (() => Promise.resolve(''));
  const docOnly = arts.filter((a) => a.kind === 'text' || a.kind === 'json');
  viewer(arts)
    .then((html) => {
      $('sm-viewer').innerHTML = html || '<div class="sm-empty">no viewable artifacts</div>';
      // Load any raw JSON/text docs referenced by the viewer
      smBody.querySelectorAll('[data-doc-path]').forEach(async (pre) => {
        try {
          let t = await fetchText(pre.dataset.docPath);
          if (t.length > 120000) t = t.slice(0, 120000) + '\n…(truncated)';
          pre.textContent = t;
        } catch { pre.textContent = '(unable to load document)'; }
      });
    })
    .catch(() => { $('sm-viewer').innerHTML = '<div class="sm-empty">could not render this stage</div>'; });

  // Show the raw doc list as fallback links at the bottom
  if (docOnly.length) {
    smBody.insertAdjacentHTML('beforeend', `<div class="sm-section-title">RAW FILES</div>
      ${docOnly.map((a) => `<div class="mono-sm mb-sm"><a href="${esc(smUrl(a.path))}" target="_blank">${esc(a.name)}</a></div>`).join('')}`);
  }

  // Attach failure log if the stage failed
  if (st.stages[stage] && st.stages[stage].status === 'failed') {
    j(pipeline('log/' + stage))
      .then((lg) => { $('sm-fail-line').textContent = lg.log || '(no error log written)'; })
      .catch(() => { $('sm-fail-line').textContent = '(could not load error)'; });
  }
}

function smNextHint(stage, st) {
  const idx = STAGE_IDS.indexOf(stage);
  if (idx < 0) return '';
  const next = STAGE_IDS.slice(idx + 1).find((s) => {
    const info = st.stages[s] || {};
    return info.status !== 'done';
  });
  if (!next) return '<div class="sm-next">✓ this is the last pending stage — the pipeline will be complete.</div>';
  return `<div class="sm-next">next up: <b>${esc(next)}</b> — run it (or hit RUN ALL).</div>`;
}

function openStageModal(stage) {
  if (!studioProject) { alert('create or select a project first'); return; }
  smTitle.textContent = STAGE_TITLES[stage] || 'STAGE';
  smBody.innerHTML = '<div class="sm-empty">loading…</div>';
  smModal.classList.add('open');
  Promise.all([j(pipeline('artifacts')), j(pipeline('status'))])
    .then(([list, st]) => loadStageArtifacts(stage, list[stage] || [], st))
    .catch((err) => { smBody.innerHTML = '<div class="sm-empty">error: ' + esc(err.message) + '</div>'; });
}

$('stage-modal-close').addEventListener('click', () => smModal.classList.remove('open'));
smModal.addEventListener('click', (e) => { if (e.target === smModal) smModal.classList.remove('open'); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { smModal.classList.remove('open'); $('setup-modal').classList.remove('open'); }
});
$('run-all-btn').addEventListener('click', runAll);
$('setup-close').addEventListener('click', () => $('setup-modal').classList.remove('open'));
$('setup-modal').addEventListener('click', (e) => {
  if (e.target === $('setup-modal')) $('setup-modal').classList.remove('open');
});

// ---- STOP / QUICK TEST controls (studio FULL PIPELINE banner) ----
// STOP asks the run-all worker to abort at the next stage boundary.
$('studio-stop-btn')?.addEventListener('click', async () => {
  if (!studioProject) { alert('select a project first'); return; }
  await postJson(pipeline('stop'));
  setLastMsg('stop requested — the run will halt after the current stage', 'warn');
});

// QUICK TEST creates a small throwaway project and runs the whole pipeline
// fast (refs capped, animation off) to prove it works end-to-end in < 1 hour.
$('quick-test-btn')?.addEventListener('click', async () => {
  if (_studioBusy) { alert('a run is already in progress — wait for it to finish'); return; }
  if (!confirm('Run a QUICK TEST? A small throwaway project (word_target 300, refs capped, animation off) is created and the full pipeline runs end-to-end — typically well under an hour.')) return;
  withLoading($('quick-test-btn'), async () => {
    const r = await j('/api/pipeline/quick-test', { method: 'POST' });
    studioProject = r.slug;
    localStorage.setItem('studio-project', r.slug);
    await loadStudioProjects();
    setLastMsg(`QUICK TEST ${r.slug} started — polling… (stop anytime with STOP)`, 'ok');
    pollStudioStatus();
  });
});

// Label the RUN ALL button by step mode: STEP pauses after each stage so the
// next click continues to the following stage (CONTINUE / RUN NEXT).
function renderRunAllLabel() {
  const btn = $('run-all-btn');
  if (!btn) return;
  const step = $('studio-step-check')?.checked || false;
  btn.textContent = step ? '▶ RUN NEXT STAGE' : '▶ RUN ALL REMAINING STAGES';
}
$('studio-step-check')?.addEventListener('change', renderRunAllLabel);
renderRunAllLabel();

// ---- Embedded ComfyUI iframe toggle ----
// The studio page lets you open ComfyUI inline (via an <iframe>) instead of a
// separate tab. Clicking the button toggles the iframe's visibility and label.
const comfyBtn = $('comfy-embed-btn'), comfyFrame = $('comfy-frame');
if (comfyBtn && comfyFrame) {
  comfyBtn.addEventListener('click', () => {
    const hidden = comfyFrame.style.display === 'none';
    comfyFrame.style.display = hidden ? 'block' : 'none';
    comfyBtn.textContent = hidden ? 'HIDE COMFYUI ▲' : 'OPEN COMFYUI HERE ▼';
  });
}

// ---- Animation master switch (studio banner toggle) ----
// OFF (default) = panels mode: stage3c + clip VLM review skipped, final video
// assembled from panels with Ken Burns zoom/pan + fades. ON = GPU animation.
// State is persisted to stack.toml [animation].enabled, not localStorage.
let _animationEnabled = null;
function renderAnimToggle() {
  const btn = $('studio-anim-toggle');
  if (!btn) return;
  if (_animationEnabled === null) { btn.textContent = '…'; return; }
  btn.textContent = _animationEnabled ? 'ON ●' : 'OFF ○';
  btn.style.color = _animationEnabled ? 'var(--green)' : 'var(--dim)';
  btn.title = _animationEnabled
    ? 'Animation ON — stage3c renders LTX/Wan clips. Click to switch to panels mode.'
    : 'Panels mode — assemble from panels (Ken Burns zoom/pan + fades), no GPU animation. Click to enable animation.';
}
async function loadAnimationState() {
  try {
    const s = await j('/api/system');
    _animationEnabled = !!s.animation?.enabled;
    renderAnimToggle();
  } catch { /* kernel down — keep last state */ }
}
const animToggleBtn = $('studio-anim-toggle');
if (animToggleBtn) {
  animToggleBtn.addEventListener('click', async () => {
    const next = !_animationEnabled;
    withLoading(animToggleBtn, async () => {
      await postJson('/api/animation', { enabled: next });
      _animationEnabled = next;
      renderAnimToggle();
      setLastMsg(next
        ? 'animation ON — stage3c (LTX/Wan) will run on the next RUN; GPU stages will be slow'
        : 'animation OFF — panels mode: Ken Burns zoom/pan + fades, no GPU video', 'ok');
      pollStudioStatus();
    });
  });
}

// ---- NIM model selector wiring ----
const nimSel = $('studio-nim-select');
if (nimSel) {
  nimSel.addEventListener('change', (e) => setNimModel(e.target.value));
  loadNimModels();
}

// ---- studio polling: faster when something is running ----
let _studioPoll = null;
function startStudioPolling() {
  if (_studioPoll) clearInterval(_studioPoll);
  _studioPoll = setInterval(() => {
    if (document.querySelector('#page-studio.active')) pollStudioStatus();
  }, 3000);
}

// Render the grid first, then load projects + start polling
renderStageGrid();
loadStudioProjects().then(() => { pollStudioStatus(); startStudioPolling(); });
loadAnimationState();
setInterval(() => { if (document.querySelector('#page-studio.active')) loadNimModels(); }, 30000);

/* -- 12. System page ------------------------------------------------------------ */

async function refreshSystemPage() {
  try {
    const s = await j('/api/system');
    const h = window._health || { status: '?', ollama: false, gpu: { available: false } };
    const total = Object.values(s.tasks).reduce((a, b) => a + b, 0);
    $('sys-cards').innerHTML = `
      <div class="card hud"><div class="big ${h.status === 'ok' ? 'ok' : 'bad'}">${(h.status || '?').toUpperCase()}</div><div class="lbl">kernel v${esc(s.kernel.version)} :${s.kernel.port}</div></div>
      <div class="card hud"><div class="big">${s.agents.length}</div><div class="lbl">agents</div></div>
      <div class="card hud"><div class="big ${h.ollama ? 'ok' : 'bad'}">${h.ollama ? 'UP' : 'DOWN'}</div><div class="lbl">ollama :11434</div></div>
      <div class="card hud"><div class="big">${h.gpu.available ? h.gpu.vram_used_mb + ' MB' : 'FREE'}</div><div class="lbl">gpu vram used</div></div>
      <div class="card hud"><div class="big">${total}</div><div class="lbl">tasks total</div></div>`;
    $('sys-models').querySelector('tbody').innerHTML = Object.entries(s.models)
      .map(([r, m]) => `<tr><td class="mono">${esc(r)}</td><td class="mono">${esc(m)}</td></tr>`).join('');
    $('sys-paths').querySelector('tbody').innerHTML = Object.entries(s.paths)
      .map(([k, v]) => `<tr><td class="mono text-cyan-dim">${esc(k)}</td><td class="mono">${esc(v)}</td></tr>`).join('');
    $('sys-agents-tbl').querySelector('tbody').innerHTML = s.agents.map((a, i) =>
      `<tr><td><span style="color:${AGENT_COLORS[i % AGENT_COLORS.length]}">●</span> ${esc(a.name)}</td>
       <td class="mono">${esc(a.domain)}</td><td class="mono">${esc(a.model)}</td><td class="mono">${esc(a.resolved_model)}</td></tr>`).join('');
    $('sys-taskstats').innerHTML = ['queued', 'running', 'done', 'failed'].map((st) =>
      `<span class="chip"><span class="dot" style="background:${STATUS_DOT[st]}"></span> ${st.toUpperCase()} ${s.tasks[st] || 0}</span>`).join('');
  } catch { /* system page unavailable */ }
}

/* -- 13. Boot ------------------------------------------------------------------- */

async function refreshAll() {
  await refreshHealth();
  await Promise.all([refreshAgents(), refreshSystems(), refreshTasks(), refreshSystemPage()]);
}

refreshAll();
drawCortex();
// Open the configured wiki root if it exists inside the vault, else the vault
// root. Checking existence up-front (instead of just requesting it) avoids a
// 404 console error when the configured folder is absent from the vault.
j('/api/system')
  .then((s) => {
    const wr = (s.paths && s.paths.wiki_root) || '';
    if (!wr) return loadWiki('');
    return j('/api/brain/notes?folder=')
      .then((root) => loadWiki(root.some((i) => i.type === 'dir' && i.name === wr) ? wr : ''))
      .catch(() => loadWiki(''));
  })
  .catch(() => loadWiki(''));
setInterval(refreshHealth, 10000);
setInterval(refreshSystems, 15000);
setInterval(refreshTasks, 5000);
setInterval(refreshSystemPage, 20000);
