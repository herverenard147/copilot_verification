/* Client API : fetch minces vers FastAPI. Toute erreur remonte un message
   humain (le backend renvoie {error: "..."} en JSON, jamais un traceback). */
const API = {
  async _json(res) {
    let data = null;
    try { data = await res.json(); } catch (e) { /* corps non-JSON */ }
    // erreur si statut HTTP non-OK OU si le corps porte success:false
    if (!res.ok || (data && data.success === false)) {
      const err = new Error((data && data.error)
        || `Erreur ${res.status}. Le serveur n'a pas pu traiter la demande.`);
      err.detail = (data && data.detail) || '';
      err.suggestions = (data && data.suggestions) || [];
      err.engine = (data && data.engine) || null;
      throw err;
    }
    return data;
  },

  async config() {
    return this._json(await fetch('/api/config'));
  },

  async extract(file, country, paymentMode) {
    const form = new FormData();
    form.append('file', file);
    form.append('country', country);
    form.append('payment_mode', paymentMode);
    return this._json(await fetch('/api/extract', { method: 'POST', body: form }));
  },

  async validate(payload) {
    return this._json(await fetch('/api/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }));
  },

  async dashboard() {
    return this._json(await fetch('/api/dashboard'));
  },

  async accounting(period, paymentMode, country) {
    const q = new URLSearchParams({ period, payment_mode: paymentMode, country });
    return this._json(await fetch('/api/accounting?' + q.toString()));
  },

  async search(question) {
    return this._json(await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    }));
  },

  async technical() {
    return this._json(await fetch('/api/technical'));
  },

  // --- Réglages : clés API (la valeur n'est jamais renvoyée par le serveur) ---
  async keyStatus() {
    return this._json(await fetch('/api/settings/status'));
  },

  async setKey(provider, key) {
    return this._json(await fetch('/api/settings/apikey', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, key }),
    }));
  },

  async clearKey(provider) {
    return this._json(await fetch('/api/settings/apikey?provider=' + encodeURIComponent(provider),
      { method: 'DELETE' }));
  },

  async testKey(provider) {
    return this._json(await fetch('/api/settings/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
    }));
  },

  async models() {
    return this._json(await fetch('/api/settings/models'));
  },

  // --- Session utilisateur (cloisonnement des données) ---
  async session() {
    return this._json(await fetch('/api/session'));
  },

  async clearSession() {
    return this._json(await fetch('/api/session', { method: 'DELETE' }));
  },

  async setDemo(enabled) {
    return this._json(await fetch('/api/settings/demo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    }));
  },
};
