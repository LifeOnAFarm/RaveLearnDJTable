'use strict';
const $ = id => document.getElementById(id);
let library, csrf, busy = false;

function notice(text, error = false) { const n = $('notice'); n.textContent = text; n.hidden = !text; n.className = error ? 'notice error' : 'notice'; }
function button(text, onclick) { const b = document.createElement('button'); b.type = 'button'; b.textContent = text; b.onclick = onclick; b.disabled = busy; return b; }
async function post(url, body) {
  const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-DJTable-CSRF': csrf}, body: JSON.stringify(body)});
  const result = await response.json(); if (!response.ok) throw Error(result.error); return result;
}

// ---- Songs: view and edit any theme's playlist without switching the toy ----
async function loadSongs() {
  const response = await fetch('/api/library?mode=' + encodeURIComponent($('song-theme').value));
  const data = await response.json(); if (!response.ok) throw Error(data.error);
  library = data; csrf = data.csrf; renderSongs();
}
function renderSongs() {
  const list = $('songs'); list.replaceChildren();
  list.closest('.card').querySelector('h2').textContent = `Songs (${library.songs.length} / 12)`;
  $('empty').hidden = library.songs.length > 0;
  library.songs.forEach((song, index) => {
    const item = document.createElement('li'); item.className = 'song';
    const title = document.createElement('div'); title.className = 'song-title'; title.textContent = `${index + 1}. ${song.title}`;
    const audio = document.createElement('audio'); audio.controls = true; audio.preload = 'none';
    audio.src = `/audio/${encodeURIComponent(song.file)}?mode=${library.mode}`; audio.setAttribute('aria-label', 'Preview ' + song.title);
    const actions = document.createElement('div'); actions.className = 'actions';
    const move = step => { const order = library.songs.map(s => s.file); [order[index], order[index + step]] = [order[index + step], order[index]]; change('order', order); };
    if (index) actions.append(button('Move up', () => move(-1)));
    if (index < library.songs.length - 1) actions.append(button('Move down', () => move(1)));
    actions.append(button('Remove', () => { if (confirm(`Remove “${song.title}”?`)) change('remove', song.file); }));
    item.append(title, audio, actions); list.append(item);
  });
  const used = library.songs.reduce((total, s) => total + s.decoded_bytes, 0) / 1048576, limit = library.max_decoded_bytes / 1048576;
  $('memory').textContent = `${used.toFixed(1)} / ${limit} MiB`; $('memory-meter').max = limit; $('memory-meter').value = used;
}
async function change(action, value) {
  if (busy) return; busy = true; renderSongs();
  try { await post('/api/change?' + new URLSearchParams({mode: library.mode}), {action, value}); await loadSongs(); notice(''); }
  catch (error) { notice(error.message, true); }
  finally { busy = false; renderSongs(); }
}
$('song-theme').onchange = () => loadSongs().catch(error => notice(error.message, true));
fetch('/api/modes').then(r => r.json()).then(data => {
  for (const [id, info] of Object.entries(data.modes)) $('song-theme').append(new Option(info.name, id));
  $('song-theme').value = data.selected; return loadSongs();
}).catch(error => notice('Cannot reach the table: ' + error.message, true));

// ---- Hardware test ----
const BUTTON_NAMES = {song: 'Song', record: 'Record', mode: 'Mode'};
const buttonName = name => BUTTON_NAMES[name] || name[0].toUpperCase() + name.slice(1);
const THEME_TONES = {house: ['House chords', 'Chord stabs', 'Deep bass'], punk: ['Clean guitar', 'Crunch guitar', 'Power chord'], baby_raver: ['Quacky duck', 'Meowing cat', 'Bouncy robot']};
function sliderLabels(data) {
  const activity = data.activity || {}, maker = activity.active === 'maker';
  if (activity.active === 'bluetooth') {
    const sets = ['punk', 'teenage_disco', 'house'], set = sets[(data.sliders?.level?.position || 2) - 1];
    return {tone: THEME_TONES[set] || ['Electric piano', 'Meows', 'Synth'], level: ['Punk', 'Teenage Disco', 'House'], volume: ['Low', 'Medium', 'High']};
  }
  let tone = THEME_TONES[data.mode?.active] || ['Electric piano', 'Meows', 'Synth'];
  if (maker && activity.level === 1) tone = ['Piano', 'Synth', 'Bass'];
  if (maker && activity.level === 2) { const kits = activity.maker?.drum_kits; tone = kits ? [kits.piano, kits.high, kits.synth] : ['Kit 1', 'Kit 2', 'Kit 3']; }
  if (maker && activity.level === 3) tone = ['Normal voice', 'Robot voice', 'Monster voice'];
  return {tone, level: maker ? ['Melody', 'Drums', 'Voice'] : ['English', 'Irish', 'Notes'], volume: ['Low', 'Medium', 'High']};
}
async function selectSlider(name, position) {
  try { await post('/api/controls', {name, position}); } catch (error) { notice(error.message, true); }
}
function renderSliders(data) {
  const labels = sliderLabels(data); $('sliders').replaceChildren();
  for (const [name, options] of Object.entries(labels)) {
    const state = data.sliders?.[name];
    const row = document.createElement('div'); row.className = 'hw-row';
    const title = document.createElement('span'); title.textContent = name[0].toUpperCase() + name.slice(1);
    const note = document.createElement('small');
    const contacts = state?.grounded || [];
    note.textContent = !state ? '' : state.source === 'web' ? 'set here' : state.valid ? 'slider'
      : contacts.length ? `contacts ${contacts.join(' + ')}` : 'no contact';
    if (name === 'volume' && data.online) note.textContent += ` · ${Math.round(data.master_volume * 100)}%`;
    title.append(note);
    const seg = document.createElement('div'); seg.className = 'seg';
    options.forEach((label, i) => {
      const active = state?.position === i + 1;
      const b = button(label, () => selectSlider(name, i + 1)); b.className = active ? 'active' : '';
      b.setAttribute('aria-pressed', String(active)); b.disabled = !data.online || !csrf; seg.append(b);
    });
    row.append(title, seg); $('sliders').append(row);
  }
}
function renderStatus(data) {
  $('hardware').classList.toggle('stale', !data.online);
  $('live').textContent = data.online ? 'Live' : 'Offline'; $('live').className = data.online ? 'badge' : 'badge off';
  renderSliders(data);
  const buttons = data.buttons;
  $('buttons').textContent = !data.online || !buttons ? '–' : buttons.held.length ? 'Holding ' + buttons.held.map(buttonName).join(', ')
    : buttons.last ? `Last: ${buttonName(buttons.last.name)} · ${Math.round(buttons.last.seconds_ago)} s ago` : 'Press any button';
  renderPins(data);
  const p = data.platter, k = data.keyboard || {};
  $('platter').textContent = !data.online ? '–' : !p ? 'Not enabled' : p.error ? p.error :
    `${Math.round(p.angle * 360 / 4096)}° · bend ${k.bend_semitones ?? 0} · speed ${k.playback_speed ?? 1}×${p.magnet === false ? ' · no magnet' : ''}`;
  const rec = data.recording;
  const states = {idle: 'Ready', prompt: 'Prompt playing', recording: 'Recording…', saving: 'Processing…', playing: 'Playing remix'};
  $('recorder').textContent = !data.online || !rec ? '–' : !rec.capture_enabled ? 'Not enabled'
    : `${states[rec.state] || rec.state}${rec.error ? ' · ' + rec.error : ''}`;
}
function pinLabel(name) {
  const [control, position] = name.split('_');
  return buttonName(control) + (position ? ' ' + position : '');
}
function renderPins(data) {
  const rows = data.online && data.buttons?.pins || [];
  $('pins').replaceChildren(...rows.map(([name, gpio, header, grounded, since]) => {
    const row = document.createElement('tr');
    const state = grounded ? 'Grounded' : since !== null && since < 30 ? `Grounded ${Math.round(since)} s ago` : 'Open';
    row.className = grounded ? 'on' : since !== null && since < 30 ? 'recent' : '';
    for (const text of [pinLabel(name), gpio, header ?? '–', state]) {
      const cell = document.createElement('td'); cell.textContent = text; row.append(cell);
    }
    return row;
  }));
}
async function pollStatus() {
  if (document.hidden && $('sliders').childElementCount) { setTimeout(pollStatus, 2000); return; }
  try { const response = await fetch('/api/status', {signal: AbortSignal.timeout(4000)}); renderStatus(await response.json()); }
  catch { renderStatus({online: false}); }
  finally { setTimeout(pollStatus, 1000); }
}
pollStatus();
