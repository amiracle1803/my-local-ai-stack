/* voice.js — VOICE page: speech studio */

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

async function loadVoiceConfig() {
  try {
    const data = await j('/api/voice/config');
    const select = $('voice-engine-select');
    if (!select) return;
    select.innerHTML = data.options.map((o) => `<option value="${esc(o.id)}" ${o.id === data.engine ? 'selected' : ''}>${esc(o.name)}</option>`).join('');
    $('voice-engine-status').textContent = 'local-only';
  } catch {
    if ($('voice-engine-status')) $('voice-engine-status').textContent = 'Voice Studio offline';
  }
}
loadVoiceConfig();

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



/* -- voice boot -- */
refreshSystems();
