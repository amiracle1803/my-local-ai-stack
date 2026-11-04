/* studio.js — STUDIO page: anime/manga pipeline */

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
  { id: 'stage2',           icon: '📝', title: 'STAGE 2 · SCREENPLAY',
    sst: 'narration + dialogue + SFX · story beats · pacing · source-fidelity gate' },
  { id: 'stage4',           icon: '🎙', title: 'STAGE 4 · AUDIO',
    sst: 'Kokoro TTS · narration + per-character voices · timed editorial spine' },
  { id: 'stage3',           icon: '🎞️', title: 'STAGE 3 · STORYBOARD',
    sst: 'enrich the timed screenplay · blocks · shot direction · composition prompts' },
  { id: 'stage1r',          icon: '👤', title: 'STAGE 1R · REFERENCES',
    sst: '10+ refs per character (360° full body) · locations + assets · style pick · voice ID' },
  { id: 'stage3b',          icon: '🎨', title: 'STAGE 3B · IMAGES',
    sst: 'one image per shot · same anchors = consistent characters' },
  { id: 'stage3c',          icon: '🎞️', title: 'STAGE 3C · ANIMATION',
    sst: 'motion per panel → clips · motion tiers · facial anchors (panels mode skips)' },
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
  '0s': 'FAITHFUL — from a finished script. Pasted verbatim, never rewritten; scenes split only.',
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

const PROVIDER_CAPABILITIES = ['llm', 'vision', 't2i', 'i2i', 'i2v', 'tts'];
let _providerData = null;

async function loadProviderRegistry() {
  _providerData = await j('/api/providers');
  return _providerData;
}

function providerLabel(id, data) {
  return data.providers[id]?.display_name || id;
}

async function openProviderSettings() {
  const modal = $('provider-modal');
  const body = $('provider-modal-body');
  if (!modal || !body) return;
  try {
    const data = await loadProviderRegistry();
    body.innerHTML = `<div class="sm-hint">Local providers are the default. Hosted providers require configured credentials and remain opt-in.</div>
      <div class="provider-grid">${PROVIDER_CAPABILITIES.map((capability) => {
        const selected = data.selections[capability] || { provider: '' };
        const options = Object.entries(data.providers)
          .filter(([, provider]) => provider.capabilities.includes(capability))
          .map(([id, provider]) => `<option value="${esc(id)}" ${id === selected.provider ? 'selected' : ''} ${!provider.enabled ? 'disabled' : ''}>${esc(provider.display_name)}${provider.experimental ? ' · experimental' : ''}</option>`).join('');
        return `<label class="provider-row"><span class="label">${esc(capability.toUpperCase())}</span><select class="provider-select" data-capability="${esc(capability)}">${options}</select><span class="hint-sm provider-health" data-provider-health="${esc(capability)}"></span></label>`;
      }).join('')}</div>
      <div class="flex mt-sm"><button class="primary" id="provider-apply">APPLY</button><button class="ghost" id="provider-reset">RESET TO LOCAL</button><span id="provider-error" class="err-sm"></span></div>`;
    modal.classList.add('open');
    const refreshHealth = () => body.querySelectorAll('.provider-select').forEach((select) => {
      const provider = data.providers[select.value];
      const health = body.querySelector(`[data-provider-health="${select.dataset.capability}"]`);
      if (health) health.textContent = provider?.integration_status === 'unavailable'
        ? 'not wired'
        : provider?.credential_present === false && provider.kind === 'hosted'
          ? '✗ credentials missing'
          : provider?.kind === 'hosted' ? 'hosted · quota-limited' : 'local';
    });
    refreshHealth();
    body.querySelectorAll('.provider-select').forEach((select) => select.addEventListener('change', refreshHealth));
    $('provider-apply').onclick = async () => {
      const selections = {};
      body.querySelectorAll('.provider-select').forEach((select) => { selections[select.dataset.capability] = { provider: select.value }; });
      try { _providerData = await postJson('/api/providers/settings', { selections }); modal.classList.remove('open'); setLastMsg('provider routing applied', 'ok'); }
      catch (error) { $('provider-error').textContent = (error.message || error).slice(0, 200); }
    };
    $('provider-reset').onclick = async () => {
      try { _providerData = await postJson('/api/providers/reset-local', {}); await openProviderSettings(); setLastMsg('provider routing reset to local defaults', 'ok'); }
      catch (error) { $('provider-error').textContent = (error.message || error).slice(0, 200); }
    };
  } catch (error) {
    body.innerHTML = `<div class="sm-empty">provider registry unavailable: ${esc(error.message || error)}</div>`;
    modal.classList.add('open');
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
  } else if (intake === '0s') {
    text.placeholder = 'Finished script — used verbatim (SCENE/Chapter headings + NAME: dialogue lines preserved)…';
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
    const pf = $('np-panels').files[0];
    if (intake === '0i' && pf) await uploadPanels(slug, pf);
    $('np-slug').value = ''; $('np-text').value = ''; $('np-panels').value = '';
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
        `fps ${st.fps} · mode ${st.mode || '0b'} · story_id ${String(st.story_id || 'unknown').slice(0, 8)}…`;
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
        ${mode === '0s' ? `
          <div class="sm-step">FAITHFUL SCRIPT (verbatim — never rewritten)</div>
          <textarea id="setup-source" placeholder="Paste the finished script here…"></textarea>` : ''}
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
          } else if (mode === '0s') {
            const source = ($('setup-source') || {}).value || '';
            if (!source.trim()) throw new Error('script text is required');
            out.source_text = source;
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

async function viewDossier(list) {
  const dossier = list.find((a) => a.path === 'intake/dossier.json');
  if (!dossier) return '';
  try {
    const data = await fetchJson(dossier.path);
    const people = asList(data.characters || data.people);
    let html = '<div class="sm-section-title">INTAKE DOSSIER</div>';
    if (data.title || data.synopsis) html += `<div class="char-card"><div class="cname">${esc(data.title || 'DOSSIER')}</div><div class="capp">${esc(data.synopsis || '')}</div></div>`;
    if (people.length) html += people.map((person) => `<div class="char-card"><div class="cname">${esc(person.name || person.id || 'CHARACTER')}</div><div class="capp">${esc(person.appearance || person.description || person.role || '')}</div></div>`).join('');
    return html + (!people.length && !data.synopsis ? smDocHtml(dossier.path) : '');
  } catch { return smDocHtml(dossier.path); }
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
  const srt = list.find((a) => a.path === 'video/final.srt' || a.path === 'video/subtitles.srt');
  const chapters = list.find((a) => a.path === 'video/chapters.ffmetadata');
  if (srt) html += `<div class="sm-section-title">SUBTITLES (.srt)</div>` + smDocHtml(srt.path);
  if (chapters) html += `<div class="sm-section-title">CHAPTERS</div>` + smDocHtml(chapters.path);
  return html;
}

// Map each stage to its human-readable viewer; fall back to a plain JSON doc
const STAGE_VIEWERS = {
    stage0: viewStage0, stage0_dossier: viewDossier, stage1: viewWorldBible,
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

const providerModal = $('provider-modal');
$('provider-settings-btn')?.addEventListener('click', openProviderSettings);
$('provider-modal-close')?.addEventListener('click', () => providerModal.classList.remove('open'));
providerModal?.addEventListener('click', (e) => { if (e.target === providerModal) providerModal.classList.remove('open'); });

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
loadProviderRegistry().catch(() => {});

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
setInterval(() => { if (document.querySelector('#page-studio.active')) loadProviderRegistry().catch(() => {}); }, 30000);

