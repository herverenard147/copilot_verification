/* Client API : fetch minces vers FastAPI. Toute erreur remonte un message
   humain (le backend renvoie {error: "..."} en JSON, jamais un traceback). */
const API = {
  async _json(res) {
    let data = null;
    try { data = await res.json(); } catch (e) { /* corps non-JSON */ }
    if (!res.ok) {
      const msg = (data && data.error) ? data.error
        : `Erreur ${res.status}. Le serveur n'a pas pu traiter la demande.`;
      throw new Error(msg);
    }
    if (data && data.error) throw new Error(data.error);
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
};
