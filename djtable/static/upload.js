"use strict";
const el = id => document.getElementById(id);
let library;
async function refresh() {
  const response = await fetch('/api/library'); library = await response.json(); if (!response.ok) throw Error(library.error);
  el('song-count').textContent = `${library.songs.length} of 12 songs added.`;
}
function message(text, error = false) { const m = el('song-message'); m.textContent = text; m.hidden = !text; m.className = error ? 'status error' : 'status'; }
el('song-file').onchange = () => { const f = el('song-file').files[0]; if (f) el('song-title').value = f.name.replace(/\.wav$/i, ''); };
el('song-upload').onsubmit = async event => {
  event.preventDefault(); const file = el('song-file').files[0]; if (!file || !library) return;
  if (file.size > 12 * 1048576) { message('Choose a file smaller than 12 MB.', true); return; }
  el('song-submit').disabled = true; el('song-progress').hidden = false; message('Uploading…');
  try {
    await new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open('POST', '/api/upload?' + new URLSearchParams({mode: library.mode, slot: 'song', title: el('song-title').value}));
      x.setRequestHeader('X-DJTable-CSRF', library.csrf); x.timeout = 120000;
      x.upload.onprogress = e => { if (e.lengthComputable) el('song-progress').value = e.loaded / e.total * 100; };
      x.onerror = () => reject(Error('Connection lost. Check Admin before trying again.'));
      x.ontimeout = () => reject(Error('Upload timed out. Check Admin before trying again.'));
      x.onload = () => { try { const result = JSON.parse(x.responseText); x.status === 200 ? resolve() : reject(Error(result.error)); } catch { reject(Error('Could not read the response.')); } };
      x.send(file);
    });
    el('song-upload').reset(); await refresh(); message('Added! The song button can now pick it.');
  } catch (e) { message(e.message, true); }
  finally { el('song-submit').disabled = false; el('song-progress').hidden = true; el('song-progress').value = 0; }
};
// Songs belong to the selected theme; follow theme changes without reloading the page.
addEventListener('themechange', () => { message(''); refresh().catch(e => message(e.message, true)); });
refresh().catch(e => { message(e.message, true); el('song-submit').disabled = true; });
