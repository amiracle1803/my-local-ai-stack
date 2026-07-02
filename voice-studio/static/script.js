const $ = id => document.getElementById(id);

// ── State ────────────────────────────────────────────────────
const state = {
  generating:      false,
  timerHandle:     null,
  timerStart:      null,
  lastElapsed:     null,
  currentBlobUrl:  null,
  currentFilename: null,
};

const voiceState = {
  pendingFile:  null,
  activeName:   null,
  useOnceMode:  false,
};

// ── Speed / engine state ──────────────────────────────────────
const PLAYBACK_SPEEDS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0];
let   playbackSpeedIdx = 2;    // index into PLAYBACK_SPEEDS, or -1 for custom
let   currentSpeed     = 1.0;  // actual speed including custom values
let   cfmSteps         = 2;    // Chatterbox CFM steps
let   nfeSteps         = 16;   // F5-TTS NFE steps
let   cfgStrength      = 2.0;  // F5-TTS CFG strength (0=fastest, 2=quality)
let   currentEngine    = 'f5'; // 'f5' | 'chatterbox' | 'humanize'

// ── Humanize state ────────────────────────────────────────────
let   currentKokoroVoice = 'af_heart';
let   kokoroSpeed        = 0.88;
let   stage1Only         = false;

// ── Progressive streaming audio ───────────────────────────────
const sp = {
  actx:      null,   // AudioContext
  gain:      null,   // GainNode
  nextAt:    0,      // next scheduled start (audioCtx time)
  startAt:   0,      // when first chunk's audio began (audioCtx time)
  totalDur:  0,      // accumulated real-time duration of all chunks (seconds)
  active:    false,
  peaks:     [],     // downsampled waveform peaks accumulated per chunk
  seekTimer: null,   // interval handle for seek-bar / time updates during streaming
};

function spInit() {
  if (sp.actx) sp.actx.close().catch(() => {});
  sp.actx      = new (window.AudioContext || window.webkitAudioContext)();
  sp.gain      = sp.actx.createGain();
  sp.gain.gain.value = (volumeBar ? volumeBar.value / 100 : 1);
  sp.gain.connect(sp.actx.destination);
  sp.nextAt    = sp.actx.currentTime + 0.08;
  sp.startAt   = sp.nextAt;
  sp.totalDur  = 0;
  sp.active    = true;
  sp.peaks     = [];

  // Prep canvas for incremental waveform
  const W = waveformCanvas.offsetWidth  || waveformCanvas.parentElement.clientWidth || 600;
  const H = waveformCanvas.offsetHeight || 100;
  waveformCanvas.width  = W;
  waveformCanvas.height = H;
  noAudioMsg.style.display = 'none';

  // Poll every 200 ms to update seek bar + current-time during streaming
  if (sp.seekTimer) clearInterval(sp.seekTimer);
  sp.seekTimer = setInterval(() => {
    if (!sp.active || !sp.actx) return;
    const elapsed = spElapsed();
    const total   = sp.totalDur;
    currentTimeEl.textContent = fmtTime(elapsed);
    totalTimeEl.textContent   = fmtTime(total);
    if (total > 0) seekBar.value = Math.min(100, (elapsed / total) * 100);
    // Also tick the waveform progress overlay
    if (sp.peaks.length > 0) paintStreamWave(total > 0 ? elapsed / total : 0);
  }, 200);
}

async function spSchedule(b64wav) {
  if (!sp.actx) return;
  const bytes   = Uint8Array.from(atob(b64wav), c => c.charCodeAt(0));
  const decoded = await sp.actx.decodeAudioData(bytes.buffer.slice(0));

  // Schedule audio
  const src = sp.actx.createBufferSource();
  src.buffer = decoded;
  src.playbackRate.value = currentSpeed;
  src.connect(sp.gain);
  src.start(sp.nextAt);
  sp.nextAt  += decoded.duration / currentSpeed;
  sp.totalDur += decoded.duration;

  // Accumulate ~60 downsampled peaks per chunk for live waveform
  const raw      = decoded.getChannelData(0);
  const nPeaks   = 60;
  const step     = Math.max(1, Math.floor(raw.length / nPeaks));
  for (let i = 0; i < nPeaks; i++) {
    let peak = 0;
    const start = i * step;
    for (let j = start; j < Math.min(start + step, raw.length); j++) {
      const v = Math.abs(raw[j]);
      if (v > peak) peak = v;
    }
    sp.peaks.push(peak);
  }
  paintStreamWave(0);

  // Show player chrome
  playerControls.style.display = 'flex';
  actionRow.style.display      = 'flex';
  playIcon.style.display       = 'none';
  pauseIcon.style.display      = 'block';
  seekBar.disabled             = true;
}

// Paint the accumulated stream waveform with a progress overlay
function paintStreamWave(playFraction) {
  const canvas = waveformCanvas;
  const ctx    = canvas.getContext('2d');
  const W      = canvas.width;
  const H      = canvas.height;
  if (!W || !H || sp.peaks.length === 0) return;

  ctx.clearRect(0, 0, W, H);
  const n = sp.peaks.length;

  for (let i = 0; i < n; i++) {
    const x     = Math.floor((i / n) * W);
    const amp   = sp.peaks[i] * (H / 2) * 0.88;
    const alpha = 0.2 + sp.peaks[i] * 0.8;
    const played = i / n < playFraction;
    ctx.fillStyle = played
      ? `rgba(124,58,237,${alpha})`
      : `rgba(255,255,255,${alpha * 0.22})`;
    ctx.fillRect(x, H / 2 - amp, Math.max(1, Math.floor(W / n)), amp * 2);
  }

  // Faint "still generating" shimmer to the right of known data
  if (playFraction < 0.98) {
    const shimX = Math.floor(n / n * W);  // always right edge of peaks so far
    const grad  = ctx.createLinearGradient(shimX, 0, W, 0);
    grad.addColorStop(0, 'rgba(124,58,237,0.12)');
    grad.addColorStop(1, 'rgba(124,58,237,0.02)');
    ctx.fillStyle = grad;
    ctx.fillRect(shimX, H / 2 - 4, W - shimX, 8);
  }
}

function spElapsed() {
  if (!sp.actx || !sp.active) return 0;
  return Math.max(0, sp.actx.currentTime - sp.startAt) * currentSpeed;
}

async function spFinalize(finalBlob, filename) {
  const elapsed = spElapsed();
  sp.active = false;
  if (sp.seekTimer) { clearInterval(sp.seekTimer); sp.seekTimer = null; }
  if (sp.actx) { await sp.actx.close().catch(() => {}); sp.actx = null; }
  seekBar.disabled = false;
  loadAudioBlob(finalBlob, filename);  // redraws waveform with full data
  const seekTo = () => {
    audioPlayer.currentTime = Math.min(elapsed, audioPlayer.duration || 0);
    audioPlayer.play();
  };
  if (audioPlayer.readyState >= 2) seekTo();
  else audioPlayer.addEventListener('loadedmetadata', seekTo, { once: true });
}

// ── DOM ──────────────────────────────────────────────────────
const textInput         = $('textInput');
const charCount         = $('charCount');
const exaggerationRange = $('exaggerationRange');
const exaggerationValue = $('exaggerationValue');
const cfgWeightRange    = $('cfgWeightRange');
const cfgWeightValue    = $('cfgWeightValue');
const filenameInput     = $('filenameInput');
const generateBtn       = $('generateBtn');
const generateTxt       = $('generateBtnText');

const timerElapsed  = $('timerElapsed');
const timerStatus   = $('timerStatus');
const timerTotal    = $('timerTotal');
const progressBar   = $('progressBar');
const lastBadge     = $('lastBadge');
const lastBadgeTime = $('lastBadgeTime');

const waveformCanvas = $('waveformCanvas');
const noAudioMsg     = $('noAudioMsg');
const playerControls = $('playerControls');
const actionRow      = $('actionRow');
const playerFileInfo = $('playerFileInfo');
const playIcon       = $('playIcon');
const pauseIcon      = $('pauseIcon');
const seekBar        = $('seekBar');
const currentTimeEl  = $('currentTime');
const totalTimeEl    = $('totalTime');
const volumeBar      = $('volumeBar');
const downloadBtn    = $('downloadBtn');
const fileStats      = $('fileStats');
const historyList    = $('historyList');
const audioPlayer    = $('audioPlayer');
const errorToast     = $('errorToast');
const successToast   = $('successToast');

// ── Init ─────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  loadHistory();
  loadSavedVoices();
  checkEngines();

  textInput.addEventListener('input', () => {
    const n = textInput.value.length;
    charCount.textContent = `${n.toLocaleString()} char${n === 1 ? '' : 's'}`;
  });

  exaggerationRange.addEventListener('input', () => {
    exaggerationValue.textContent = parseFloat(exaggerationRange.value).toFixed(2);
  });

  cfgWeightRange.addEventListener('input', () => {
    cfgWeightValue.textContent = parseFloat(cfgWeightRange.value).toFixed(2);
  });

  audioPlayer.addEventListener('timeupdate',     onTimeUpdate);
  audioPlayer.addEventListener('loadedmetadata', onMetadata);
  audioPlayer.addEventListener('ended',          onEnded);
  audioPlayer.addEventListener('play',  () => { playIcon.style.display = 'none';  pauseIcon.style.display = 'block'; });
  audioPlayer.addEventListener('pause', () => { playIcon.style.display = 'block'; pauseIcon.style.display = 'none';  });

  seekBar.addEventListener('input', () => {
    if (audioPlayer.duration) {
      audioPlayer.currentTime = (seekBar.value / 100) * audioPlayer.duration;
    }
  });

  volumeBar.addEventListener('input', () => {
    audioPlayer.volume = volumeBar.value / 100;
    if (sp.gain) sp.gain.gain.value = volumeBar.value / 100;
  });

  textInput.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') generateSpeech();
  });
});

// ── Voice Management ─────────────────────────────────────────
function onVoiceDrop(e) {
  e.preventDefault();
  $('voiceDropZone').classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) stageVoiceFile(file);
}

function onVoiceFileSelected(file) {
  if (file) stageVoiceFile(file);
}

function stageVoiceFile(file) {
  voiceState.pendingFile = file;
  const base = file.name.replace(/\.[^.]+$/, '').replace(/[^a-zA-Z0-9 _-]/g, '').trim();
  $('voiceNameInput').value = base;
  $('voiceSaveRow').style.display = 'flex';
}

// ── Voice Style Presets ───────────────────────────────────────
function applyPreset(btn, exag, cfg) {
  $('exaggerationRange').value = exag;
  $('cfgWeightRange').value    = cfg;
  $('exaggerationValue').textContent = exag.toFixed(2);
  $('cfgWeightValue').textContent    = cfg.toFixed(2);
  // only deactivate chips in the voice-styles row (not the gen-speed row)
  btn.closest('.presets-row').querySelectorAll('.preset-chip').forEach(b => b.classList.remove('preset-active'));
  btn.classList.add('preset-active');
}

function setEngine(btn, engine) {
  currentEngine = engine;
  $('engineRow').querySelectorAll('.preset-chip').forEach(b => b.classList.remove('preset-active'));
  btn.classList.add('preset-active');
  $('f5Controls').style.display          = engine === 'f5'        ? 'block' : 'none';
  $('chatterboxControls').style.display  = engine === 'chatterbox'? 'block' : 'none';
  $('humanizeControls').style.display    = engine === 'humanize'  ? 'block' : 'none';
  const notes = {
    f5:          'Zero-shot voice cloning • ~20× realtime • MIT',
    chatterbox:  'Highest quality • Voice cloning • MIT',
    humanize:    'Kokoro → XTTS-v2 • Two-stage humanization • Local • Free',
  };
  $('engineNote').textContent = notes[engine] || '';
}

function setKokoroVoice(btn, voice) {
  currentKokoroVoice = voice;
  $('kokoroVoiceRow').querySelectorAll('.preset-chip').forEach(b => b.classList.remove('preset-active'));
  btn.classList.add('preset-active');
}

function setKokoroSpeed(btn, speed) {
  kokoroSpeed = speed;
  $('kokoroSpeedRow').querySelectorAll('.preset-chip').forEach(b => b.classList.remove('preset-active'));
  btn.classList.add('preset-active');
}

function onStage1OnlyChange() {
  stage1Only = $('stage1OnlyCheck').checked;
}

async function checkEngines() {
  try {
    const d = await (await fetch('/api/engines')).json();
    const chip = $('humanizeChip');
    if (!chip) return;
    if (!d.humanize) {
      chip.disabled = true;
      const missing = [];
      if (!d.kokoro) missing.push('kokoro soundfile');
      if (!d.xtts)   missing.push('TTS');
      chip.title = missing.length
        ? `Missing: pip install ${missing.join(' && pip install ')}`
        : 'Humanize unavailable';
    }
  } catch {}
}

function setNfeSteps(btn, steps, cfg) {
  nfeSteps    = steps;
  cfgStrength = cfg;
  $('nfeStepsRow').querySelectorAll('.preset-chip').forEach(b => b.classList.remove('preset-active'));
  btn.classList.add('preset-active');
}

function setGenSpeed(btn, steps) {
  cfmSteps = steps;
  $('genSpeedRow').querySelectorAll('.preset-chip').forEach(b => b.classList.remove('preset-active'));
  btn.classList.add('preset-active');
}

// ── Playback speed ────────────────────────────────────────────
function setPlaybackSpeed(btn, idx) {
  playbackSpeedIdx = idx;
  currentSpeed     = PLAYBACK_SPEEDS[idx];
  audioPlayer.playbackRate = currentSpeed;
  const inp = $('customSpeedInput');
  if (inp) inp.value = currentSpeed;
  updateSpeedBtn();
  updateSpeedChips();
}

function cyclePlaybackSpeed() {
  playbackSpeedIdx = (playbackSpeedIdx + 1) % PLAYBACK_SPEEDS.length;
  currentSpeed     = PLAYBACK_SPEEDS[playbackSpeedIdx];
  audioPlayer.playbackRate = currentSpeed;
  const inp = $('customSpeedInput');
  if (inp) inp.value = currentSpeed;
  updateSpeedBtn();
  updateSpeedChips();
}

function onCustomSpeedInput() {
  const inp = $('customSpeedInput');
  const val = parseFloat(inp.value);
  if (!isNaN(val) && val >= 0.1 && val <= 4.0) {
    currentSpeed = val;
    audioPlayer.playbackRate = val;
    playbackSpeedIdx = PLAYBACK_SPEEDS.findIndex(s => Math.abs(s - val) < 0.001);
    updateSpeedBtn();
    updateSpeedChips();
  }
}

function applyCustomSpeed() {
  const inp = $('customSpeedInput');
  let val = parseFloat(inp.value);
  if (isNaN(val) || val < 0.1) val = 0.1;
  if (val > 4.0) val = 4.0;
  val = Math.round(val * 100) / 100;
  inp.value = val;
  currentSpeed = val;
  audioPlayer.playbackRate = val;
  playbackSpeedIdx = PLAYBACK_SPEEDS.findIndex(s => Math.abs(s - val) < 0.001);
  updateSpeedBtn();
  updateSpeedChips();
}

function updateSpeedBtn() {
  const btn = $('speedBtn');
  if (btn) btn.textContent = `${currentSpeed}x`;
}

function updateSpeedChips() {
  const row = $('playbackSpeedRow');
  if (!row) return;
  row.querySelectorAll('.preset-chip').forEach((b, i) => {
    b.classList.toggle('preset-active', i === playbackSpeedIdx);
  });
}

function toggleVoiceUpload() {
  const panel = $('voiceUploadPanel');
  const open  = panel.style.display !== 'none';
  panel.style.display = open ? 'none' : 'block';
  if (!open) {
    $('voiceSaveRow').style.display = 'none';
    $('voiceFileInput').value = '';
    voiceState.pendingFile = null;
  }
}

function onVoiceSelectChange() {
  const sel = $('voiceSelect');
  voiceState.activeName  = sel.value || null;
  voiceState.useOnceMode = false;
  $('voiceDeleteBtn').style.display = voiceState.activeName ? 'flex' : 'none';
}

async function saveVoice() {
  const file = voiceState.pendingFile;
  if (!file) { showError('No audio file selected.'); return; }
  const name = $('voiceNameInput').value.trim();
  if (!name) { showError('Enter a name for this voice.'); return; }

  const fd = new FormData();
  fd.append('audio',   file);
  fd.append('name',    name);
  fd.append('refText', ($('voiceRefText')?.value || '').trim());

  try {
    const r = await fetch('/api/voices/upload', { method: 'POST', body: fd });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || 'Upload failed');
    voiceState.pendingFile = null;
    $('voiceSaveRow').style.display = 'none';
    $('voiceFileInput').value = '';
    $('voiceUploadPanel').style.display = 'none';
    showSuccess(`Voice "${d.name}" saved to library.`);
    await loadSavedVoices();
    voiceState.activeName  = d.name;
    voiceState.useOnceMode = false;
    $('voiceSelect').value = d.name;
    $('voiceDeleteBtn').style.display = 'flex';
  } catch (err) {
    showError(err.message);
  }
}

async function useVoiceOnce() {
  const file = voiceState.pendingFile;
  if (!file) { showError('No audio file selected.'); return; }

  const tempName = `_once_${Date.now()}`;
  const fd = new FormData();
  fd.append('audio', file);
  fd.append('name',  tempName);

  try {
    const r = await fetch('/api/voices/upload', { method: 'POST', body: fd });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || 'Upload failed');
    voiceState.pendingFile  = null;
    voiceState.activeName   = d.name;
    voiceState.useOnceMode  = true;
    $('voiceSaveRow').style.display    = 'none';
    $('voiceFileInput').value          = '';
    $('voiceUploadPanel').style.display = 'none';
    const sel = $('voiceSelect');
    for (let i = sel.options.length - 1; i >= 0; i--) {
      if (sel.options[i].value.startsWith('_once_')) sel.remove(i);
    }
    const opt = document.createElement('option');
    opt.value = d.name;
    opt.textContent = '(Use Once — temp)';
    sel.appendChild(opt);
    sel.value = d.name;
    $('voiceDeleteBtn').style.display = 'none';
    showSuccess('Voice ready — will be used for the next generation only.');
  } catch (err) {
    showError(err.message);
  }
}

async function deleteSelectedVoice() {
  const name = voiceState.activeName;
  if (!name) return;
  try {
    await fetch(`/api/voices/${encodeURIComponent(name)}`, { method: 'DELETE' });
    voiceState.activeName  = null;
    voiceState.useOnceMode = false;
    $('voiceSelect').value = '';
    $('voiceDeleteBtn').style.display = 'none';
    showSuccess(`Voice "${name}" deleted.`);
    loadSavedVoices();
  } catch {}
}

async function loadSavedVoices() {
  try {
    const d = await (await fetch('/api/voices')).json();
    window._savedVoices = d.voices || [];
    populateVoiceSelect(window._savedVoices);
  } catch {}
}

function populateVoiceSelect(voices) {
  const sel = $('voiceSelect');
  if (!sel) return;
  const prevVal = voiceState.activeName || '';
  while (sel.options.length > 1) sel.remove(1);
  voices.forEach(v => {
    const opt = document.createElement('option');
    opt.value = v.name;
    opt.textContent = v.name;
    sel.appendChild(opt);
  });
  sel.value = prevVal;
  if (sel.value !== prevVal) {
    sel.value = '';
    voiceState.activeName  = null;
    voiceState.useOnceMode = false;
  }
  $('voiceDeleteBtn').style.display =
    (voiceState.activeName && !voiceState.useOnceMode) ? 'flex' : 'none';
}

// ── Timer helpers ─────────────────────────────────────────────
function fmtHMS(sec) {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  return `${m}:${String(s).padStart(2,'0')}`;
}

// ── Timer ────────────────────────────────────────────────────
function timerStart() {
  state.timerStart = performance.now();
  progressBar.className = 'progress-fill indeterminate';
  setStatus('Generating', '#f59e0b');
  timerElapsed.textContent = '0:00';
  timerTotal.textContent   = '--';
  state.timerHandle = setInterval(() => {
    const sec = (performance.now() - state.timerStart) / 1000;
    timerElapsed.textContent = fmtHMS(sec);
  }, 500);
}

function timerStop(clientSec) {
  clearInterval(state.timerHandle);
  state.timerHandle = null;
  state.lastElapsed = clientSec;
  timerElapsed.textContent  = fmtHMS(clientSec);
  timerTotal.textContent    = fmtHMS(clientSec);
  progressBar.className     = 'progress-fill full';
  setStatus('Done', '#22c55e');
  lastBadgeTime.textContent = fmtHMS(clientSec);
  lastBadge.style.display   = 'flex';
}

function timerError() {
  clearInterval(state.timerHandle);
  state.timerHandle = null;
  const sec = state.timerStart ? (performance.now() - state.timerStart) / 1000 : 0;
  timerElapsed.textContent = fmtHMS(sec);
  progressBar.className    = 'progress-fill error';
  setStatus('Error', '#ef4444');
}

function timerReset() {
  clearInterval(state.timerHandle);
  state.timerHandle = null;
  timerElapsed.textContent = '0:00';
  timerTotal.textContent   = '--';
  progressBar.className    = 'progress-fill';
  progressBar.style.width  = '0%';
  setStatus('Ready', '');
}

function setStatus(text, color) {
  timerStatus.textContent = text;
  timerStatus.style.color = color;
}

// ── Humanize ─────────────────────────────────────────────────
async function generateHumanize() {
  if (state.generating) return;

  const text = textInput.value.trim();
  if (!text) { showError('Please enter some text first.'); return; }

  const filename = filenameInput.value.trim() ||
    text.split(/\s+/).slice(0, 5).join('_').replace(/[^a-zA-Z0-9_]/g, '') ||
    `humanized_${Date.now()}`;

  state.generating = true;
  generateBtn.disabled = true;
  generateBtn.classList.add('loading');
  generateTxt.textContent = 'Stage 1: Kokoro...';
  timerReset();
  timerStart();

  // Transition status label ~10s in to reflect Stage 2
  const stageTimer = setTimeout(() => {
    if (!state.generating) return;
    generateTxt.textContent = 'Stage 2: Fish Speech...';
    setStatus('Stage 2', '#06b6d4');
  }, 10000);

  const fetchStart = performance.now();

  try {
    const resp = await fetch('/api/humanize', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        filename,
        kokoro_voice: currentKokoroVoice,
        kokoro_speed: kokoroSpeed,
        stage1_only:  stage1Only,
      }),
    });

    clearTimeout(stageTimer);
    const d = await resp.json();
    if (!resp.ok || d.error) throw new Error(d.error || `Server error ${resp.status}`);

    const clientSec = (performance.now() - fetchStart) / 1000;
    timerStop(clientSec);

    const bytes = Uint8Array.from(atob(d.audioData), c => c.charCodeAt(0));
    const blob  = new Blob([bytes], { type: 'audio/wav' });
    loadAudioBlob(blob, d.filename);

    const kb        = (d.fileSize / 1024).toFixed(1);
    const stageNote = d.stage === 'humanized' ? 'Kokoro &rarr; XTTS-v2' : 'Kokoro only';
    fileStats.innerHTML =
      `<span class="stat-hi">${escHtml(d.filename)}</span> &nbsp;&bull;&nbsp; ${kb} KB &nbsp;&bull;&nbsp; ${fmtHMS(clientSec)} &nbsp;&bull;&nbsp; ${stageNote}`;

    downloadBtn.onclick = () => dlFile(d.filename);

    audioPlayer.addEventListener('loadedmetadata', () => {
      const durNote = `${fmtTime(audioPlayer.duration)} audio`;
      showSuccess(`Humanized in ${fmtHMS(clientSec)} — ${durNote} — ${d.filename}`);
    }, { once: true });
    if (audioPlayer.readyState >= 1) audioPlayer.dispatchEvent(new Event('loadedmetadata'));

    loadHistory();
    filenameInput.value = '';

  } catch (err) {
    clearTimeout(stageTimer);
    timerError();
    showError(err.message || 'Humanize failed.');
    console.error(err);
  } finally {
    state.generating = false;
    generateBtn.disabled = false;
    generateBtn.classList.remove('loading');
    generateTxt.textContent = 'Generate Speech';
  }
}

// ── Generate ─────────────────────────────────────────────────
async function generateSpeech() {
  if (currentEngine === 'humanize') return generateHumanize();
  if (state.generating) return;

  const text = textInput.value.trim();
  if (!text) { showError('Please enter some text first.'); return; }

  const filename = filenameInput.value.trim() ||
    text.split(/\s+/).slice(0, 5).join('_').replace(/[^a-zA-Z0-9_]/g, '') ||
    `tts_${Date.now()}`;

  state.generating = true;
  generateBtn.disabled = true;
  generateBtn.classList.add('loading');
  generateTxt.textContent = 'Generating...';
  timerReset();
  timerStart();

  const fetchStart = performance.now();

  // Collected audio chunks for final blob assembly
  const chunkAudios = [];
  let   doneData    = null;
  let   multiChunk  = false;   // true once we know there are >1 chunks

  try {
    const resp = await fetch('/api/generate_stream', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        filename,
        engine:       currentEngine,
        exaggeration: parseFloat(exaggerationRange?.value || 0.5),
        cfgWeight:    parseFloat(cfgWeightRange?.value    || 0.0),
        voiceName:    voiceState.activeName || '',
        cfmSteps:     cfmSteps,
        nfeSteps:     nfeSteps,
        cfgStrength:  cfgStrength,
      }),
    });

    if (!resp.ok) throw new Error(`Server error ${resp.status}`);

    // Read SSE stream line by line
    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let   buf     = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      // Process all complete lines
      let nl;
      while ((nl = buf.indexOf('\n')) !== -1) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line.startsWith('data: ')) continue;
        let evt;
        try { evt = JSON.parse(line.slice(6)); } catch { continue; }

        if (evt.type === 'progress') {
          // Kick off streaming audio context on first progress event with >1 chunks
          if (evt.chunk === 1 && evt.total > 1) { multiChunk = true; spInit(); }
          generateTxt.textContent = `Generating… ${evt.chunk}/${evt.total}`;
          progressBar.style.width = `${Math.round((evt.chunk / evt.total) * 85)}%`;

        } else if (evt.type === 'chunk') {
          chunkAudios[evt.index] = evt.audio;
          if (multiChunk) await spSchedule(evt.audio);   // play immediately

        } else if (evt.type === 'done') {
          doneData = evt;

        } else if (evt.type === 'error') {
          throw new Error(evt.error);
        }
      }
    }

    if (!doneData) throw new Error('Server closed without a done event.');

    const clientSec = (performance.now() - fetchStart) / 1000;
    timerStop(clientSec);

    // Clean up use-once temp voice
    if (voiceState.useOnceMode && voiceState.activeName) {
      fetch(`/api/voices/${encodeURIComponent(voiceState.activeName)}`, { method: 'DELETE' }).catch(() => {});
      voiceState.activeName  = null;
      voiceState.useOnceMode = false;
      const sel = $('voiceSelect');
      for (let i = sel.options.length - 1; i >= 0; i--) {
        if (sel.options[i].value.startsWith('_once_')) sel.remove(i);
      }
      sel.value = '';
      $('voiceDeleteBtn').style.display = 'none';
      loadSavedVoices();
    }

    // Build final blob from collected chunks
    const blob = chunkAudios.filter(Boolean).length > 0
      ? await concatWavChunks(chunkAudios.filter(Boolean))
      : await (await fetch(`/play/${encodeURIComponent(doneData.filename)}`)).blob();

    if (multiChunk) {
      // Transition: stop Web Audio, load into regular player at current position
      await spFinalize(blob, doneData.filename);
    } else {
      loadAudioBlob(blob, doneData.filename);
    }

    const kb         = (doneData.fileSize / 1024).toFixed(1);
    const chunkLabel = doneData.chunks > 1 ? ` &nbsp;&bull;&nbsp; ${doneData.chunks} chunks` : '';
    fileStats.innerHTML =
      `<span class="stat-hi">${escHtml(doneData.filename)}</span> &nbsp;&bull;&nbsp; ${kb} KB &nbsp;&bull;&nbsp; ${fmtHMS(clientSec)}${chunkLabel}`;

    downloadBtn.onclick = () => dlFile(doneData.filename);
    const chunkNote = doneData.chunks > 1 ? ` · ${doneData.chunks} segments` : '';
    // Show realtime speed ratio once audio duration is known
    audioPlayer.addEventListener('loadedmetadata', () => {
      const rtx = doneData.serverElapsed > 0
        ? (audioPlayer.duration / doneData.serverElapsed).toFixed(1)
        : '?';
      showSuccess(`Done in ${fmtHMS(clientSec)}${chunkNote} · ${rtx}× realtime — ${doneData.filename}`);
    }, { once: true });
    // Fallback in case metadata fires before we attach
    if (audioPlayer.readyState >= 1) audioPlayer.dispatchEvent(new Event('loadedmetadata'));
    loadHistory();
    filenameInput.value = '';

  } catch (err) {
    timerError();
    showError(err.message || 'Generation failed.');
    console.error(err);
  } finally {
    state.generating = false;
    generateBtn.disabled = false;
    generateBtn.classList.remove('loading');
    generateTxt.textContent = 'Generate Speech';
  }
}

// Decode all WAV chunks via AudioContext, concatenate PCM, re-encode as WAV blob
async function concatWavChunks(base64Chunks) {
  const actx    = new (window.AudioContext || window.webkitAudioContext)();
  const buffers = await Promise.all(base64Chunks.map(b64 => {
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    return actx.decodeAudioData(bytes.buffer.slice(0));
  }));
  await actx.close();

  const sampleRate  = buffers[0].sampleRate;
  const totalFrames = buffers.reduce((s, b) => s + b.length, 0);
  const pcm         = new Float32Array(totalFrames);
  let   offset      = 0;
  for (const buf of buffers) {
    pcm.set(buf.getChannelData(0), offset);
    offset += buf.length;
  }
  return encodeWav(pcm, sampleRate);
}

function encodeWav(samples, sampleRate) {
  const dataLen = samples.length * 2;
  const ab      = new ArrayBuffer(44 + dataLen);
  const v       = new DataView(ab);
  const str     = (off, s) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); v.setUint32(4,  36 + dataLen,    true);
  str(8, 'WAVE'); str(12, 'fmt ');
  v.setUint32(16, 16,          true);  // chunk size
  v.setUint16(20, 1,           true);  // PCM
  v.setUint16(22, 1,           true);  // mono
  v.setUint32(24, sampleRate,  true);
  v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2,           true);  // block align
  v.setUint16(34, 16,          true);  // bit depth
  str(36, 'data'); v.setUint32(40, dataLen, true);
  let off = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    off += 2;
  }
  return new Blob([ab], { type: 'audio/wav' });
}

// ── Audio ────────────────────────────────────────────────────
function loadAudioBlob(blob, filename) {
  if (state.currentBlobUrl) URL.revokeObjectURL(state.currentBlobUrl);
  state.currentBlobUrl  = URL.createObjectURL(blob);
  state.currentFilename = filename;
  audioPlayer.src = state.currentBlobUrl;
  audioPlayer.load();
  audioPlayer.playbackRate = currentSpeed;
  audioPlayer.play();
  playerFileInfo.textContent   = filename;
  noAudioMsg.style.display     = 'none';
  playerControls.style.display = 'flex';
  actionRow.style.display      = 'flex';
  drawWaveform(blob);
}

function togglePlayPause() {
  if (audioPlayer.paused) audioPlayer.play();
  else audioPlayer.pause();
}

function onTimeUpdate() {
  if (!audioPlayer.duration) return;
  const pct = (audioPlayer.currentTime / audioPlayer.duration) * 100;
  seekBar.value = pct;
  currentTimeEl.textContent = fmtTime(audioPlayer.currentTime);
  drawWaveformProgress(pct / 100);
}

function onMetadata() {
  totalTimeEl.textContent = fmtTime(audioPlayer.duration);
}

function onEnded() {
  seekBar.value = 0;
  currentTimeEl.textContent = '0:00';
}

function fmtTime(s) {
  if (!isFinite(s)) return '0:00';
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

// ── Waveform ─────────────────────────────────────────────────
let waveData = null;

async function drawWaveform(blob) {
  const W = waveformCanvas.offsetWidth  || waveformCanvas.parentElement.clientWidth;
  const H = waveformCanvas.offsetHeight || 100;
  waveformCanvas.width  = W;
  waveformCanvas.height = H;

  const buf  = await blob.arrayBuffer();
  const actx = new (window.AudioContext || window.webkitAudioContext)();
  let decoded;
  try {
    decoded = await actx.decodeAudioData(buf);
  } catch {
    waveData = new Float32Array(W).map(() => Math.random() * 0.5 + 0.15);
    paintWave(0);
    actx.close();
    return;
  }

  const raw  = decoded.getChannelData(0);
  const step = Math.ceil(raw.length / W);
  waveData   = new Float32Array(W);
  for (let i = 0; i < W; i++) {
    let peak = 0;
    for (let j = 0; j < step; j++) {
      const v = Math.abs(raw[i * step + j] || 0);
      if (v > peak) peak = v;
    }
    waveData[i] = peak;
  }
  actx.close();
  paintWave(0);
}

function drawWaveformProgress(pct) {
  if (!waveData) return;
  paintWave(pct);
}

function paintWave(pct) {
  if (!waveData) return;
  const canvas = waveformCanvas;
  const ctx    = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;
  const playX = W * pct;

  ctx.clearRect(0, 0, W, H);
  for (let i = 0; i < W; i++) {
    const amp   = waveData[i] * (H / 2) * 0.88;
    const alpha = 0.2 + waveData[i] * 0.8;
    ctx.fillStyle = i < playX
      ? `rgba(124,58,237,${alpha})`
      : `rgba(255,255,255,${alpha * 0.2})`;
    ctx.fillRect(i, H / 2 - amp, 1, amp * 2);
  }
}

// ── Download ─────────────────────────────────────────────────
function dlFile(filename) {
  const a = document.createElement('a');
  a.href     = `/download/${encodeURIComponent(filename)}`;
  a.download = filename;
  a.click();
}

// ── History ──────────────────────────────────────────────────
async function loadHistory() {
  try {
    const d = await (await fetch('/api/files')).json();
    renderHistory(d.files || []);
  } catch {
    historyList.innerHTML = '<div class="history-empty">Could not load files.</div>';
  }
}

function renderHistory(files) {
  if (!files.length) {
    historyList.innerHTML = '<div class="history-empty">No files yet.</div>';
    return;
  }
  historyList.innerHTML = files.map(f => `
    <div class="history-item">
      <div class="history-icon">
        <svg viewBox="0 0 24 24" fill="none" width="13" stroke="#a78bfa" stroke-width="1.5">
          <path d="M9 18V5l12-2v13" stroke-linecap="round"/>
          <circle cx="6" cy="18" r="3"/>
          <circle cx="18" cy="16" r="3"/>
        </svg>
      </div>
      <div class="history-info">
        <div class="history-name">${escHtml(f.name)}</div>
        <div class="history-meta mono">${fmtBytes(f.size)} &bull; ${escHtml(f.created)}</div>
      </div>
      <div class="history-actions">
        <button class="icon-btn" title="Play" onclick="playFromHistory('${escHtml(f.name)}')">
          <svg viewBox="0 0 24 24" fill="currentColor" width="12"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        </button>
        <button class="icon-btn" title="Download" onclick="dlFile('${escHtml(f.name)}')">
          <svg viewBox="0 0 24 24" fill="none" width="12" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/><path d="M5 20h14"/></svg>
        </button>
      </div>
    </div>
  `).join('');
}

async function playFromHistory(filename) {
  const url = `/play/${encodeURIComponent(filename)}`;

  if (state.currentBlobUrl) {
    URL.revokeObjectURL(state.currentBlobUrl);
    state.currentBlobUrl = null;
  }

  audioPlayer.src = url;
  audioPlayer.load();
  audioPlayer.play();

  playerFileInfo.textContent   = filename;
  noAudioMsg.style.display     = 'none';
  playerControls.style.display = 'flex';
  actionRow.style.display      = 'flex';
  fileStats.innerHTML = `Playing: <span class="stat-hi">${escHtml(filename)}</span>`;
  downloadBtn.onclick = () => dlFile(filename);

  waveData = null;
  try {
    const blob = await (await fetch(url)).blob();
    drawWaveform(blob);
  } catch {}
}

// ── Toasts ───────────────────────────────────────────────────
let errTO, okTO;
function showError(msg) {
  $('errorMsg').textContent = msg;
  errorToast.classList.add('show');
  clearTimeout(errTO);
  errTO = setTimeout(() => errorToast.classList.remove('show'), 5000);
}
function showSuccess(msg) {
  $('successMsg').textContent = msg;
  successToast.classList.add('show');
  clearTimeout(okTO);
  okTO = setTimeout(() => successToast.classList.remove('show'), 4000);
}

// ── Helpers ──────────────────────────────────────────────────
function fmtBytes(b) {
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
  return (b / 1048576).toFixed(2) + ' MB';
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
