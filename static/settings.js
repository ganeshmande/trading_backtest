(() => {
  const input = document.getElementById('globalScLimit');
  const save = document.getElementById('saveScLimit');
  const status = document.getElementById('settingsStatus');
  if (!input || !save) return;

  const setStatus = (text, ok = true) => {
    if (!status) return;
    status.textContent = text;
    status.classList.toggle('error', !ok);
  };

  async function loadSettings() {
    try {
      const r = await fetch('/api/settings?_=' + Date.now(), {cache: 'no-store'});
      const d = await r.json();
      if (!r.ok || !d.success) throw new Error(d.error || 'Settings error');
      input.value = Number(d.settings?.sc_wick_body_limit_percent ?? 40).toString();
      setStatus('Applied');
      document.dispatchEvent(new CustomEvent('sc-setting-loaded', {detail: d.settings}));
    } catch (e) {
      setStatus('Load error', false);
    }
  }

  async function saveSettings() {
    const value = Number(input.value);
    if (!Number.isFinite(value) || value < 1) {
      setStatus('Use 1% or higher', false);
      return;
    }
    save.disabled = true;
    setStatus('Saving…');
    try {
      const r = await fetch('/api/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sc_wick_body_limit_percent: value})
      });
      const d = await r.json();
      if (!r.ok || !d.success) throw new Error(d.error || 'Unable to save');
      const saved = Number(d.settings.sc_wick_body_limit_percent);
      input.value = saved.toString();
      setStatus(`Active ${saved}%`);
      document.dispatchEvent(new CustomEvent('sc-setting-changed', {detail: d.settings}));
    } catch (e) {
      setStatus(e.message || 'Save error', false);
    } finally {
      save.disabled = false;
    }
  }

  save.addEventListener('click', saveSettings);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') saveSettings(); });
  loadSettings();
})();
