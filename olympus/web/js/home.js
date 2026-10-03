/* home.js — HOME page: cortex graph, jarvis, capture, search, activity */

/* -- 2. Home / Cortex knowledge graph --------------------------------------- */

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


async function refreshAgents() {
  window._agents = await j('/api/agents');
  buildCortex(window._agents, noteIndex || []);
  // once the vault index is loaded, rebuild so every neuron is a real note
  buildNoteIndex().then((idx) => buildCortex(window._agents, idx));
}


/* -- 4. Jarvis chat ---------------------------------------------------------- */

// Poll a task until it finishes (or times out), then call onDone


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
      location.href = '/wiki?note=' + encodeURIComponent(el.dataset.p);
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


/* -- home boot -------------------------------------------------------------- */
drawCortex();
refreshAgents();
refreshSystems();
refreshTasks();
const _wikiRoot = j('/api/system').then((s) => (s.paths && s.paths.wiki_root) || '').catch(() => '');
_wikiRoot.then((wr) => {
  if (!wr) return buildNoteIndex();
  return j('/api/brain/notes?folder=').then((root) => {
    if (root.some((i) => i.type === 'dir' && i.name === wr)) return buildNoteIndex();
  }).catch(() => {});
});
setInterval(refreshSystems, 15000);
setInterval(refreshTasks, 5000);
setInterval(refreshHealth, 10000);
