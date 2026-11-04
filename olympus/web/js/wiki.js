/* wiki.js — WIKI page: knowledge corpus browser */

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
    ? `<div class="wiki-dir" data-dir="${esc(wikiFolder ? wikiFolder + '/' + it.name : it.name)}"><span class="wiki-ic">📁</span><b>${esc(it.name)}</b><span class="wiki-kind">folder</span></div>`
    : `<div class="wiki-note" data-note="${esc(wikiFolder ? wikiFolder + '/' + it.name : it.name)}"><span class="wiki-ic">📄</span><b>${esc(it.name)}</b><span class="wiki-kind">md</span></div>`
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


/* -- wiki boot -------------------------------------------------------------- */
j('/api/system')
  .then((s) => {
    const wr = (s.paths && s.paths.wiki_root) || '';
    const note = new URLSearchParams(location.search).get('note');
    const finish = () => { if (note) openWikiNote(note); };
    if (!wr) { loadWiki('').then(finish); return; }
    return j('/api/brain/notes?folder=')
      .then((root) => loadWiki(root.some((i) => i.type === 'dir' && i.name === wr) ? wr : '').then(finish))
      .catch(() => loadWiki('').then(finish));
  })
  .catch(() => loadWiki(''));
