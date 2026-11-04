/* commerce.js — COMMERCE page: Zik research, Plutus, charts */

/* -- 9. Commerce ---------------------------------------------------------------- */

bindTaskForm('plutus-form', 'button[type="submit"]', {
  inputId: 'plutus-text', agent: 'plutus',
  onDone() { refreshTasks(); },
});


/* -- 9b. Commerce research (Zik intake + notes + n8n) --------------------------- */
// Plutus form/table stay as-is (see refreshTasks). This block adds the
// product-research layer below: Zik keywords w/ client-side filter,
// vault research notes w/ breadcrumb + rendered markdown, n8n pipeline
// status, and a static eBay API checklist (no secrets in the frontend).
let commerceNoteCache = {}, _commerceLoading = false;
let _commerceLastN8n = '';
// Workbench state: parsed intake + per-keyword comps. eBay keys are read
// from the password inputs at analyze time and never persisted anywhere.
let intake = { category: '', keywords: [], sellers: [] };
let intakeSlug = '';

function cmStep(n, state) {
  const el = $('cm-step-' + n);
  if (!el) return;
  el.classList.remove('active', 'done');
  if (state) el.classList.add(state);
}

function cmKpis(kwCount, revenue, sellerCount, compsText) {
  if (kwCount !== undefined) $('cm-kpi-kw').textContent = kwCount;
  if (revenue !== undefined) $('cm-kpi-rev').textContent = revenue;
  if (sellerCount !== undefined) $('cm-kpi-sellers').textContent = sellerCount;
  if (compsText !== undefined) $('cm-kpi-comps').textContent = compsText;
}

function commerceMoney(n) {
  return '$' + Number(n || 0).toLocaleString();
}

// Zik "Product Research" copy-paste: a header stat block (Sell through,
// Listings, Sold Items, Sale Earnings, Successful listings, Average Price)
// followed by seller/product rows (country, seller, feedback, title, sold,
// total, price, ship-from). Returns null when the text isn't that format.
function parseZikResearch(text) {
  const raw = String(text || '');
  if (!/sell through|sale earnings|successful listings|average price|market share|sales trend/i.test(raw)) return null;
  const ne = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const low = (s) => s.toLowerCase();

  const STAT = {
    'sell through': 'sell_through', 'listings': 'listings',
    'sold items': 'sold_items', 'sale earnings': 'sale_earnings',
    'successful listings': 'successful_listings', 'average price': 'average_price',
  };
  const stats = {};
  ne.forEach((l, i) => {
    const key = STAT[low(l)];
    if (key && stats[key] == null) {
      const next = ne[i + 1];
      if (next && /^\$?[\d.,]+%?$/.test(next)) stats[key] = next;
    }
  });

  const isCountry = (s) => /^[A-Z]{2}$/.test(s);
  const isNum = (s) => /^\d[\d,]*$/.test(s);
  const isMoney = (s) => /^\$[\d.,]+$/.test(s);
  const isSeller = (s) => /^[A-Za-z][A-Za-z0-9 ._&-]{1,38}$/.test(s)
    && !isCountry(s) && !isMoney(s) && !isNum(s);

  // Each product block starts at a country code directly above a seller name.
  const starts = [];
  for (let i = 0; i < ne.length - 1; i++) {
    if (isCountry(ne[i]) && isSeller(ne[i + 1])) starts.push(i);
  }
  const products = [];
  for (let s = 0; s < starts.length; s++) {
    const block = ne.slice(starts[s], s + 1 < starts.length ? starts[s + 1] : ne.length);
    const seller = block[1];
    const priceLine = [...block].reverse().find(isMoney);
    const price = priceLine ? Number(priceLine.replace(/[$,]/g, '')) : null;
    let title = '';
    block.forEach((l) => {
      if (l !== seller && l.length > title.length && l.length > 10
        && l.includes(' ') && /[A-Za-z]/.test(l) && !isSeller(l)) title = l;
    });
    const feedbackLine = block.find((l, idx) => idx > 1 && isNum(l));
    const feedback = feedbackLine ? Number(feedbackLine.replace(/,/g, '')) : null;
    const ti = block.indexOf(title);
    const after = block.slice(ti + 1).filter(isNum).map((n) => Number(n.replace(/,/g, '')));
    const ship = [...block].reverse().find(isCountry) || block[0];
    if (seller && title) {
      products.push({
        seller, seller_feedback: feedback, title, price,
        country: ship, sold: after[0] != null ? after[0] : null,
        total: after[1] != null ? after[1] : null,
      });
    }
  }

  const CHROME = new Set(['product research', 'title analytics', 'price analytics',
    'search', 'training videos', 'share', 'scan', 'save to watchlist', 'market share',
    'sales trend', 'filters', 'sellers country', 'dropshippers only', 'exclude vero',
    'search products', 'searched on: ebay.com']);
  let keyword = '';
  for (const l of ne) {
    if (CHROME.has(low(l))) continue;
    if (l === low(l) && /^[a-z0-9][a-z0-9 .'&-]{2,}$/.test(l) && l.split(' ').length <= 6) { keyword = l; break; }
  }

  if (!products.length && !Object.keys(stats).length) return null;
  return { keyword, stats, products };
}

// Parse raw Zik copy-paste: alternating name/$lines in keywords mode, then
// CC/seller/feedback/$sales groups after the "Trending Dropshippers" header.
function parseZik(text) {
  const HEADERS = new Set(['trending ebay niches', 'trending dropshippers',
    'last 30 days', 'keywords', 'revenue', 'seller', 'sellers',
    'scan', 'feedback', 'sales']);
  const kws = [], sellers = [];
  let mode = 'kw', pending = null, grp = null, unpaired = 0;
  const cleanName = (s) => s.replace(/\s*[,.;:]+\s*$/, '').replace(/\s+/g, ' ').trim();
  for (const rawLine of String(text || '').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    const low = line.toLowerCase();
    if (HEADERS.has(low)) {
      if (low === 'trending dropshippers') { mode = 'sellers'; pending = null; grp = null; }
      continue;
    }
    const mVal = /^\$([\d,]+)$/.exec(line);
    if (mVal) {
      const v = parseInt(mVal[1].replace(/,/g, ''), 10);
      if (mode === 'kw') {
        if (pending) { kws.push({ keyword: pending, revenue_30d: v }); pending = null; }
        else unpaired++;
      } else if (grp && grp.seller && grp.feedback != null) {
        sellers.push({ seller: grp.seller, country: grp.cc, feedback: grp.feedback, sales_30d: v });
        grp = null;
      } else unpaired++;
      continue;
    }
    if (mode === 'kw') {
      if (/^[a-z]{2}$/.test(low)) continue; // stray country header (us)
      pending = cleanName(line);
      continue;
    }
    if (/^[a-z]{2}$/.test(low)) { grp = { cc: line.toUpperCase() }; continue; }
    if (grp && !grp.seller) { grp.seller = cleanName(line); continue; }
    const nVal = /^[0-9][\d,]*$/.test(line) ? parseInt(line.replace(/,/g, ''), 10) : null;
    if (grp && grp.seller && grp.feedback == null && nVal != null) { grp.feedback = nVal; continue; }
    unpaired++;
  }
  if (pending) unpaired++;
  const seen = new Map();
  for (const k of kws) {
    const key = k.keyword.toLowerCase();
    if (!seen.has(key) || seen.get(key).rev < k.revenue_30d) seen.set(key, { name: k.keyword, rev: k.revenue_30d });
  }
  const deduped = [...seen.values()]
    .map((v) => ({ keyword: v.name, revenue_30d: v.rev }))
    .sort((a, b) => b.revenue_30d - a.revenue_30d);
  sellers.sort((a, b) => b.sales_30d - a.sales_30d);
  return { keywords: deduped, sellers, unpaired, research: parseZikResearch(text) };
}

function sourceLinks(kw) {
  const q = encodeURIComponent(kw);
  return `<a href="https://www.amazon.com/s?k=${q}" target="_blank">A</a> · `
    + `<a href="https://www.walmart.com/search?q=${q}" target="_blank">W</a> · `
    + `<a href="https://www.ebay.com/sch/i.html?_nkw=${q}" target="_blank">e</a>`;
}

// Infographics: horizontal SVG bar charts (offline-safe, no CDN) + keyword
// cards with min/med/max range bars. Rendered from the parsed intake.
let _cmGradN = 0;
// Rank-medal palette: gold / silver / bronze / cyan for the rest.
const CM_RANK = [
  ['#8a6a1f', '#e8b84b'],
  ['#5a6b7d', '#c3d0dd'],
  ['#7a4a22', '#d29a5b'],
  ['#2a7d99', '#57c7e3'],
];
function svgBars(rows, fmt) {
  const W = 660, rowH = 26, padL = 220, padR = 90;
  const max = Math.max(1, ...rows.map((r) => r.value));
  const base = 'cmg' + (++_cmGradN);
  const defs = CM_RANK.map((c, i) =>
    `<linearGradient id="${base}-${i}" x1="0" y1="0" x2="1" y2="0">`
    + `<stop offset="0" stop-color="${c[0]}"/><stop offset="1" stop-color="${c[1]}"/></linearGradient>`
  ).join('');
  let y = 6, body = '';
  rows.forEach((r, idx) => {
    const w = Math.max(2, Math.round((W - padL - padR) * r.value / max));
    const g = idx < 3 ? idx : 3;
    body += `<text class="cx-lbl" x="0" y="${y + 15}">${esc((r.label || '').slice(0, 30))}</text>`
      + `<rect class="cx-track" x="${padL}" y="${y + 4}" width="${W - padL - padR}" height="12" rx="3"/>`
      + `<rect x="${padL}" y="${y + 4}" width="${w}" height="12" rx="3" fill="url(#${base}-${g})"/>`
      + `<text class="cx-val" x="${W - padR + 8}" y="${y + 15}">${esc(fmt(r.value))}</text>`;
    y += rowH;
  });
  return `<svg viewBox="0 0 ${W} ${y}" role="img"><defs>${defs}</defs>${body}</svg>`;
}
const fmtMoney = (n) => '$' + Number(n || 0).toLocaleString();

// Keyword detail (Zik-style): stat strip + trend sparkline + product rows.
// Comps carry live listings only — sold history needs Terapeak/prod order
// data, so the strip labels counts honestly.
let detailComps = [];
let detailItems = [];

const DONUT_COLORS = ['#8f7bff', '#57c7e3', '#4ade80', '#e8b84b', '#ff5ca8', '#ff9f45', '#7bd4ff'];

function donutChart(segs) {
  // segs: [{label, value}] — SVG donut, top sellers + Other.
  const R = 54, C = 2 * Math.PI * R;
  const total = Math.max(1, segs.reduce((a, s) => a + s.value, 0));
  let start = 0, rings = '';
  segs.forEach((s, i) => {
    const len = (s.value / total) * C;
    rings += `<circle cx="70" cy="70" r="${R}" fill="none" `
      + `stroke="${DONUT_COLORS[i % DONUT_COLORS.length]}" stroke-width="18" `
      + `stroke-dasharray="${len.toFixed(1)} ${C.toFixed(1)}" `
      + `stroke-dashoffset="${(-start * C).toFixed(1)}" transform="rotate(-90 70 70)"/>`;
    start += s.value / total;
  });
  const top = segs[0];
  const legend = segs.map((s, i) =>
    `<div class="mono-xs" style="margin:.15rem 0"><span style="color:${DONUT_COLORS[i % DONUT_COLORS.length]}">●</span> `
    + `${esc(s.label)} · ${Math.round(100 * s.value / total)}%</div>`).join('');
  return `<div class="flex"><svg viewBox="0 0 140 140" style="width:150px;height:auto" role="img">${rings}`
    + `<text x="70" y="66" text-anchor="middle" fill="#dfe9f2" font-size="11" font-family="Consolas,monospace">${esc((top.label || '').slice(0, 16))}</text>`
    + `<text x="70" y="82" text-anchor="middle" fill="#8b9fb3" font-size="11" font-family="Consolas,monospace">${Math.round(100 * top.value / total)}%</text></svg>`
    + `<div>${legend}</div></div>`;
}

function areaChart(points) {
  // Google-interest area chart w/ date axis (weekly points back from today).
  if (!points || !points.length) return '<span class="text-dim">no trend data</span>';
  const W = 620, H = 150, padL = 30, padB = 18;
  const max = Math.max(...points, 1);
  const X = (i) => padL + (i * (W - padL - 8)) / Math.max(1, points.length - 1);
  const Y = (v) => 8 + (H - padB - 8) * (1 - v / max);
  const line = points.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ');
  const d = new Date();
  const fmt = (weeksAgo) => new Date(d - weeksAgo * 7 * 864e5).toISOString().slice(0, 10);
  const n = points.length;
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto" role="img">`
    + [0, 0.5, 1].map((f) =>
      `<line x1="${padL}" y1="${(Y(max * f)).toFixed(1)}" x2="${W - 4}" y2="${(Y(max * f)).toFixed(1)}" stroke="#123347"/>`
      + `<text x="2" y="${(Y(max * f) + 3).toFixed(1)}" font-size="9" fill="#8b9fb3" font-family="Consolas,monospace">${Math.round(max * f)}</text>`
    ).join('')
    + `<polygon points="${padL},${H - padB} ${line} ${X(n - 1).toFixed(1)},${H - padB}" fill="rgba(87,199,227,.18)"/>`
    + `<polyline points="${line}" fill="none" stroke="#57c7e3" stroke-width="1.5"/>`
    + `<text x="${padL}" y="${H - 4}" font-size="9" fill="#8b9fb3" font-family="Consolas,monospace">${fmt(n - 1)}</text>`
    + `<text x="${W - 62}" y="${H - 4}" font-size="9" fill="#8b9fb3" font-family="Consolas,monospace">${fmt(0)}</text></svg>`;
}

/* -- Zik-style Product Research view --------------------------------------- */
// One selected keyword drives the whole view: stat band, market-share donut,
// sales trend, filters and the product table. Data comes from the same eBay
// comp payload the workbench already fetches.
let zkState = { keyword: '', revenue_30d: null, total: null, stats: null, meta: null, items: [], ztab: 'research' };

function zkSellerCounts() {
  const set = {};
  (zkState.items || []).forEach((i) => { const k = i.seller || 'unknown'; set[k] = (set[k] || 0) + 1; });
  return set;
}

function renderZkStats() {
  const s = zkState.stats || {};
  const m = zkState.meta || {};
  const cell = (v, l, t) => `<div class="zk-stat" title="${esc(t || '')}"><b>${v}</b><span>${esc(l)}</span></div>`;
  const dash = '<span class="text-dim">—</span>';
  const listings = m.listings != null ? m.listings
    : (zkState.total != null ? Number(zkState.total).toLocaleString() : null);
  const earnings = zkState.revenue_30d != null ? commerceMoney(zkState.revenue_30d)
    : (m.saleEarnings || null);
  const avg = s.avg != null ? '$' + Number(s.avg).toFixed(2) : (m.avgPrice || null);
  $('zk-stats').innerHTML =
    cell(m.sellThrough || dash, 'Sell through', 'Sold ÷ listings over the window (from Zik paste)')
    + cell(listings || dash, 'Listings', 'Live eBay listings')
    + cell(m.soldItems || dash, 'Sold items', 'Units sold in the window (from Zik paste)')
    + cell(earnings || dash, 'Sale earnings', 'Zik 30-day revenue for this keyword')
    + cell(m.successful || dash, 'Successful listings', 'Share of listings that sold (from Zik paste)')
    + cell(avg || dash, 'Average price', 'Mean listing price');
}

function renderZkShare() {
  const share = zkSellerCounts();
  const segs = Object.entries(share).sort((a, b) => b[1] - a[1]).slice(0, 6)
    .map(([label, value]) => ({ label, value }));
  const rest = Object.entries(share).slice(6).reduce((a, [, v]) => a + v, 0);
  if (rest) segs.push({ label: 'other', value: rest });
  $('zk-share').innerHTML = segs.length
    ? donutChart(segs) : '<span class="text-dim">no seller data — run Analyze with eBay keys</span>';
}

async function renderZkTrend() {
  const el = $('zk-trend');
  if (!zkState.keyword) { el.innerHTML = '<span class="text-dim">—</span>'; return; }
  el.innerHTML = '<em class="text-dim">loading trend…</em>';
  try {
    const t = await j('/api/commerce/trends?keyword=' + encodeURIComponent(zkState.keyword));
    el.innerHTML = areaChart(t.points)
      + `<div class="mono-xs text-dim">avg ${t.trend_90d_avg} · ${t.trending ? '↗ trending' : '→ flat'}</div>`;
  } catch {
    el.innerHTML = '<span class="text-dim">trend unavailable</span>';
  }
}

function zkFilteredItems() {
  const q = ($('zk-product-search').value || '').trim().toLowerCase();
  const cc = $('zk-country').value;
  const vero = $('zk-vero').checked;
  return (zkState.items || []).filter((i) => {
    if (q && !(i.title || '').toLowerCase().includes(q)) return false;
    if (cc && (i.country || '').toUpperCase() !== cc) return false;
    if (vero && /vero/i.test(i.title || '')) return false;
    return true;
  });
}

function renderZkTable() {
  const n = parseInt($('zk-entries').value, 10) || 100;
  const items = zkFilteredItems().slice(0, n);
  $('zk-rows').innerHTML = items.map((i) => {
    const loc = (i.country || 'US').toUpperCase();
    return '<tr>'
      + `<td class="mono-sm">${esc(loc)}</td>`
      + `<td class="mono-sm">${esc(i.seller || '')}</td>`
      + `<td class="mono">${i.seller_feedback != null ? Number(i.seller_feedback).toLocaleString() : '—'}</td>`
      + `<td class="zk-prod">${i.thumb ? `<a href="${esc(i.url || '#')}" target="_blank"><img src="${esc(i.thumb)}" alt="" loading="lazy" style="width:34px;height:34px;object-fit:cover;border-radius:5px;vertical-align:middle;margin-right:.5rem"></a>` : ''}<a href="${esc(i.url || '#')}" target="_blank">${esc(i.title || '')}</a></td>`
      + `<td class="mono">${i.sold != null ? Number(i.sold).toLocaleString() : '—'}</td>`
      + `<td class="mono">${i.total != null ? Number(i.total).toLocaleString() : '—'}</td>`
      + `<td class="mono">$${Number(i.price || 0).toFixed(2)}</td>`
      + `<td class="mono-sm">${esc(loc)}</td></tr>`;
  }).join('') || '<tr><td colspan="8" class="text-dim">no listings — run Analyze with eBay keys, or widen the filters</td></tr>';
}

function renderZkTitle() {
  const freq = {};
  zkFilteredItems().forEach((i) => {
    new Set((i.title || '').toLowerCase().replace(/[^a-z0-9\s]/g, ' ').split(/\s+/).filter((w) => w.length > 2))
      .forEach((w) => { freq[w] = (freq[w] || 0) + 1; });
  });
  const rows = Object.entries(freq).sort((a, b) => b[1] - a[1]).slice(0, 40);
  const total = rows.reduce((a, [, v]) => a + v, 0) || 1;
  $('zk-title-rows').innerHTML = rows.map(([w, v]) =>
    `<tr><td class="mono">${esc(w)}</td><td class="mono">${v}</td>`
    + `<td><div class="cm-bar" style="max-width:160px"><div style="width:${Math.round(100 * v / rows[0][1])}%"></div></div>`
    + `<span class="mono-xs text-dim">${Math.round(100 * v / total)}%</span></td></tr>`
  ).join('') || '<tr><td colspan="3" class="text-dim">no listings to analyse</td></tr>';
}

function renderZkPrice() {
  const items = zkFilteredItems().filter((i) => i.price != null);
  const bands = [[0, 5], [5, 10], [10, 20], [20, 50], [50, 100], [100, Infinity]];
  const counts = bands.map(() => 0);
  items.forEach((i) => {
    const p = Number(i.price);
    const idx = bands.findIndex(([lo, hi]) => p >= lo && p < hi);
    if (idx >= 0) counts[idx]++;
  });
  const max = Math.max(1, ...counts);
  const total = counts.reduce((a, v) => a + v, 0) || 1;
  $('zk-price-rows').innerHTML = bands.map(([lo, hi], i) => {
    const label = hi === Infinity ? `$${lo}+` : `$${lo}–$${hi}`;
    return `<tr><td class="mono">${label}</td><td class="mono">${counts[i]}</td>`
      + `<td><div class="cm-bar" style="max-width:160px"><div style="width:${Math.round(100 * counts[i] / max)}%"></div></div>`
      + `<span class="mono-xs text-dim">${Math.round(100 * counts[i] / total)}%</span></td></tr>`;
  }).join('');
}

function applyZkTab() {
  const tab = zkState.ztab;
  $('zk-table-wrap').hidden = tab !== 'research';
  $('zk-title-wrap').hidden = tab !== 'title';
  $('zk-price-wrap').hidden = tab !== 'price';
  document.querySelectorAll('.zk-tab').forEach((b) => {
    const on = b.dataset.ztab === tab;
    b.classList.toggle('is-active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  });
}

function zkRender() {
  const countries = [...new Set((zkState.items || [])
    .map((i) => (i.country || '').toUpperCase()).filter(Boolean))].sort();
  const sel = $('zk-country');
  const cur = sel.value;
  sel.innerHTML = '<option value="">All</option>'
    + countries.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
  sel.value = countries.includes(cur) ? cur : '';
  renderZkStats();
  renderZkShare();
  renderZkTrend();
  renderZkTable();
  renderZkTitle();
  renderZkPrice();
}

function zkSetIntake(open) {
  const panel = $('commerce-intake-panel');
  const btn = $('commerce-intake-toggle');
  if (!panel) return;
  panel.hidden = !open;
  if (btn) {
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    btn.textContent = open ? 'Paste Zik intake ▴' : 'Paste Zik intake ▾';
  }
}

function zkShowKeyword(keyword, opts) {
  const o = opts || {};
  zkState.keyword = keyword || '';
  zkState.revenue_30d = o.revenue_30d != null ? o.revenue_30d : null;
  zkState.total = o.total != null ? o.total : null;
  zkState.stats = o.stats || null;
  zkState.meta = o.meta || null;
  zkState.items = o.items || [];
  $('zk-title').textContent = zkState.keyword || '—';
  $('zk-prodmeta').textContent = [
    zkState.total != null ? `${Number(zkState.total).toLocaleString()} live listings` : 'live listings —',
    zkState.items.length ? `${zkState.items.length} sampled` : 'sample —',
    zkState.revenue_30d != null ? `${commerceMoney(zkState.revenue_30d)} Zik 30d` : 'Zik 30d —',
  ].join(' · ');
  ['zk-prodhead', 'zk-stats', 'zk-two', 'zk-filters'].forEach((id) => { $(id).hidden = false; });
  applyZkTab();
  zkRender();
  zkSetIntake(false); // results take focus; reopen via the “Paste Zik intake” button
}

async function openKwDetail(kw) {
  const c = detailComps.find((x) => x.keyword === kw);
  if (!c) return;
  detailItems = c.items || [];
  zkShowKeyword(c.keyword, {
    revenue_30d: c.revenue_30d, total: c.total, stats: c.stats, items: c.items,
  });
  $('zk-prodhead').scrollIntoView({ block: 'start', behavior: 'smooth' });
}

function renderSellerChart() {
  const top = intake.sellers.slice(0, 8);
  $('commerce-chart-sellers').innerHTML = top.length
    ? svgBars(top.map((s) => ({ label: s.seller, value: s.sales_30d })), fmtMoney)
    : '<div class="sm-empty">No seller data in this paste.</div>';
}

async function openCommerceNote(path) {
  $('commerce-note').hidden = false;
  if (commerceNoteCache[path]) {
    $('commerce-note').innerHTML = `<div class="mono-sm text-cyan-dim mb-sm">${esc(path)}</div>` + commerceNoteCache[path];
    try { localStorage.setItem('commerce-note', path); } catch { /* ignore */ }
    return;
  }
  $('commerce-note').innerHTML = '<em class="text-dim">loading…</em>';
  try {
    const n = await j('/api/brain/note?path=' + encodeURIComponent(path));
    commerceNoteCache[path] = n.html || '<em>empty note</em>';
    $('commerce-note').innerHTML = `<div class="mono-sm text-cyan-dim mb-sm">${esc(path)}</div>` + commerceNoteCache[path];
    try { localStorage.setItem('commerce-note', path); } catch { /* ignore */ }
  } catch {
    $('commerce-note').innerHTML = '<em>could not load note — check vault path in stack.toml</em>';
  }
}

async function loadCommerce() {
  if (_commerceLoading) return;
  _commerceLoading = true;
  try {
    // Status line: Plutus model + n8n reachability (per-panel error states)
    let statusHtml = '';
    try {
      const agents = await j('/api/agents');
      const plutus = (agents || []).find((a) => (a.name || '').toLowerCase() === 'plutus');
      statusHtml += plutus
        ? `<span class="chip"><span class="ok">●</span> PLUTUS · ${esc(plutus.resolved_model || plutus.model || '')}</span>`
        : `<span class="chip"><span class="bad">●</span> PLUTUS agent missing</span>`;
    } catch {
      statusHtml += `<span class="chip"><span class="bad">●</span> agents unreachable</span>`;
    }
    let n8n = null;
    try {
      n8n = await j('/api/commerce/n8n');
      statusHtml += n8n && n8n.reachable
        ? `<span class="chip"><span class="ok">●</span> n8n · ${n8n.workflows} workflows (${n8n.active} active)</span>`
        : `<span class="chip"><span class="bad">●</span> n8n unreachable</span>`;
    } catch {
      statusHtml += `<span class="chip"><span class="bad">●</span> n8n unreachable</span>`;
    }
    statusHtml += `<span class="chip">eBay sandbox · tested via curl</span>`;
    $('commerce-status').innerHTML = statusHtml;

    // eBay checklist (static — keys are per-session, never stored)
    $('commerce-ebay-rows').innerHTML = [
      ['Live comps (above)', 'live listings via per-session App ID/Cert — price spread + listing counts'],
      ['Sold history (30d)', 'needs production user token — OAuth consent with seller account (phase 2)'],
      ['Trending verdict', 'Plutus/Ollama local analysis + eBay comp velocity — no cloud calls'],
      ['Sourcing', 'Amazon / Walmart / eBay search links per keyword — compare landed cost manually'],
    ].map(([k, v]) => `<tr><td class="mono text-cyan-dim">${esc(k)}</td><td>${esc(v)}</td></tr>`).join('');

    // Research insights: one ranked card grid (score, revenue, bar).
    // The old separate chart duplicated this list — removed. Clicking a
    // card opens the full note below (existing reader, hidden till then).
    try {
      const ins = await j('/api/commerce/insights?limit=200');
      const items = ins.items || [];
      $('commerce-ins-count').textContent =
        `${items.length} notes ranked`;
      let insShowAll = false;
      const renderInsCards = () => {
        const list = insShowAll ? items : items.slice(0, 8);
        const tierOf = (o) => o == null ? 'none' : o >= 85 ? 'ok' : o >= 70 ? 'warn' : 'low';
        const pill = (o) => o == null ? `<span class="cm-pill warn">unscored</span>`
          : o >= 85 ? `<span class="cm-pill ok">${o}/100</span>`
          : o >= 70 ? `<span class="cm-pill warn">${o}/100</span>`
          : `<span class="cm-pill">${o}/100</span>`;
        $('commerce-ins-cards').innerHTML = (list.map((n) => {
          const p = 'Product Research/' + n.file;
          const pct = n.opportunity != null ? Math.max(2, n.opportunity) : 0;
          return `<div class="hud cm-kcard" data-note="${esc(p)}" style="cursor:pointer">`
            + `<div class="kw">${esc(n.keyword || n.file.replace(/\.md$/, ''))}</div>`
            + (n.revenue_30d != null
              ? `<div class="rev">${commerceMoney(n.revenue_30d)} <small>ZIK 30D</small></div>` : '')
            + `<div class="row">${pill(n.opportunity)}`
            + (n.category ? `<span class="mono-xs text-dim">${esc(n.category)}</span>` : '')
            + `</div>`
            + (n.opportunity != null
              ? `<div class="cm-bar tier-${tierOf(n.opportunity)}"><div style="width:${pct}%"></div></div>` : '')
            + `</div>`;
        }).join('') || '<div class="sm-empty">No research notes yet.</div>')
          + (items.length > 8
            ? `<div style="grid-column:1/-1;text-align:center;margin-top:.4rem">`
              + `<button class="ghost" id="cm-ins-toggle">`
              + `${insShowAll ? 'show less ↑' : `show all ${items.length} ↓`}</button></div>` : '');
        $('commerce-ins-cards').querySelectorAll('[data-note]').forEach((el) =>
          el.addEventListener('click', () => openCommerceNote(el.dataset.note)));
        const tgl = $('cm-ins-toggle');
        if (tgl) tgl.addEventListener('click', () => { insShowAll = !insShowAll; renderInsCards(); });
      };
      renderInsCards();
      const lastRun = n8n && n8n.product_research && n8n.product_research.last
        && n8n.product_research.last.stoppedAt
        ? n8n.product_research.last.stoppedAt.slice(0, 10) : null;
      $('cm-hero-meta').textContent =
        `${items.length} notes · ${n8n && n8n.reachable ? `${n8n.workflows} workflows` : 'n8n offline'}`
        + (lastRun ? ` · last deep run ${lastRun}` : '');
      const saved = localStorage.getItem('commerce-note');
      if (saved && items.some((n) => 'Product Research/' + n.file === saved)) openCommerceNote(saved);
    } catch {
      $('commerce-ins-cards').innerHTML = '<div class="sm-empty">Insights unavailable.</div>';
    }

    // Deep-research pipeline only — the full workflow roster lives on SYSTEM.
    if (n8n && n8n.reachable) {
      const pr = n8n.product_research;
      const last = pr && pr.last;
      const nh = pr
        ? `<div class="sys-row"><span class="dot" style="background:${pr.active ? 'var(--green)' : '#2a3a4a'}"></span>`
          + `<span class="nm">${esc(pr.name)}</span>`
          + (last && last.status
            ? `<span class="st ${last.status === 'success' ? 'up' : 'down'}">${esc(last.status)}${last.stoppedAt ? ' · ' + esc(last.stoppedAt.slice(0, 10)) : ''}</span>`
            : `<span class="st ${pr.active ? 'up' : 'down'}">${pr.active ? 'ACTIVE' : 'PAUSED'}</span>`)
          + `</div>`
        : `<div class="text-dim mono-sm">deep-research workflow not found in n8n</div>`;
      if (nh !== _commerceLastN8n) {
        $('commerce-n8n').innerHTML = nh;
        _commerceLastN8n = nh;
      }
    } else {
      $('commerce-n8n').innerHTML = '<span class="text-dim">n8n unreachable — runs daily 06:10, or trigger manually in the n8n UI</span>';
      _commerceLastN8n = '';
    }

  } finally {
    _commerceLoading = false;
  }
}

// Commerce workbench wiring: parse → analyze (Plutus + eBay comps) → save
(() => {
  const parseBtn = $('commerce-parse-btn'), analyzeBtn = $('commerce-analyze-btn');
  if (!parseBtn || !analyzeBtn) return;

  // Friendly inline errors — never alert() popups on this page.
  function cmError(msg) {
    const el = $('commerce-error');
    el.textContent = msg;
    el.style.display = 'block';
    el.scrollIntoView({ block: 'nearest' });
  }
  function cmClearError() {
    const el = $('commerce-error');
    el.style.display = 'none';
    el.textContent = '';
  }
  function suggestCategory(topKw) {
    const s = (topKw || '').toLowerCase().replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '').slice(0, 40);
    return s || ('intake-' + new Date().toISOString().slice(0, 10));
  }

  function doParse() {
    cmClearError();
    const parsed = parseZik($('commerce-paste').value);
    const r = parsed.research;
    // Zik "Product Research" paste → one keyword plus its seller/product rows.
    if (r && (r.products.length || Object.keys(r.stats).length)) {
      const kw = r.keyword || 'product research';
      const num = (v, pct) => {
        if (v == null) return null;
        const n = Number(String(v).replace(/[$,%]/g, ''));
        return Number.isFinite(n) ? n : null;
      };
      const earn = num(r.stats.sale_earnings);
      const listings = num(r.stats.listings);
      const avg = num(r.stats.average_price);
      intake = {
        category: $('commerce-category').value.trim() || kw,
        keywords: [{ keyword: kw, revenue_30d: earn || 0 }],
        sellers: r.products.map((p) => ({
          seller: p.seller, country: p.country || '',
          feedback: p.seller_feedback || 0, sales_30d: p.sold || 0,
        })),
      };
      intakeSlug = '';
      const catInput = $('commerce-category');
      if (!catInput.value.trim()) catInput.value = suggestCategory(kw);
      intake.category = catInput.value;
      $('commerce-preview-rows').innerHTML = r.products.slice(0, 30).map((p) =>
        `<tr><td>${esc(p.title)}</td><td class="mono">$${Number(p.price || 0).toFixed(2)}</td></tr>`
      ).join('') || '<tr><td colspan="2" class="text-dim">No product rows found.</td></tr>';
      $('commerce-preview-count').textContent =
        `${r.products.length} products · “${kw}”` + (listings ? ` · ${listings.toLocaleString()} listings` : '');
      cmKpis('1', earn != null ? commerceMoney(earn) : '—',
        String(r.products.length), undefined);
      $('cm-results').hidden = false;
      $('cm-hero-num').hidden = false;
      $('cm-kpis').hidden = false;
      renderSellerChart();
      cmStep(1, 'done'); cmStep(2, 'active'); cmStep(3, ''); cmStep(4, '');
      zkShowKeyword(kw, {
        revenue_30d: earn, total: listings,
        stats: avg != null ? { avg } : null,
        items: r.products,
        meta: {
          sellThrough: r.stats.sell_through || null,
          soldItems: r.stats.sold_items || null,
          successful: r.stats.successful_listings || null,
          listings: listings != null ? listings.toLocaleString() : null,
          saleEarnings: earn != null ? commerceMoney(earn) : null,
          avgPrice: avg != null ? '$' + avg.toFixed(2) : null,
        },
      });
      $('commerce-search').value = kw;
      // Feed the ANALYSIS cards from the same paste so they're coherent and
      // clicking one re-opens the research view (no eBay keys required).
      detailComps = [{
        keyword: kw, revenue_30d: earn, total: listings,
        stats: avg != null ? { avg } : null, items: r.products,
      }];
      $('commerce-comps-cards').innerHTML =
        `<div class="hud cm-kcard" data-kw="${esc(kw)}" style="cursor:pointer">`
        + `<div class="rank">#1</div><div class="kw">${esc(kw)}</div>`
        + (earn != null ? `<div class="rev">${commerceMoney(earn)} <small>ZIK 30D</small></div>` : '')
        + `<div class="row"><span class="cm-pill ok">${r.products.length} products</span>`
        + (listings ? `<span class="cm-pill">${listings.toLocaleString()} live</span>` : '')
        + `</div><div class="row cm-src">${sourceLinks(kw)}</div></div>`;
      return;
    }
    intake = { category: $('commerce-category').value.trim(),
               keywords: parsed.keywords, sellers: parsed.sellers };
    intakeSlug = '';
    if (!intake.keywords.length) {
      $('commerce-preview-rows').innerHTML =
        '<tr><td colspan="2" class="text-dim">Nothing readable yet — paste your Zik copy above.</td></tr>';
      $('commerce-preview-count').textContent = '';
      $('cm-results').hidden = true;
      $('cm-hero-num').hidden = true;
      $('cm-kpis').hidden = true;
      return;
    }
    const catInput = $('commerce-category');
    if (!catInput.value.trim() && parsed.keywords.length) {
      catInput.value = suggestCategory(parsed.keywords[0].keyword);
      intake.category = catInput.value;
    }
    const show = parsed.keywords.slice(0, 30);
    const maxRev = (parsed.keywords[0] && parsed.keywords[0].revenue_30d) || 1;
    const totalRev = parsed.keywords.reduce((a, k) => a + k.revenue_30d, 0);
    $('commerce-preview-rows').innerHTML = show.map((k) => {
      const pct = Math.max(2, Math.round(100 * k.revenue_30d / maxRev));
      return `<tr><td>${esc(k.keyword)}</td><td class="mono">${commerceMoney(k.revenue_30d)}`
        + `<div class="cm-bar"><div style="width:${pct}%"></div></div></td></tr>`;
    }).join('');
    $('commerce-preview-count').textContent =
      `${parsed.keywords.length} keywords · ${parsed.sellers.length} sellers`
      + (parsed.unpaired ? ` · ${parsed.unpaired} stray lines skipped` : '')
      + (parsed.keywords.length > 30 ? ' · showing top 30' : '');
    cmKpis(String(parsed.keywords.length), commerceMoney(totalRev),
      parsed.sellers.length ? String(parsed.sellers.length) : '—', undefined);
    $('cm-results').hidden = false;
    $('cm-hero-num').hidden = false;
    $('cm-kpis').hidden = false;
     renderSellerChart();
    cmStep(1, 'done');
    cmStep(2, 'active');
    cmStep(3, '');
    cmStep(4, '');
    // Zik research view defaults to the top keyword by revenue.
    zkShowKeyword(parsed.keywords[0].keyword, { revenue_30d: parsed.keywords[0].revenue_30d, items: [] });
  }

  parseBtn.addEventListener('click', doParse);
  // Charts build themselves the moment you paste — no button needed.
  $('commerce-paste').addEventListener('paste', () => setTimeout(doParse, 0));

  analyzeBtn.addEventListener('click', async () => {
    cmClearError();
    if (analyzeBtn.disabled) return;
    if (!intake.keywords.length) {
      cmError('Paste your Zik data in the box above first — your charts will build themselves.');
      return;
    }
    const cat = $('commerce-category').value.trim()
      || suggestCategory(intake.keywords[0].keyword);
    $('commerce-category').value = cat;
    const appId = $('commerce-appid').value.trim();
    const certId = $('commerce-certid').value.trim();
    const wantComps = !!(appId && certId);
    const env = $('commerce-env').value;
    const origLabel = analyzeBtn.textContent;
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = 'Working…';
    try {
      $('commerce-progress').textContent = 'saving your batch…';
      const saved = await postJson('/api/commerce/intakes', {
        category: cat, keywords: intake.keywords.slice(0, 300),
        sellers: intake.sellers.slice(0, 100).map((s) => ({
          seller: s.seller, country: s.country || '',
          feedback: s.feedback || 0, sales_30d: s.sales_30d || 0,
        })),
      });
      intakeSlug = saved.slug;
      intake.category = cat;
      // Seed keyword cards (top 8 by revenue), then fill them as calls land.
      // Without eBay keys the cards still render — verdict + sourcing only.
      const top = intake.keywords.slice(0, 8);
      $('commerce-comps-cards').innerHTML = top.length ? top.map((k, i) =>
        `<div class="hud cm-kcard" id="compcard-${i}" data-kw="${esc(k.keyword)}" style="cursor:pointer"><div class="rank">#${i + 1}</div>`
        + `<div class="kw">${esc(k.keyword)}</div>`
        + `<div class="rev">${commerceMoney(k.revenue_30d)} <small>ZIK 30D</small></div>`
        + `<div class="row" data-slot="status">`
        + (wantComps ? `<span class="cm-pill warn">queued</span>`
          : `<span class="cm-pill warn">no keys</span> <span class="mono-xs text-dim">verdict + sourcing only</span>`)
        + `</div>`
        + `<div data-slot="range"></div>`
        + `<div class="row cm-src">${sourceLinks(k.keyword)}</div></div>`
      ).join('') : '<div class="sm-empty">Nothing to analyze.</div>';
      cmStep(2, 'done');
      cmStep(3, 'active');
      $('commerce-progress').textContent = 'asking Plutus…';
      $('commerce-verdict').innerHTML = '<em class="text-dim">Plutus is analyzing…</em>';
      const topLines = intake.keywords.slice(0, 15)
        .map((k) => `- ${k.keyword}: $${k.revenue_30d.toLocaleString()}`).join('\n');
      const sellerLines = intake.sellers.slice(0, 8)
        .map((s) => `- ${s.seller}: $${s.sales_30d.toLocaleString()} sales`).join('\n');
      const t = await postJson('/api/tasks', { text:
        `You are Plutus, commerce analyst. Niche category: "${cat}".\n`
        + `Zik last-30-day keyword revenues:\n${topLines}\n`
        + `Top sellers:\n${sellerLines || '(none)'}\n`
        + `Every claim MUST cite a number from the input above. Ban generic phrases. `
        + `If data is thin, say so instead of inventing. Write exactly these sections, terse plain text, no tables:\n`
        + `1) NICHE VERDICT (trending or not, why — 2 lines max)\n`
        + `2) DEMAND SIGNALS 3) RISK FLAGS (up to 3)\n`
        + `4) PRICE BAND to list under 5) SOURCING ANGLES (what to verify on Amazon/Walmart)`,
        agent: 'plutus' });
      const verdictDone = pollTask(t.id, (done) => {
        const txt = done.result || ('⚠ ' + (done.error || 'failed'));
        $('commerce-verdict').innerHTML =
          `<div class="mono-sm text-cyan-dim mb-sm">PLUTUS · task ${done.id ?? t.id} · ${esc(done.status)}</div>`
          + `<div style="white-space:pre-wrap">${esc(txt).slice(0, 4000)}</div>`;
        refreshTasks();
      });
      $('commerce-progress').textContent = wantComps
        ? 'asking Plutus + checking eBay…'
        : 'asking Plutus… (no keys, so verdict + sourcing only)';
      const card = (idx) => $('compcard-' + idx);
      const fetchComp = async (k, idx) => {
        try {
          const c = await postJson('/api/commerce/ebay-comps', {
            keyword: k.keyword, app_id: appId, cert_id: certId, env, limit: 10,
          });
          k.comp = c;
          const el = card(idx);
          if (!el) return;
          const status = el.querySelector('[data-slot="status"]');
          const range = el.querySelector('[data-slot="range"]');
          if (c.stats) {
            const s = c.stats;
            const span = (s.max - s.min) || 1;
            const medPct = Math.min(100, Math.max(0,
              Math.round(100 * (s.med - s.min) / span)));
            status.innerHTML =
              `<span class="cm-pill ok">${c.total.toLocaleString()} live</span> `
              + `<span class="mono-xs text-dim">${c.returned} sampled</span>`;
            range.innerHTML =
              `<div class="cm-range"><div class="med" style="left:${medPct}%"></div></div>`
              + `<div class="cm-range-lbls"><span>$${s.min.toFixed(2)}</span>`
              + `<span>med $${s.med.toFixed(2)}</span><span>$${s.max.toFixed(2)}</span></div>`;
          } else {
            status.innerHTML =
              `<span class="cm-pill warn">${c.total.toLocaleString()} live</span> `
              + `<span class="mono-xs text-dim">no prices</span>`;
          }
        } catch (err) {
          const el = card(idx);
          if (el) {
            el.querySelector('[data-slot="status"]').innerHTML =
              `<span class="cm-pill bad">failed</span> `
              + `<span class="mono-xs text-dim">${esc((err.message || 'error').slice(0, 60))}</span>`;
          }
        }
      };
      const queue = wantComps ? top.map((k, i) => [k, i]) : [];
      if (queue.length) {
        $('commerce-progress').textContent = 'checking live eBay prices…';
        await Promise.all(Array.from({ length: 3 }, async () => {
          while (queue.length) { const [k, i] = queue.shift(); await fetchComp(k, i); }
        }));
      }
      await verdictDone.catch(() => {});
      const done_n = top.filter((k) => k.comp && k.comp.stats).length;
      detailComps = top.filter((k) => k.comp).map((k) =>
        ({ keyword: k.keyword, revenue_30d: k.revenue_30d, ...k.comp }));
      if (detailComps.length) {
        const c0 = detailComps[0];
        zkShowKeyword(c0.keyword, {
          revenue_30d: c0.revenue_30d, total: c0.total, stats: c0.stats, items: c0.items,
        });
      }
      cmKpis(undefined, undefined, undefined,
        wantComps ? `${done_n}/${top.length}` : '—');
      cmStep(3, 'done');
      cmStep(4, 'active');
      $('commerce-progress').textContent = wantComps
        ? `done — ${done_n}/${top.length} live prices · your report is ready to save`
        : 'verdict done — add eBay keys above and Analyze again for live prices';
      refreshTasks();
    } catch (err) {
      cmError('Something hiccuped: ' + (err.message || err).slice(0, 200));
    } finally {
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = origLabel;
    }
  });

  $('commerce-save-btn').addEventListener('click', () => {
    withLoading($('commerce-save-btn'), async () => {
      if (!intakeSlug) {
        cmError('Hit “Analyze my niche” first — then your report will save here.');
        return;
      }
      const top = intake.keywords.slice(0, 8);
      const lines = [
        `---`, `category: ${intake.category}`, `slug: ${intakeSlug}`,
        `date: ${new Date().toISOString().slice(0, 10)}`,
        `tags: [product-research, ebay]`, `---`, ``,
        `# ${intake.category}`, ``,
        `## Zik 30-day revenues (top ${intake.keywords.length})`,
        ...intake.keywords.slice(0, 30).map((k) => `- ${k.keyword}: $${k.revenue_30d.toLocaleString()}`),
        ``, `## eBay live comps`,
        ...top.map((k) => k.comp && k.comp.stats
          ? `- ${k.keyword}: ${k.comp.total.toLocaleString()} live, $${k.comp.stats.min.toFixed(2)}–$${k.comp.stats.max.toFixed(2)} (med $${k.comp.stats.med.toFixed(2)})`
          : `- ${k.keyword}: comps unavailable`),
        ``, `## Sourcing (check landed cost manually)`,
        ...top.map((k) => `- ${k.keyword}: [Amazon](https://www.amazon.com/s?k=${encodeURIComponent(k.keyword)}) · [Walmart](https://www.walmart.com/search?q=${encodeURIComponent(k.keyword)}) · [eBay](https://www.ebay.com/sch/i.html?_nkw=${encodeURIComponent(k.keyword)})`),
        ``, `_Generated by Olympus Commerce workbench._`,
      ];
      const r = await postJson('/api/commerce/reports',
        { slug: intakeSlug, markdown: lines.join('\n') });
      $('commerce-save-msg').textContent = 'saved → ' + r.path;
      cmStep(4, 'done');
    });
  });

  const crumb = $('commerce-crumb');
  if (crumb) crumb.addEventListener('click', loadCommerce);

  // Clicking any comp card (quick or deep) opens the keyword detail view.
  // Links inside cards still navigate normally.
  $('commerce-comps-cards').addEventListener('click', (e) => {
    if (e.target.closest('a')) return;
    const card = e.target.closest('[data-kw]');
    if (card) openKwDetail(card.dataset.kw);
  });

  /* -- Zik view wiring ------------------------------------------------------ */
  document.querySelectorAll('.zk-tab').forEach((b) => b.addEventListener('click', () => {
    zkState.ztab = b.dataset.ztab;
    applyZkTab();
  }));
  const zkRerender = () => { renderZkTable(); renderZkTitle(); renderZkPrice(); };
  ['zk-product-search', 'zk-country', 'zk-vero', 'zk-dropship', 'zk-entries'].forEach((id) => {
    const el = $(id);
    if (el) el.addEventListener('input', zkRerender);
    if (el) el.addEventListener('change', zkRerender);
  });

  const intakeToggle = $('commerce-intake-toggle');
  if (intakeToggle) intakeToggle.addEventListener('click', () => {
    zkSetIntake($('commerce-intake-panel').hidden);
  });

  const searchBtn = $('commerce-search-btn');
  if (searchBtn) searchBtn.addEventListener('click', () => {
    const kw = ($('commerce-search').value || '').trim();
    if (!kw) return;
    const c = detailComps.find((x) => (x.keyword || '').toLowerCase() === kw.toLowerCase());
    if (c) {
      zkShowKeyword(c.keyword, { revenue_30d: c.revenue_30d, total: c.total, stats: c.stats, items: c.items });
      return;
    }
    const k = intake.keywords.find((x) => x.keyword.toLowerCase() === kw.toLowerCase()) || { keyword: kw, revenue_30d: null };
    zkShowKeyword(k.keyword, { revenue_30d: k.revenue_30d, items: [] });
  });

  const zkShareBtn = $('zk-share-btn');
  if (zkShareBtn) zkShareBtn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(location.href.split('#')[0] + '#' + encodeURIComponent(zkState.keyword));
      zkShareBtn.textContent = 'Copied ✓';
      setTimeout(() => { zkShareBtn.textContent = 'Share'; }, 1500);
    } catch { /* clipboard blocked */ }
  });
  const zkSaveBtn = $('zk-save');
  if (zkSaveBtn) zkSaveBtn.addEventListener('click', () => {
    if (!zkState.keyword) return;
    let list = [];
    try { list = JSON.parse(localStorage.getItem('zk-watchlist') || '[]'); } catch { list = []; }
    const has = list.includes(zkState.keyword);
    const next = has ? list.filter((k) => k !== zkState.keyword) : [...list, zkState.keyword];
    try { localStorage.setItem('zk-watchlist', JSON.stringify(next.slice(-50))); } catch { /* ignore */ }
    zkSaveBtn.textContent = next.includes(zkState.keyword) ? 'Saved ★' : 'Save to Watchlist';
  });
  const zkScanBtn = $('zk-scan');
  if (zkScanBtn) zkScanBtn.addEventListener('click', () => { zkRender(); zkScanBtn.textContent = 'Scanned ✓'; setTimeout(() => { zkScanBtn.textContent = 'Scan'; }, 1200); });

  // Deep pipeline: same intake through the n8n workflow (niches, live
  // comps, trends, vault report). Takes minutes; keys ride along per-run.
  const deepBtn = $('commerce-deep-btn');
  if (deepBtn) deepBtn.addEventListener('click', async () => {
    cmClearError();
    if (deepBtn.disabled) return;
    if (!intake.keywords.length) {
      cmError('Paste your Zik data in the box above first — your charts will build themselves.');
      return;
    }
    const appId = $('commerce-appid').value.trim();
    const certId = $('commerce-certid').value.trim();
    if (!appId || !certId) {
      cmError('The deep pipeline needs eBay keys to check live prices — open “eBay keys” above and paste them (this tab only, never stored).');
      return;
    }
    const cat = $('commerce-category').value.trim()
      || suggestCategory(intake.keywords[0].keyword);
    $('commerce-category').value = cat;
    const origLabel = deepBtn.textContent;
    deepBtn.disabled = true;
    deepBtn.textContent = 'Running…';
    $('commerce-progress').textContent =
      'Deep pipeline running — niches, prices, trends, report. Several minutes…';
    cmStep(2, 'done');
    cmStep(3, 'active');
    try {
      const r = await postJson('/api/commerce/deep-research', {
        category: cat, app_id: appId, cert_id: certId,
        keywords: intake.keywords.slice(0, 30),
        sellers: intake.sellers.slice(0, 12).map((s) => ({
          seller: s.seller, country: s.country || '',
          feedback: s.feedback || 0, sales_30d: s.sales_30d || 0,
        })),
      });
      const revByKw = {};
      intake.keywords.forEach((k) => { revByKw[k.keyword] = k.revenue_30d; });
      const comps = r.comps || [];
      $('commerce-verdict').innerHTML =
        `<div class="mono-sm text-cyan-dim mb-sm">DEEP PIPELINE · ${esc(r.category || cat)}</div>`
        + `<div style="white-space:pre-wrap">${esc(String(r.verdict || 'no verdict')).slice(0, 4000)}</div>`;
      $('commerce-comps-cards').innerHTML = comps.length ? comps.map((c, i) => {
        const rev = revByKw[c.keyword];
        const trend = c.trending === true
          ? `<span class="cm-pill ok">↗ trending</span>`
          : c.trending === false
            ? `<span class="cm-pill warn">→ flat</span>`
            : `<span class="cm-pill warn">trend n/a</span>`;
        const lo = c.min ?? 0, hi = c.max ?? 0;
        const span = (hi - lo) || 1;
        const medPct = Math.min(100, Math.max(0,
          Math.round(100 * ((c.med ?? lo) - lo) / span)));
        return `<div class="hud cm-kcard" data-kw="${esc(c.keyword || '')}" style="cursor:pointer"><div class="rank">#${i + 1}</div>`
          + `<div class="kw">${esc(c.keyword || '')}</div>`
          + (rev !== undefined ? `<div class="rev">${commerceMoney(rev)} <small>ZIK 30D</small></div>` : '')
          + `<div class="row" data-slot="status">`
          + `<span class="cm-pill ok">${Number(c.total || 0).toLocaleString()} live</span> ${trend}</div>`
          + (c.min != null
            ? `<div class="cm-range"><div class="med" style="left:${medPct}%"></div></div>`
              + `<div class="cm-range-lbls"><span>$${c.min.toFixed(2)}</span>`
              + `<span>med $${(c.med ?? c.min).toFixed(2)}</span><span>$${c.max.toFixed(2)}</span></div>`
            : '')
          + `<div class="row cm-src">${sourceLinks(c.keyword || '')}</div></div>`;
      }).join('') : '<div class="sm-empty">Pipeline returned no comps.</div>';
      cmKpis(undefined, undefined, undefined, `${comps.length} deep`);
      detailComps = comps.map((c) => ({
        ...c,
        revenue_30d: revByKw[c.keyword],
        stats: c.min != null ? { min: c.min, med: c.med, max: c.max, avg: c.avg } : null,
        items: c.items || [],
      }));
      if (detailComps.length) {
        const c0 = detailComps[0];
        zkShowKeyword(c0.keyword, {
          revenue_30d: c0.revenue_30d, total: c0.total, stats: c0.stats, items: c0.items,
        });
      }
      cmStep(3, 'done');
      cmStep(4, 'done');
      $('commerce-progress').textContent =
        `done — deep report saved${r.reportFile ? ': ' + r.reportFile : ''}`;
      $('commerce-save-msg').textContent = r.reportFile
        ? 'vault → Product Research/_intakes/' + r.reportFile : '';
      refreshTasks();
      loadCommerce();
    } catch (err) {
      cmError('Deep pipeline: ' + (err.message || err).slice(0, 220));
    } finally {
      deepBtn.disabled = false;
      deepBtn.textContent = origLabel;
    }
  });
})();


/* -- commerce boot ---------------------------------------------------------- */
loadCommerce();
