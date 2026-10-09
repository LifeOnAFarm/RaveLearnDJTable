"use strict";
const modeSelect = document.getElementById('mode-select');
const modeStatus = document.getElementById('mode-status');
const showModeStatus = text => { modeStatus.textContent = text; modeStatus.hidden = !text; };
let modeToken, modeSaving = false;
async function modePoll() {
  if (document.hidden && modeSelect.options.length) { setTimeout(modePoll, 2000); return; }
  try {
    const response = await fetch('/api/modes', {signal: AbortSignal.timeout(4000)});
    const data = await response.json(); if (!response.ok) throw Error(data.error);
    modeToken = data.csrf;
    if (!modeSelect.options.length) for (const [id, info] of Object.entries(data.modes)) modeSelect.append(new Option(info.name, id));
    if (!modeSaving) { modeSelect.value = data.selected; modeSelect.disabled = false; }
    const name = id => data.modes[id]?.name || id, runtime = data.runtime;
    // Text only while a theme is loading, or when something went wrong.
    showModeStatus(runtime?.error ? `Theme change failed: ${runtime.error}` :
      runtime && runtime.active !== data.selected ? `${name(data.selected)} mode is loading…` : '');
  } catch (error) { showModeStatus('Theme status unavailable: ' + error.message); }
  finally { setTimeout(modePoll, 1500); }
}
modeSelect.onchange = async () => {
  modeSaving = true; modeSelect.disabled = true;
  try {
    const response = await fetch('/api/mode', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-DJTable-CSRF': modeToken}, body: JSON.stringify({mode: modeSelect.value})});
    const result = await response.json(); if (!response.ok) throw Error(result.error);
    dispatchEvent(new Event('themechange'));
  } catch (error) { showModeStatus(error.message); }
  finally { modeSaving = false; modeSelect.disabled = false; }
};
modePoll();
