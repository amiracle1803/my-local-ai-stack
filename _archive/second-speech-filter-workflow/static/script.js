let referenceFile = null;
let busy = false;

// ── text counter ──────────────────────────────────────────
document.getElementById('textInput').addEventListener('input', function () {
  document.getElementById('charCount').textContent = this.value.length;
});

// ── drop zone ─────────────────────────────────────────────
const dropZone  = document.getElementById('dropZone');
const fileInput = document.getElementById('audioFile');

dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
});
dropZone.addEventListener('click', () => fileInput.click());
document.getElementById('browseBtn').addEventListener('click', e => {
  e.stopPropagation();
  fileInput.click();
});
fileInput.addEventListener('change', e => {
  if (e.target.files[0]) setFile(e.target.files[0]);
});
document.getElementById('clearBtn').addEventListener('click', clearFile);

function setFile(file) {
  const MAX_BYTES = 500 * 1024 * 1024;
  if (file.size > MAX_BYTES) {
    showErr(`File is too large (${(file.size / 1024 / 1024).toFixed(0)} MB). Maximum is 500 MB.`);
    return;
  }
  referenceFile = file;
  const mb = (file.size / 1024 / 1024).toFixed(1);
  document.getElementById('fileName').textContent = `${file.name}  (${mb} MB)`;
  document.getElementById('fileInfo').style.display = 'flex';
  dropZone.style.display = 'none';
}

function clearFile() {
  referenceFile = null;
  fileInput.value = '';
  document.getElementById('fileInfo').style.display = 'none';
  dropZone.style.display = '';
}

// ── status ────────────────────────────────────────────────
checkStatus();

async function checkStatus() {
  try {
    const d = await (await fetch('/api/status')).json();
    const dot = document.getElementById('statusDot');
    if (d.ready) {
      dot.className = 'status-dot ready';
      dot.title = 'F5-TTS ready — GPU accelerated';
    } else {
      dot.className = 'status-dot offline';
      dot.title = 'F5-TTS not installed — run setup.bat';
    }
  } catch (_) {}
}

// ── generate ──────────────────────────────────────────────
async function generate() {
  if (busy) return;

  if (!referenceFile) { showErr('Upload the audio you want to clean first.'); return; }
  const text = document.getElementById('textInput').value.trim();

  busy = true;
  hide('errBox');
  hide('audioCard');
  setStatus('psF5', '—', '');

  const btn = document.getElementById('genBtn');
  const lbl = document.getElementById('genLabel');
  btn.disabled = true;
  lbl.textContent = 'Cleaning…';
  setStatus('psF5', 'loading model… (first run: ~1-3 min)', 'running');

  const form = new FormData();
  form.append('audio', referenceFile);
  if (text) form.append('text', text);

  // Poll /api/status while the request is in flight so we can give a better
  // error message if the server crashes during a long F5-TTS inference.
  let _serverDied = false;
  const _heartbeat = setInterval(async () => {
    try { await fetch('/api/status', { signal: AbortSignal.timeout(3000) }); }
    catch (_) { _serverDied = true; clearInterval(_heartbeat); }
  }, 4000);

  try {
    let res;
    try {
      res = await fetch('/api/generate', { method: 'POST', body: form });
    } catch (_) {
      const hint = _serverDied
        ? 'Server crashed during processing — check app.log for details, then restart start.bat.'
        : 'Cannot reach server — restart start.bat and try again.';
      throw new Error(hint);
    }
    const d = await res.json();
    if (!res.ok || d.error) throw new Error(d.error || 'Request failed');

    setStatus('psF5', `✓ done (${d.elapsed}s)`, 'done');

    const blob = b64toBlob(d.audio, 'audio/wav');
    const url  = URL.createObjectURL(blob);

    const player = document.getElementById('player');
    player.src = url;
    player.load();

    const dl = document.getElementById('dlLink');
    dl.href = url;
    dl.download = `speech_${Date.now()}.wav`;

    document.getElementById('audioMeta').textContent = `Elapsed: ${d.elapsed}s`;
    show('audioCard');
    lbl.textContent = 'Clean Audio';

  } catch (e) {
    showErr(e.message);
    setStatus('psF5', '—', '');
    lbl.textContent = 'Clean Audio';
  } finally {
    clearInterval(_heartbeat);
    btn.disabled = false;
    busy = false;
  }
}

// ── helpers ───────────────────────────────────────────────
function b64toBlob(b64, type) {
  const bytes = atob(b64);
  const arr   = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  return new Blob([arr], { type });
}

function setStatus(id, text, cls) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = 'pstatus' + (cls ? ' ' + cls : '');
}

function showErr(msg) { const b = document.getElementById('errBox'); b.textContent = msg; b.style.display = ''; }
function show(id) { document.getElementById(id).style.display = ''; }
function hide(id) { document.getElementById(id).style.display = 'none'; }
