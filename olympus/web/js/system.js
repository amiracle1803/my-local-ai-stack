/* system.js — SYSTEM page: overview tables */

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
    try {
      const n8n = await j('/api/commerce/n8n');
      $('sys-n8n').innerHTML = n8n && n8n.reachable
        ? (n8n.items || []).map((w) =>
          `<tr><td>${esc(w.name || '')}</td>`
          + `<td><span class="cm-pill ${w.active ? 'ok' : ''}">${w.active ? 'ACTIVE' : 'PAUSED'}</span></td></tr>`
        ).join('') || '<tr><td colspan="2" class="text-dim">no workflows</td></tr>'
        : '<tr><td colspan="2" class="text-dim">n8n unreachable</td></tr>';
    } catch {
      $('sys-n8n').innerHTML = '<tr><td colspan="2" class="text-dim">n8n unreachable</td></tr>';
    }
  } catch { /* system page unavailable */ }
}



/* -- system boot -- */
refreshSystems();
refreshSystemPage();
setInterval(refreshSystems, 15000);
setInterval(refreshSystemPage, 20000);
