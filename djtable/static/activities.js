"use strict";
const activitySelect = document.getElementById('activity-select');
const activityStatus = document.getElementById('activity-status');
const showActivityStatus = text => { activityStatus.textContent = text; activityStatus.hidden = !text; };
const makerButtons = ['toggle', 'undo', 'clear'].map(action => document.getElementById('maker-' + action));
const quantize = document.getElementById('maker-quantize');
let activityToken, activitySaving = false;
async function makerAction(action, align) {
  try {
    const response = await fetch('/api/maker', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-DJTable-CSRF': activityToken}, body: JSON.stringify({action, quantize: align})});
    const result = await response.json(); if (!response.ok) throw Error(result.error);
  } catch (error) { showActivityStatus(error.message); }
}
makerButtons.forEach(b => { b.onclick = () => makerAction(b.id.slice(6)); });
quantize.onchange = () => makerAction(undefined, quantize.checked);
const LAYERS = {1: 'melody', 2: 'drums', 3: 'voice'};
function bluetoothText(bt) {
  if (!bt || bt.state === 'off' || bt.state === 'starting') return 'Starting Bluetooth…';
  if (bt.state === 'connected') return `Connected: ${bt.device}`;
  if (bt.state === 'error') return `Bluetooth unavailable: ${bt.error}. Returning to Learning…`;
  const s = bt.seconds_left ?? 0;
  return `Connect your phone to “${bt.name || 'DJTable'}” · ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
const VOICE = {prompt: 'Wait for the beep…', recording: 'Recording your voice now!', saving: 'Preparing your voice…'};
const LOOP = {counting: 'Count-in: wait for four clicks', capturing: 'Recording', preparing: 'Preparing your layer…'};
async function activityPoll() {
  if (document.hidden && activitySelect.options.length) { setTimeout(activityPoll, 2000); return; }
  try {
    const response = await fetch('/api/activities', {signal: AbortSignal.timeout(4000)});
    const data = await response.json(); if (!response.ok) throw Error(data.error);
    activityToken = data.csrf;
    if (!activitySelect.options.length) for (const [id, name] of Object.entries(data.activities)) activitySelect.append(new Option(name, id));
    if (!activitySaving) { activitySelect.value = data.selected; activitySelect.disabled = false; }
    const maker = data.selected === 'maker', phone = data.selected === 'bluetooth', runtime = data.runtime, recording = data.recording;
    // Music themes and song uploads only apply to Learning.
    document.getElementById('maker-panel').hidden = !maker;
    document.getElementById('mode-select').closest('section').hidden = maker || phone;
    document.getElementById('song-card').hidden = maker || phone;
    showActivityStatus(runtime && runtime.active !== data.selected ? `${data.activities[data.selected] || data.selected} mode is loading…`
      : phone ? bluetoothText(data.bluetooth) : '');
    const loop = runtime?.maker;
    if (maker && loop) {
      const busy = loop.state !== 'idle' || recording?.state in VOICE;
      document.getElementById('maker-status').textContent = VOICE[recording?.state] || (recording?.preview ? 'Voice saved: playing it once.' : '') ||
        `${loop.error || loop.clear_hint || (loop.state === 'capturing' ? 'Recording ' + LAYERS[loop.level] : LOOP[loop.state]) || (loop.playing ? 'Playing' : 'Paused')} · Layers: ${loop.layers.map(i => LAYERS[i]).join(', ') || 'none'}`;
      if (document.activeElement !== quantize) quantize.checked = data.maker_settings?.quantize !== false;
      makerButtons.forEach(b => { b.disabled = busy; });
    }
  } catch (error) { showActivityStatus('Status unavailable: ' + error.message); }
  finally { setTimeout(activityPoll, 700); }
}
activitySelect.onchange = async () => {
  activitySaving = true; activitySelect.disabled = true;
  try {
    const response = await fetch('/api/activity', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-DJTable-CSRF': activityToken}, body: JSON.stringify({activity: activitySelect.value})});
    const result = await response.json(); if (!response.ok) throw Error(result.error);
  } catch (error) { showActivityStatus(error.message); }
  finally { activitySaving = false; }
};
activityPoll();
