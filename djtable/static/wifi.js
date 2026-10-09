"use strict";
const el = id => document.getElementById(id);
let csrf;
function result(text) { el('result').textContent = text; el('result').hidden = !text; }
async function refresh() {
  try {
    const response = await fetch('/api/wifi'); const data = await response.json(); if (!response.ok) throw Error(data.error);
    const mode = data.mode === 'hotspot' ? 'Hotspot' : data.mode === 'wifi' ? 'Connected' : 'Offline';
    el('network-status').textContent = `${mode}${data.address ? ' · ' + data.address : ''}${data.busy ? ' · connecting…' : ''}`;
    el('network-status').className = data.mode === 'offline' ? 'badge off' : 'badge';
    if (data.error) result(data.error);
    el('connect').disabled = !!data.busy || !csrf;
  } catch { el('network-status').textContent = 'Unavailable'; el('network-status').className = 'badge off'; }
}
el('connect').disabled = true;
fetch('/api/library').then(r => r.json()).then(d => { csrf = d.csrf; refresh(); });
el('wifi-form').onsubmit = async event => {
  event.preventDefault(); el('connect').disabled = true;
  try {
    const response = await fetch('/api/wifi', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-DJTable-CSRF': csrf}, body: JSON.stringify({ssid: el('ssid').value, password: el('password').value})});
    const data = await response.json(); if (!response.ok) throw Error(data.error);
    el('password').value = ''; result('Connecting… Join the same Wi-Fi on your phone, then reopen this page.');
  } catch (e) { result(e.message); el('connect').disabled = false; }
};
setInterval(refresh, 5000);
