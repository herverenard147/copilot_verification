/* Client API : fetch minces vers FastAPI (même backend que l'ancien front
   web/js/api.js, dont ce fichier reprend fidèlement les endpoints). Toute
   erreur remonte un message humain (le backend renvoie {error: "..."} en
   JSON, jamais un traceback). credentials:'include' pour porter les cookies
   sid (session anonyme) et auth_token (compte) même via le proxy Vite. */
async function _json(res) {
  let data = null;
  try { data = await res.json(); } catch (e) { /* corps non-JSON */ }
  if (!res.ok || (data && data.success === false)) {
    const err = new Error((data && data.error)
      || `Erreur ${res.status}. Le serveur n'a pas pu traiter la demande.`);
    err.detail = (data && data.detail) || '';
    err.suggestions = (data && data.suggestions) || [];
    err.engine = (data && data.engine) || null;
    err.status = res.status;
    throw err;
  }
  return data;
}

async function getJSON(url) {
  return _json(await fetch(url, { credentials: 'include' }));
}

async function postJSON(url, body) {
  return _json(await fetch(url, {
    method: 'POST', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  }));
}

async function putJSON(url, body) {
  return _json(await fetch(url, {
    method: 'PUT', credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  }));
}

async function del(url, body) {
  const opts = { method: 'DELETE', credentials: 'include' };
  if (body) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  return _json(await fetch(url, opts));
}

const API = {
  config: () => getJSON('/api/config'),

  async extract(file, country, paymentMode, docType) {
    const form = new FormData();
    form.append('file', file);
    form.append('country', country);
    form.append('payment_mode', paymentMode);
    form.append('doc_type', docType || 'ticket');
    return _json(await fetch('/api/extract', { method: 'POST', credentials: 'include', body: form }));
  },

  validate: (payload) => postJSON('/api/validate', payload),
  dashboard: () => getJSON('/api/dashboard'),
  receipt: (id, country) => getJSON('/api/receipt/' + encodeURIComponent(id)
    + (country ? '?country=' + encodeURIComponent(country) : '')),
  updateReceipt: (id, payload) => putJSON('/api/receipt/' + encodeURIComponent(id), payload),
  deleteReceipt: (id) => del('/api/receipt/' + encodeURIComponent(id)),
  accounting: (period, paymentMode, country) =>
    getJSON('/api/accounting?' + new URLSearchParams({ period, payment_mode: paymentMode, country })),
  search: (question) => postJSON('/api/search', { question }),
  technical: () => getJSON('/api/technical'),

  keyStatus: () => getJSON('/api/settings/status'),
  setKey: (provider, key) => postJSON('/api/settings/apikey', { provider, key }),
  clearKey: (provider) => del('/api/settings/apikey?provider=' + encodeURIComponent(provider)),
  testKey: (provider) => postJSON('/api/settings/test', { provider }),
  models: () => getJSON('/api/settings/models'),

  session: () => getJSON('/api/session'),
  clearSession: () => del('/api/session'),
  setDemo: (enabled) => postJSON('/api/settings/demo', { enabled }),

  // --- Comptes (chantier auth/RGPD) ---
  register: (email, password) => postJSON('/api/auth/register', { email, password }),
  login: (email, password) => postJSON('/api/auth/login', { email, password }),
  logout: () => postJSON('/api/auth/logout'),
  me: () => getJSON('/api/auth/me'),
  getConsent: (consentType = 'training_data') =>
    getJSON('/api/auth/consent?consent_type=' + encodeURIComponent(consentType)),
  setConsent: (granted, consentType = 'training_data') =>
    postJSON('/api/auth/consent', { consent_type: consentType, granted }),
  exportData: () => getJSON('/api/auth/export'),
  deleteAccount: (password) => del('/api/auth/account', { password }),
};

export default API;
