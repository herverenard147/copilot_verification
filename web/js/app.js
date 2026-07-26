/* ==========================================================================
   Copilote de reçus — logique front (vanilla JS)
   Fidèle au design Stitch (voir DESIGN.md). Appelle l'API FastAPI (api.js).
   Non négociables : chips 3 états (➖ neutre), table éditable avec recalcul
   live via /api/validate, bandeau CI expérimental + moteur affiché, jamais
   de pourcentage de confiance, erreurs humaines.
   ========================================================================== */

const state = {
  config: null,
  country: 'CI',
  payment: 'cash',
  docType: 'ticket',   // 'ticket' (défaut, inchangé) ou 'facture' (post-traitement en-têtes)
  file: null,          // File courant (pour l'aperçu image)
  result: null,        // dernier /api/extract
  askHistory: [],
  demoMode: false,     // corpus CORD chargé dans la session (bandeau permanent)
  sessionEmpty: true,  // aucune dépense utilisateur pour l'instant
};

/* ---------- helpers ---------- */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function money(v) {
  if (v == null || (typeof v === 'number' && isNaN(v))) return '—';
  const n = Number(v);
  const decimals = Number.isInteger(n) ? 0 : 2;
  return n.toLocaleString('fr-FR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

// Libellé d'un document selon son type (affichage seul) :
//  facture + numéro trouvé -> "Facture n°{num}" ; facture sans numéro ->
//  "Facture #{id}" ; ticket (défaut) -> "Reçu #{id}" (inchangé). Renvoie du
//  HTML déjà échappé.
function receiptLabel(r) {
  const id = r.receipt_id;
  if (r && r.doc_type === 'facture') {
    return r.invoice_number ? `Facture n°${esc(r.invoice_number)}` : `Facture #${id}`;
  }
  return `Reçu #${id}`;
}

// chip 3 états : true=✅ / false=❌ / null=➖ (gris NEUTRE, jamais alarmant)
// Le title explicite chaque état — notamment ➖, souvent mal compris.
function chip(label, value) {
  const map = {
    true: ['chip--ok', '✅', 'Contrôle conforme'],
    false: ['chip--bad', '❌', 'Anomalie détectée sur ce contrôle'],
    null: ['chip--neutral', '➖', 'Non vérifiable : information absente sur ce reçu'],
  };
  const key = value === true ? 'true' : value === false ? 'false' : 'null';
  const [cls, icon, tip] = map[key];
  return `<span class="chip ${cls}" title="${esc(tip)}">${icon} ${esc(label)}</span>`;
}

// Formate un taux : 10.75 -> "10,75 %", 25 -> "25 %".
function pct(rate) {
  return rate.toLocaleString('fr-FR', { maximumFractionDigits: 2 }) + ' %';
}

// TÂCHE 1 — les 4 indicateurs de contrôle, chacun avec un titre clair, une
// explication chiffrée VISIBLE (pas un tooltip) et un verdict en couleur.
function control(title, value, msgs) {
  const key = value === true ? 'ok' : value === false ? 'bad' : 'none';
  const meta = { ok: ['chip--ok', '✅'], bad: ['chip--bad', '❌'], none: ['chip--neutral', '➖'] }[key];
  const explainCls = key === 'bad' ? 'control-explain control-explain--bad' : 'control-explain';
  return `<div class="control">
    <span class="chip ${meta[0]}">${meta[1]} ${esc(title)}</span>
    <div class="${explainCls}">${esc(msgs[key])}</div></div>`;
}

function controlsHtml(audit, balanced, receipt, journal, country) {
  const a = audit || {};
  const sub = receipt.subtotal, tax = receipt.tax, total = receipt.total;
  const itemsSum = (receipt.items || []).reduce((s, it) => s + (Number(it.line_price) || 0), 0);
  const td = (journal || []).reduce((s, l) => s + (l.debit || 0), 0);
  const tc = (journal || []).reduce((s, l) => s + (l.credit || 0), 0);
  const isID = country !== 'CI';
  const ctyLabel = isID ? 'indonésien' : 'ivoirien';
  const expRate = isID ? 11 : 18;
  const rate = (tax && sub) ? (tax / sub * 100) : null;
  const attendu = (sub || 0) + (tax || 0), diff = (total || 0) - attendu;

  return control('Somme des articles', a.line_sum_ok, {
      ok: `La somme des articles (${money(itemsSum)}) correspond au sous-total (${money(sub)})`,
      bad: `⚠️ La somme des articles (${money(itemsSum)}) ne correspond pas au sous-total annoncé (${money(sub)}) — écart de ${money(Math.abs(itemsSum - (sub || 0)))}. Vérifiez qu'aucun article ne manque.`,
      none: `Le sous-total n'est pas indiqué sur ce reçu — vérification impossible`,
    })
    + control('Calcul du total', a.total_ok, {
      ok: `Sous-total (${money(sub)}) + taxe (${money(tax || 0)}) = total (${money(total)}) ✓`,
      bad: `⚠️ Sous-total (${money(sub)}) + taxe (${money(tax || 0)}) = ${money(attendu)}, mais le total indiqué est ${money(total)}. ${diff >= 0 ? 'Il manque ' + money(diff) : 'Il y a ' + money(-diff) + ' de trop'} — peut-être un frais de service non extrait.`,
      none: `Le sous-total ou le total n'est pas indiqué — vérification impossible`,
    })
    + control('Taux de taxe', a.tax_ok, {
      ok: `Taxe de ${rate != null ? pct(rate) : '—'} — cohérent avec le taux ${ctyLabel} (≈${expRate} %)`,
      bad: `⚠️ Taxe de ${rate != null ? pct(rate) : '?'} — inhabituel pour le pays sélectionné (attendu ≈${expRate} %). Vérifiez le montant de la taxe.`,
      none: `Pas de taxe sur ce reçu — non vérifiable`,
    })
    + control('Équilibre comptable', balanced, {
      ok: `Total des débits (${money(td)}) = total des crédits (${money(tc)}) ✓`,
      bad: `⚠️ L'écriture est déséquilibrée — contactez un comptable`,
      none: `Écriture non générée — données insuffisantes`,
    });
}

// TÂCHE 3 — points précis à vérifier (encart en tête de détail / d'analyse).
function reviewPoints(audit, balanced, receipt) {
  const a = audit || {};
  const sub = receipt.subtotal, tax = receipt.tax, total = receipt.total;
  const itemsSum = (receipt.items || []).reduce((s, it) => s + (Number(it.line_price) || 0), 0);
  const pts = [];
  if (a.line_sum_ok === false) pts.push(`Somme des articles : écart de ${money(Math.abs(itemsSum - (sub || 0)))} entre les articles et le sous-total`);
  if (a.total_ok === false) { const d = (total || 0) - ((sub || 0) + (tax || 0)); pts.push(`Calcul du total : il ${d >= 0 ? 'manque ' + money(d) : 'y a ' + money(-d) + ' de trop'} entre sous-total + taxe et le total affiché`); }
  if (a.tax_ok === false) pts.push(`Taux de taxe : le taux paraît inhabituel pour le pays sélectionné`);
  if (balanced === false) pts.push(`Équilibre comptable : l'écriture est déséquilibrée`);
  return pts;
}

function reviewBanner(pts, editable) {
  if (!pts.length) return '';
  const close = editable
    ? "→ Corrigez les montants ci-dessus, les contrôles et l'écriture se recalculent automatiquement."
    : "→ Vérifiez ces montants sur le reçu d'origine.";
  return `<div class="banner">Ce reçu a ${pts.length} point${pts.length > 1 ? 's' : ''} à vérifier :
    <ul style="margin:var(--xs) 0 var(--xs) var(--lg)">${pts.map(p => `<li>${esc(p)}</li>`).join('')}</ul>${close}</div>`;
}

// TÂCHE 2 — état d'un reçu, progressif et jamais alarmiste.
function receiptStatus(r) {
  const flags = [r.line_sum_ok, r.total_ok, r.tax_ok];
  let fails = flags.filter(f => f === false).length;
  if (fails === 0 && r.anomaly) fails = 1;   // ex. contrôle magnitude non exposé -> 1 point
  if (fails > 0) return {
    status: 'review', rowClass: 'receipt-review',
    badge: `<span class="badge badge--review">⚠️ ${fails} point${fails > 1 ? 's' : ''} à vérifier</span>`,
  };
  if (flags.some(f => f === true)) return {
    status: 'conforme', rowClass: '', badge: `<span class="badge badge--verified">✓ Vérifié</span>`,
  };
  return { status: 'nodata', rowClass: '', badge: `<span class="badge badge--nodata">— Données insuffisantes</span>` };
}

function engineBadge(engine) {
  if (engine === 'llm_fallback')
    return `<span class="badge badge--fallback" title="Un LLM de vision a lu l'image parce que Donut n'y arrivait pas (ex. reçu hors de son domaine).">🛰️ Moteur : LLM vision (fallback)</span>`;
  if (engine === 'fallback_indisponible')
    return `<span class="badge badge--fallback" title="Aucun modèle vision accessible avec la clé Groq configurée.">⚠️ Fallback vision indisponible — modèle non accessible avec cette clé</span>`;
  return `<span class="badge badge--donut" title="Donut : modèle spécialisé reçus, entraîné sur CORD (tickets indonésiens).">🍩 Moteur : Donut</span>`;
}

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2600);
}

/* ---------- init ---------- */
async function init() {
  try {
    state.config = await API.config();
  } catch (e) {
    state.config = { countries: { CI: 0.18, ID: 0.11 }, payment_modes: ['cash', 'bank', 'credit'],
                     chart_of_accounts: {}, groq_configured: false, disclaimer: '' };
  }
  populateSelects();
  wireNav();
  wireSettings();
  $('#demo-exit').onclick = exitDemo;
  await refreshSession();
  renderAnalyzeEmpty();
}

// Met à jour l'état de session (mode démo + vacuité) et le bandeau permanent.
async function refreshSession() {
  try {
    const s = await API.session();
    state.demoMode = !!s.demo_mode;
    state.sessionEmpty = !!s.empty;
    state.nReceipts = s.n_receipts || 0;
  } catch (e) {
    state.demoMode = false;
    state.sessionEmpty = true;
    state.nReceipts = 0;
  }
  $('#demo-banner').classList.toggle('hidden', !state.demoMode);
}

async function exitDemo() {
  try { await API.setDemo(false); } catch (e) { /* ignore */ }
  await refreshSession();
  toast('Mode démonstration désactivé');
  // rafraîchit l'onglet visible
  const active = $('#nav button.active');
  if (active) switchTab(active.dataset.tab, active);
}

function populateSelects() {
  const countryLabels = { CI: "Côte d'Ivoire — TVA 18%", ID: 'Indonésie — TVA 11%' };
  const paymentLabels = { cash: 'Espèces (caisse)', bank: 'Virement bancaire', credit: 'À crédit (fournisseur)' };
  const c = $('#sel-country');
  c.innerHTML = Object.keys(state.config.countries)
    .map(k => `<option value="${k}">${esc(countryLabels[k] || k)}</option>`).join('');
  c.value = state.country;
  c.onchange = () => { state.country = c.value; if (state.result) recompute(); };

  const p = $('#sel-payment');
  p.innerHTML = state.config.payment_modes
    .map(k => `<option value="${k}">${esc(paymentLabels[k] || k)}</option>`).join('');
  p.value = state.payment;
  p.onchange = () => { state.payment = p.value; if (state.result) recompute(); };

  // Type de document : n'agit qu'au moment de l'extraction (post-traitement
  // en-têtes en mode facture). Changer le sélecteur ne re-filtre pas un résultat
  // déjà affiché — il faut relancer une extraction pour un effet.
  const dt = $('#sel-doctype');
  if (dt) { dt.value = state.docType; dt.onchange = () => { state.docType = dt.value; }; }
}

function wireNav() {
  $$('#nav button').forEach(btn => {
    btn.onclick = () => switchTab(btn.dataset.tab, btn);
  });
}

const loadedOnce = {};
function switchTab(tab, btn) {
  $$('#nav button').forEach(b => b.classList.toggle('active', b === btn));
  $$('.tab').forEach(s => s.classList.add('hidden'));
  $('#tab-' + tab).classList.remove('hidden');
  // chargement paresseux par onglet (Dashboard/Compta/Technique ne touchent PAS Donut)
  if (tab === 'dashboard') loadDashboard();
  if (tab === 'accounting') loadAccounting();
  if (tab === 'technical' && !loadedOnce.technical) { loadedOnce.technical = true; loadTechnical(); }
  if (tab === 'ask' && !loadedOnce.ask) { loadedOnce.ask = true; setupAsk(); }
}

/* ==========================================================================
   ONGLET 1 — ANALYSER
   ========================================================================== */
function renderAnalyzeEmpty() {
  state.result = null; state.file = null;
  $('#analyze-body').innerHTML = `
    <div class="dropzone" id="dropzone">
      <div style="font-size:40px">📤</div>
      <p class="headline-sm">Déposer une photo de reçu</p>
      <p class="muted">Cliquez ou glissez une image (JPG, PNG). L'analyse tourne en local.</p>
      <input type="file" id="file-input" accept="image/*" class="hidden" />
    </div>
    <p class="muted body-sm" style="margin-top:var(--md)">
      💡 Astuce : une photo nette, à plat et bien éclairée améliore nettement l'extraction.
    </p>`;
  const dz = $('#dropzone'), fi = $('#file-input');
  dz.onclick = () => fi.click();
  fi.onchange = () => { if (fi.files[0]) handleFile(fi.files[0]); };
  dz.ondragover = e => { e.preventDefault(); dz.classList.add('drag'); };
  dz.ondragleave = () => dz.classList.remove('drag');
  dz.ondrop = e => { e.preventDefault(); dz.classList.remove('drag'); if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]); };
}

function renderLoading() {
  $('#analyze-body').innerHTML = `
    <div class="card"><div class="loader">
      <div class="spinner"></div>
      <p class="headline-sm">Analyse du reçu en cours…</p>
      <p class="muted">L'inférence tourne sur le processeur : comptez <b>30 à 60 secondes</b>. Ne fermez pas la page.</p>
      <ul class="steps" id="steps">
        <li data-step="0">📥 Préparation et redressement de l'image</li>
        <li data-step="1">🧠 Chargement du modèle Donut (au 1er lancement)</li>
        <li data-step="2">🔍 Lecture du reçu</li>
        <li data-step="3">🧮 Vérification des règles comptables</li>
      </ul>
    </div></div>`;
  // animation visuelle des étapes pendant la requête unique (pas de vrai
  // sous-progrès disponible : on informe sans mentir sur un pourcentage).
  let i = 0;
  const steps = $$('#steps li');
  steps[0].classList.add('active');
  return setInterval(() => {
    if (i < steps.length - 1) { steps[i].classList.remove('active'); steps[i].classList.add('done'); i++; steps[i].classList.add('active'); }
  }, 4000);
}

async function handleFile(file) {
  state.file = file;
  const timer = renderLoading();
  try {
    const data = await API.extract(file, state.country, state.payment, state.docType);
    clearInterval(timer);
    state.result = data;
    renderResult(data);
  } catch (e) {
    clearInterval(timer);
    renderError(e);
  }
}

// consomme le format d'erreur structuré de l'API :
// { error, detail, suggestions } (voir fail() dans api.py)
function renderError(err) {
  const title = (err && err.message) || 'Impossible de lire ce reçu';
  const detail = (err && err.detail) || '';
  const suggestions = (err && err.suggestions && err.suggestions.length)
    ? err.suggestions
    : ['Réessayer avec une photo plus nette', 'Saisir les données manuellement'];

  $('#analyze-body').innerHTML = `
    <div class="card"><div class="section-body">
      <div class="error-box"><b>${esc(title)}</b>${detail ? `<br>${esc(detail)}` : ''}</div>
      <div style="margin-top:var(--md)">
        <div class="label-caps">Suggestions</div>
        <ul class="muted body-sm">${suggestions.map(s => `<li>${esc(s)}</li>`).join('')}</ul>
      </div>
      <div class="btn-row" style="margin-top:var(--md)">
        <button class="btn btn--primary" id="err-retry">📷 Essayer une autre image</button>
        <button class="btn" id="err-manual">✏️ Saisir les données manuellement</button>
      </div>
    </div></div>`;
  $('#err-retry').onclick = renderAnalyzeEmpty;
  $('#err-manual').onclick = () => {
    state.result = { engine: 'donut', receipt: { items: [], subtotal: null, tax: null, total: null, merchant: null },
                     audit: {}, journal: null, balanced: null, vat: {}, raw_json: {}, fallback_note: null };
    state.file = null;
    renderResult(state.result);
  };
}

function renderResult(data) {
  const r = data.receipt;
  const imgHtml = state.file
    ? `<img class="receipt-img" src="${URL.createObjectURL(state.file)}" alt="Reçu déposé" />`
    : `<div class="card"><div class="section-body muted">Saisie manuelle — aucune image associée.</div></div>`;

  const banner = state.country === 'CI'
    ? `<div class="banner">⚠️ <b>Mode expérimental</b> : l'extraction est entraînée sur des reçus indonésiens (CORD),
       les résultats sur reçus ivoiriens sont dégradés. Les règles comptables SYSCOHADA, elles, restent fonctionnelles.</div>`
    : '';

  const accounts = state.config.chart_of_accounts || {};
  const proposedAccount = (data.journal && data.journal[0]) ? data.journal[0].account : '638';

  $('#analyze-body').innerHTML = `
    ${banner}
    <div style="margin-bottom:var(--md)">${engineBadge(data.engine)}
      ${data.fallback_note ? `<span class="muted body-sm" style="margin-left:var(--sm)">${esc(data.fallback_note)}</span>` : ''}
    </div>
    <p class="muted body-sm" style="margin-bottom:var(--md)">💡 Vous pouvez modifier chaque montant dans le tableau. Les contrôles et l'écriture comptable se mettent à jour en temps réel.</p>
    <div class="analyze-grid">
      <div>${imgHtml}</div>
      <div class="stack">
        <div class="card">
          <div class="section-head"><span class="label-caps">Articles extraits</span>
            <span id="verify-tag"></span></div>
          <table class="editable"><thead><tr>
            <th>Article</th><th class="num">Qté</th><th class="num">Prix unit.</th><th class="num">Total ligne</th>
          </tr></thead><tbody id="items-body"></tbody></table>
          <div class="section-body"><button class="btn" id="add-item">+ Ajouter une ligne</button></div>
        </div>

        <div class="totals">
          <div class="total-box"><div class="label-caps">Sous-total</div>
            <input class="amount tabular" id="in-subtotal" type="number" step="100" /></div>
          <div class="total-box total-box--tax"><div class="label-caps">Taxe</div>
            <input class="amount tabular" id="in-tax" type="number" step="100" /></div>
          <div class="total-box total-box--total"><div class="label-caps">Total</div>
            <input class="amount tabular" id="in-total" type="number" step="100" style="background:transparent;color:#fff;border-color:rgba(255,255,255,.3)" /></div>
        </div>

        <div class="card"><div class="section-head"><span class="label-caps">Contrôles</span></div>
          <div class="section-body" id="chips"></div></div>

        <div class="card">
          <div class="section-head"><span class="label-caps">Écriture comptable proposée</span></div>
          <div class="section-body">
            <label class="field">Compte de charge (réassignable)</label>
            <select id="sel-account">${Object.entries(accounts).map(([code, lbl]) =>
              `<option value="${code}">${code} — ${esc(lbl)}</option>`).join('')}</select>
          </div>
          <table><thead><tr><th>Compte</th><th>Libellé</th><th class="num">Débit</th><th class="num">Crédit</th></tr></thead>
            <tbody id="journal-body"></tbody></table>
          <div class="section-body" id="journal-footer"></div>
        </div>

        <details><summary>Voir le JSON brut extrait</summary>
          <pre>${esc(JSON.stringify(data.raw_json || {}, null, 2))}</pre></details>

        <button class="btn btn--primary" id="btn-validate">✅ Valider et enregistrer dans les dépenses</button>
      </div>
    </div>`;

  // remplir la table éditable
  renderItems(r.items || []);
  $('#in-subtotal').value = r.subtotal ?? '';
  $('#in-tax').value = r.tax ?? '';
  $('#in-total').value = r.total ?? '';
  $('#sel-account').value = proposedAccount;

  // premier rendu des chips / écriture depuis la réponse extract
  paintAudit(data.audit, data.journal, data.balanced, data.vat, r, state.country);
  updateVerifyTag(r);

  // câblage des recalculs live
  $('#add-item').onclick = () => { addItemRow(); recompute(); };
  ['in-subtotal', 'in-tax', 'in-total'].forEach(id => { $('#' + id).onchange = recompute; });
  $('#sel-account').onchange = recompute;
  $('#btn-validate').onclick = saveReceipt;
}

function renderItems(items) {
  const body = $('#items-body');
  body.innerHTML = '';
  if (!items.length) addItemRow();
  else items.forEach(it => addItemRow(it));
}

function addItemRow(it = { name: '', quantity: '', unit_price: '', line_price: '' }) {
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td contenteditable data-k="name">${esc(it.name ?? '')}</td>
    <td contenteditable data-k="quantity" class="num">${it.quantity ?? ''}</td>
    <td contenteditable data-k="unit_price" class="num">${it.unit_price ?? ''}</td>
    <td contenteditable data-k="line_price" class="num">${it.line_price ?? ''}</td>`;
  tr.querySelectorAll('[contenteditable]').forEach(td => {
    td.addEventListener('blur', recompute);   // recalcul quand l'utilisateur valide une cellule
  });
  $('#items-body').appendChild(tr);
}

function readReceiptFromDOM() {
  const items = $$('#items-body tr').map(tr => {
    const row = {};
    tr.querySelectorAll('[contenteditable]').forEach(td => {
      const k = td.dataset.k, v = td.textContent.trim();
      if (k === 'name') row[k] = v || null;
      else row[k] = v === '' ? null : Number(v.replace(/\s/g, '').replace(',', '.'));
    });
    return row;
  }).filter(r => r.name || r.line_price != null);
  const num = id => { const el = $('#' + id); if (!el || el.value === '') return null; return Number(el.value); };
  return {
    items,
    subtotal: num('in-subtotal'), tax: num('in-tax'), total: num('in-total'),
    account: $('#sel-account') ? $('#sel-account').value : null,
    merchant: state.result?.receipt?.merchant ?? null,
    country: state.country, payment_mode: state.payment,
    // conserve le type + le numéro trouvés à l'extraction (contexte du reçu)
    doc_type: state.result?.doc_type ?? state.docType,
    invoice_number: state.result?.invoice_number ?? null,
    persist: false,
  };
}

// recalcul LIVE : /api/validate persist=false → met à jour chips + écriture
async function recompute() {
  const payload = readReceiptFromDOM();
  try {
    const data = await API.validate(payload);
    paintAudit(data.audit, data.journal, data.balanced, data.vat, data.receipt, state.country);
    updateVerifyTag(data.receipt);
  } catch (e) {
    toast('Recalcul impossible : ' + e.message);
  }
}

function paintAudit(audit, journal, balanced, vat, receipt, country) {
  const pts = reviewPoints(audit, balanced, receipt);
  $('#chips').innerHTML = reviewBanner(pts, true)
    + controlsHtml(audit, balanced, receipt, journal, country);

  const jb = $('#journal-body'), jf = $('#journal-footer');
  if (!journal) {
    jb.innerHTML = `<tr><td colspan="4" class="muted">Impossible de proposer une écriture : total, sous-total et lignes sont tous vides.</td></tr>`;
    jf.innerHTML = '';
    return;
  }
  jb.innerHTML = journal.map(l => `<tr>
    <td style="color:var(--primary);font-weight:500">${esc(l.account)}</td>
    <td>${esc(l.label)}</td>
    <td class="num">${money(l.debit)}</td>
    <td class="num">${money(l.credit)}</td></tr>`).join('');
  const td = journal.reduce((s, l) => s + (l.debit || 0), 0);
  const tc = journal.reduce((s, l) => s + (l.credit || 0), 0);
  const vatNote = (vat && vat.recoverable === 0 && receipt.tax)
    ? `<div class="banner" style="margin-top:var(--sm)">TVA non récupérable — ${esc(vat.reason)}. Elle est réintégrée dans la charge.</div>`
    : '';
  jf.innerHTML = `<div class="tabular">Total débit : ${money(td)} · Total crédit : ${money(tc)} ·
    ${balanced ? '✅ équilibré' : '❌ déséquilibré'}</div>${vatNote}
    <p class="muted body-sm" style="margin-top:var(--sm)">Cette écriture est une proposition automatique basée sur la catégorie détectée pour chaque article. Elle doit être validée par un comptable avant tout usage officiel. Vous pouvez modifier les montants ci-dessus : les contrôles et l'écriture se recalculeront automatiquement.</p>`;
}

function updateVerifyTag(r) {
  const missing = !r || r.subtotal == null || r.tax == null || r.total == null || r.subtotal === 0;
  $('#verify-tag').innerHTML = missing ? `<span class="tag-verify">⚠️ à vérifier</span>` : '';
}

async function saveReceipt() {
  const payload = readReceiptFromDOM();
  payload.persist = true;
  try {
    const data = await API.validate(payload);
    if (data.persisted) {
      toast('✅ Reçu #' + data.receipt_id + ' enregistré dans vos dépenses');
      await refreshSession();
      renderAnalyzeEmpty();
    } else {
      toast('Enregistré côté calcul mais non persisté.');
    }
  } catch (e) {
    toast('Enregistrement impossible : ' + e.message);
  }
}

/* ==========================================================================
   ONGLET 2 — TABLEAU DE BORD
   ========================================================================== */
async function loadDashboard() {
  const body = $('#dashboard-body');
  body.innerHTML = `<p class="muted">Chargement…</p>`;
  try {
    const d = await API.dashboard();
    state.demoMode = !!d.demo_mode;
    $('#demo-banner').classList.toggle('hidden', !state.demoMode);
    if (d.empty) { body.innerHTML = emptyDashboard(); wireEmptyState(); return; }
    const k = d.kpis;
    const kpis = `<div class="kpi-grid">
      <div class="kpi"><div class="label-caps">Reçus analysés</div><div class="value">${money(k.n_receipts)}</div></div>
      <div class="kpi"><div class="label-caps">Articles</div><div class="value">${money(k.n_items)}</div></div>
      <div class="kpi"><div class="label-caps">Dépense totale</div><div class="value">${money(k.total_spend)}</div></div>
      <div class="kpi ${k.n_anomalies ? 'kpi--alert receipt-open-kpi' : ''}" id="kpi-anomalies"
           ${k.n_anomalies ? 'title="Voir les reçus à vérifier" style="cursor:pointer"' : ''}>
        <div class="label-caps">À vérifier</div><div class="value">${money(k.n_anomalies)}</div></div>
    </div>`;

    const maxCat = Math.max(...d.by_category.map(c => c.total), 1);
    const cats = `<div class="card"><div class="section-head"><span class="label-caps">Dépenses par catégorie</span></div>
      <div class="section-body bars">${d.by_category.map(c => `
        <div class="bar-row"><span>${esc(c.category)}</span>
          <span class="bar-track"><span class="bar-fill" style="width:${(c.total / maxCat * 100).toFixed(1)}%"></span></span>
          <span class="num">${money(c.total)}</span></div>`).join('')}</div></div>`;

    const maxD = Math.max(...d.distribution.map(x => x.count), 1);
    const dist = `<div class="card"><div class="section-head"><span class="label-caps">Répartition des totaux</span></div>
      <div class="section-body bars">${d.distribution.map(x => `
        <div class="bar-row"><span class="body-sm">${esc(x.range)}</span>
          <span class="bar-track"><span class="bar-fill" style="width:${(x.count / maxD * 100).toFixed(1)}%"></span></span>
          <span class="num">${x.count}</span></div>`).join('')}</div></div>`;

    const totalReceipts = k.n_receipts || (d.receipts ? d.receipts.length : 0);
    const anomalyRate = totalReceipts ? (k.n_anomalies / totalReceipts * 100) : 0;
    const highRateNote = anomalyRate > 15 ? `<p class="banner">ℹ️ ${money(k.n_anomalies)} reçus sur ${money(totalReceipts)} (${anomalyRate.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} %) présentent au moins une incohérence. La cause la plus fréquente est un écart entre sous-total + taxe et total, souvent dû à des frais de service ou pourboires non extraits par le modèle.</p>` : '';
    const anomalies = d.anomalies.length ? `<div class="card">
      <div class="section-head"><span class="label-caps">Reçus à vérifier (${d.anomalies.length})</span></div>
      <div class="section-body">
        <p class="muted body-sm">Ces reçus présentent des incohérences dans leurs montants. Cliquez sur un reçu pour voir le détail et corriger si nécessaire. Un signalement ne signifie pas une erreur certaine — il peut s'agir d'un frais de service non extrait ou d'un arrondi de caisse.</p>
        ${highRateNote}
      </div>
      <div class="section-body stack">${d.anomalies.slice(0, 30).map(a => `
        <div class="card receipt-open receipt-review" data-id="${a.receipt_id}" title="Voir le détail du reçu"><div class="section-body">
          <b>${receiptLabel(a)}</b> — ${esc(a.rule)}
          ${a.a_label ? `<div class="muted body-sm tabular">${esc(a.a_label)} : ${money(a.a_value)} · ${esc(a.b_label)} : ${money(a.b_value)}
            · Écart : ${money(Math.abs((a.b_value || 0) - (a.a_value || 0)))}</div>` : ''}
        </div></div>`).join('')}
        ${d.anomalies.length > 30 ? `<p class="muted body-sm">… et ${d.anomalies.length - 30} autres.</p>` : ''}
      </div></div>` : '';

    // Liste des reçus, cliquable + filtres rapides (Tâche 3).
    body.innerHTML = kpis + `<div class="grid-2">${cats}${dist}</div>` + anomalies
      + receiptsListCard(d.receipts, 'Vos reçus', { id: 'dash-receipts', filters: true });
    // Délégation unique sur le tab-body : couvre lignes de liste ET cartes d'anomalie.
    wireReceiptOpen($('#dashboard-body'), loadDashboard);
    // Filtres rapides + KPI "à vérifier" cliquable (du chiffre aux reçus en 1 clic).
    $$('#receipt-filters .filter-btn').forEach(b => b.onclick = () => applyReceiptFilter(b.dataset.filter));
    const kpiA = $('#kpi-anomalies');
    if (kpiA && k.n_anomalies) kpiA.onclick = () => {
      applyReceiptFilter('review');
      $('#dash-receipts').scrollIntoView({ behavior: 'smooth' });
    };
  } catch (e) {
    body.innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
  }
}

/* ==========================================================================
   DÉTAIL D'UN REÇU — point d'entrée UNIQUE, appelé partout (Chantier 2)
   openReceiptDetail(id, container, restore) : affiche le détail dans
   `container` ; le bouton Retour appelle `restore()` (écran d'origine).
   ========================================================================== */
async function openReceiptDetail(id, container, restore) {
  container.innerHTML = `<p class="muted">Chargement du reçu #${esc(id)}…</p>`;
  try {
    // Recalcul de l'audit avec le BON pays : les reçus de démo sont le corpus
    // CORD (indonésien) -> ID ; sinon le pays sélectionné. Sans ça, la taxe
    // indonésienne était jugée sous le seuil ivoirien et le chip se contredisait
    // entre le dashboard (ID) et le détail.
    const country = state.demoMode ? 'ID' : state.country;
    container.innerHTML = receiptDetailHtml(id, await API.receipt(id, country), country);
  } catch (e) {
    container.innerHTML = `<div class="error-box">${esc(e.message)}</div>
      <div class="btn-row" style="margin-top:var(--md)"><button class="btn" id="detail-back">← Retour</button></div>`;
  }
  const b = container.querySelector('#detail-back');
  if (b) b.onclick = restore;
}

// Détail (réutilise controlsHtml() et money() ; bundle serveur = build_receipt_bundle).
function receiptDetailHtml(id, d, country) {
  const r = d.receipt, a = d.audit || {};
  const items = (r.items || []).map(it => `<tr>
    <td>${esc(it.name || '—')}</td><td class="num">${it.quantity ?? ''}</td>
    <td class="num">${money(it.unit_price)}</td><td class="num">${money(it.line_price)}</td></tr>`).join('')
    || `<tr><td colspan="4" class="muted">Aucun article enregistré.</td></tr>`;
  const controls = controlsHtml(a, d.balanced, r, d.journal, country);
  const encart = reviewBanner(reviewPoints(a, d.balanced, r), false);
  const journal = d.journal ? d.journal.map(l => `<tr>
    <td style="color:var(--primary);font-weight:500">${esc(l.account)}</td>
    <td>${esc(l.label)}</td><td class="num">${money(l.debit)}</td>
    <td class="num">${money(l.credit)}</td></tr>`).join('')
    : `<tr><td colspan="4" class="muted">Écriture impossible : montants insuffisants.</td></tr>`;
  return `
    <div class="btn-row" style="margin-bottom:var(--md)">
      <button class="btn" id="detail-back">← Retour</button></div>
    ${encart}
    <div class="card"><div class="section-head">
      <span class="label-caps">${receiptLabel({ doc_type: d.doc_type, invoice_number: d.invoice_number, receipt_id: id })}${d.category ? ' — ' + esc(d.category) : ''}</span></div>
      <div class="section-body muted body-sm">Reçu enregistré — aucune image conservée (données en mémoire de session).</div></div>
    <div class="card"><div class="section-head"><span class="label-caps">Articles</span></div>
      <table><thead><tr><th>Article</th><th class="num">Qté</th><th class="num">Prix unit.</th>
        <th class="num">Total ligne</th></tr></thead><tbody>${items}</tbody></table>
      <div class="section-body tabular">Sous-total : ${money(r.subtotal)} · Taxe : ${money(r.tax)} · Total : ${money(r.total)}</div></div>
    <div class="card"><div class="section-head"><span class="label-caps">Contrôles</span></div>
      <div class="section-body">${controls}</div></div>
    <div class="card"><div class="section-head"><span class="label-caps">Écriture comptable</span></div>
      <table><thead><tr><th>Compte</th><th>Libellé</th><th class="num">Débit</th><th class="num">Crédit</th></tr></thead>
        <tbody>${journal}</tbody></table>
      <p class="muted body-sm" style="margin:var(--sm) var(--md)">ℹ️ Affectation comptable indicative, à valider par un professionnel (expert-comptable) avant tout usage officiel.</p></div>`;
}

// Composant liste de reçus cliquables, réutilisé (Dashboard + listes filtrées).
function receiptRowHtml(r) {
  const st = receiptStatus(r);
  return `<tr class="receipt-open ${st.rowClass}" data-id="${r.receipt_id}" data-status="${st.status}" title="Voir le détail du reçu">
    <td><b>${receiptLabel(r)}</b></td><td>${esc(r.category || '—')}</td>
    <td class="num">${r.n_items}</td><td class="num">${money(r.total)}</td>
    <td>${st.badge}</td></tr>`;
}
function receiptFilterBar(receipts) {
  const total = receipts.length;
  const review = receipts.filter(r => receiptStatus(r).status === 'review').length;
  return `<div class="filter-bar" id="receipt-filters">
    <button class="btn filter-btn active" data-filter="all">Tous (${total})</button>
    <button class="btn filter-btn" data-filter="conforme">✓ Conformes (${total - review})</button>
    <button class="btn filter-btn" data-filter="review">⚠️ À vérifier (${review})</button></div>`;
}
// Filtre la liste des reçus SANS re-render (préserve la délégation d'événement).
function applyReceiptFilter(filter) {
  $$('#receipt-filters .filter-btn').forEach(b => b.classList.toggle('active', b.dataset.filter === filter));
  $$('#dash-receipts tbody tr.receipt-open').forEach(tr => {
    const st = tr.dataset.status;
    const show = filter === 'all' || (filter === 'review' ? st === 'review' : st !== 'review');
    tr.classList.toggle('row-hidden', !show);
  });
}
function receiptsListCard(receipts, title, opts) {
  if (!receipts || !receipts.length) return '';
  opts = opts || {};
  const idAttr = opts.id ? ` id="${opts.id}"` : '';
  const filters = opts.filters ? receiptFilterBar(receipts) : '';
  return `<div class="card"${idAttr}>
    <div class="section-head"><span class="label-caps">${esc(title)} (${receipts.length})</span>
      <span class="muted body-sm">Cliquez une ligne pour voir le détail</span></div>
    ${filters}
    <table><thead><tr><th>Reçu</th><th>Catégorie</th><th class="num">Articles</th>
      <th class="num">Total</th><th>Contrôle</th></tr></thead>
      <tbody>${receipts.map(receiptRowHtml).join('')}</tbody></table></div>`;
}
// Délégation d'événement sur un conteneur : tout élément .receipt-open (ligne,
// carte d'anomalie, groupe de journal…) ouvre le détail, avec le bon retour.
function wireReceiptOpen(container, restore) {
  container.onclick = (e) => {
    const el = e.target.closest('.receipt-open');
    if (el && container.contains(el)) openReceiptDetail(el.dataset.id, container, restore);
  };
}

// État vide du tableau de bord : 4 KPI à zéro grisés + CTA + mention démo.
function emptyDashboard() {
  const zero = (lbl) => `<div class="kpi kpi--muted"><div class="label-caps">${lbl}</div><div class="value">0</div></div>`;
  return `
    <div class="kpi-grid">
      ${zero('Reçus analysés')}${zero('Articles')}${zero('Dépense totale')}${zero('À vérifier')}
    </div>
    <div class="card"><div class="empty-state">
      <div class="empty-icon">👋</div>
      <p class="headline-sm">Bienvenue !</p>
      <p class="muted">Commencez par analyser un reçu, ou explorez l'application avec les données de démonstration.</p>
      <div class="btn-row" style="justify-content:center;margin-top:var(--md)">
        <button class="btn btn--primary" id="empty-analyze">📷 Analyser un reçu</button>
        <button class="btn" id="empty-demo">🔬 Mode démo</button>
      </div>
    </div></div>`;
}

function wireEmptyState() {
  const b = $('#empty-analyze');
  if (b) b.onclick = () => { const t = $('#nav button[data-tab="analyze"]'); switchTab('analyze', t); };
  const dm = $('#empty-demo');
  if (dm) dm.onclick = async () => {
    try { await API.setDemo(true); } catch (e) { /* ignore */ }
    await refreshSession();
    loadDashboard();
  };
}

/* ==========================================================================
   ONGLET 3 — COMPTABILITÉ
   ========================================================================== */
function loadAccounting() {
  $('#sel-period').onchange = renderAccounting;
  renderAccounting();
}
async function renderAccounting() {
  const body = $('#accounting-body');
  body.innerHTML = `<p class="muted">Chargement…</p>`;
  try {
    const d = await API.accounting($('#sel-period').value, state.payment, state.country);
    state.demoMode = !!d.demo_mode;
    $('#demo-banner').classList.toggle('hidden', !state.demoMode);
    if (d.empty) {
      body.innerHTML = `
        <div class="card"><div class="empty-state">
          <div class="empty-icon">🧮</div>
          <p class="headline-sm">Aucune écriture — analysez un reçu pour commencer</p>
          <p class="muted">Le journal comptable et la TVA se construisent à partir de vos reçus validés.</p>
          <div class="btn-row" style="justify-content:center;margin-top:var(--md)">
            <button class="btn btn--primary" id="empty-analyze">📷 Analyser un reçu</button>
          </div>
          <p class="muted body-sm" style="margin-top:var(--md)">💡 Ou activez le mode démonstration dans ⚙️ Réglages.</p>
        </div></div>`;
      wireEmptyState();
      return;
    }
    const v = d.vat, rep = d.report;
    const reasons = Object.entries(v.non_recoverable_reasons || {}).map(([r, det]) => {
      const text = /fournisseur/i.test(r)
        ? `${det.count} reçus — TVA non récupérable : le nom du fournisseur n'apparaît pas sur ces reçus, ce qui empêche la déduction fiscale de la TVA. Pour récupérer la TVA, demandez une facture nominative au fournisseur.`
        : `${esc(r)} : ${det.count} reçu(s), ${money(det.amount)}`;
      return `<div class="body-sm reason-link" data-reason="${esc(r)}" title="Voir les reçus concernés">• ${text} →</div>`;
    }).join('');

    const vatCard = `<div class="card"><div class="section-head"><span class="label-caps">TVA — ${esc(d.period)}</span></div>
      <div class="section-body grid-2">
        <div><div class="label-caps">Récupérable</div><div class="headline-sm tabular">${money(v.recoverable_total)}</div></div>
        <div><div class="label-caps">Non récupérable</div><div class="headline-sm tabular">${money(v.non_recoverable_total)}</div>${reasons}</div>
      </div></div>`;

    const reportCard = `<div class="card"><div class="section-head"><span class="label-caps">Note de frais agrégée</span></div>
      <div class="section-body kpi-grid">
        <div class="kpi"><div class="label-caps">Total HT</div><div class="value">${money(rep.total_ht)}</div></div>
        <div class="kpi"><div class="label-caps">Total TVA</div><div class="value">${money(rep.total_tax)}</div></div>
        <div class="kpi"><div class="label-caps">Total TTC</div><div class="value">${money(rep.total_ttc)}</div></div>
      </div></div>`;

    const rows = d.journal.slice(0, 100).map(g => g.lines.map((l, i) => `
      <tr class="${g.balanced ? '' : 'unbalanced'}">
        ${i === 0 ? `<td rowspan="${g.lines.length}" class="receipt-open" data-id="${g.receipt_id}" title="Voir le détail du reçu"><b>${receiptLabel(g)}</b> ${g.balanced ? '✅' : '❌'}</td>` : ''}
        <td>${esc(l.account)}</td><td>${esc(l.label)}</td>
        <td class="num">${money(l.debit)}</td><td class="num">${money(l.credit)}</td></tr>`).join('')).join('');
    const journalCard = `<div class="card"><div class="section-head"><span class="label-caps">Journal général, groupé par reçu</span>
      <button class="btn" id="export-journal">📥 Export CSV</button></div>
      <table><thead><tr><th>Reçu</th><th>Compte</th><th>Libellé</th><th class="num">Débit</th><th class="num">Crédit</th></tr></thead>
        <tbody>${rows}</tbody></table>
      ${d.journal.length > 100 ? `<div class="section-body muted body-sm">Affichage des 100 premiers reçus sur ${d.journal.length}.</div>` : ''}</div>`;

    // Disclaimer remonté en tête, visible sans scroller (Tâche 4).
    const disclaimer = `<div class="banner">ℹ️ ${esc(d.disclaimer)}</div>`;
    body.innerHTML = disclaimer + vatCard + reportCard + journalCard;
    $('#export-journal').onclick = () => exportJournalCsv(d.journal);
    // Groupes de journal cliquables -> détail (retour = comptabilité).
    wireReceiptOpen(body, renderAccounting);
    // Motif TVA cliquable -> liste filtrée des reçus concernés.
    $$('.reason-link', body).forEach(el => {
      el.onclick = () => renderFilteredReceipts(el.dataset.reason, d);
    });
  } catch (e) {
    body.innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
  }
}

// Liste filtrée par motif TVA : réutilise le composant liste du Dashboard.
// Retour depuis un détail -> revient à CETTE liste filtrée (pas au Dashboard).
function renderFilteredReceipts(reason, d) {
  const body = $('#accounting-body');
  const filtered = (d.receipts || []).filter(r => r.vat_reason === reason);
  body.innerHTML = `
    <div class="btn-row" style="margin-bottom:var(--md)"><button class="btn" id="filter-back">← Retour à la comptabilité</button></div>
    <div class="card"><div class="section-body"><b>Reçus — motif :</b> ${esc(reason)} <span class="muted">(${filtered.length})</span></div></div>
    ${receiptsListCard(filtered, 'Reçus concernés')}`;
  $('#filter-back').onclick = renderAccounting;
  wireReceiptOpen(body, () => renderFilteredReceipts(reason, d));
}

function exportJournalCsv(journal) {
  const lines = [['receipt_id', 'account', 'label', 'debit', 'credit', 'balanced']];
  journal.forEach(g => g.lines.forEach(l =>
    lines.push([g.receipt_id, l.account, `"${(l.label || '').replace(/"/g, '""')}"`, l.debit, l.credit, g.balanced])));
  const csv = lines.map(r => r.join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'journal_comptable.csv'; a.click();
}

/* ==========================================================================
   ONGLET 4 — QUESTIONS
   ========================================================================== */
function setupAsk() {
  const suggestions = ['Combien ai-je dépensé en boissons ?', 'Montre-moi les reçus de plus de 100 000', 'Quel est le total du dernier trimestre ?'];
  $('#ask-suggestions').innerHTML = suggestions.map(s => `<span class="pill">${esc(s)}</span>`).join('');
  $$('#ask-suggestions .pill').forEach(p => p.onclick = () => { $('#ask-input').value = p.textContent; doAsk(); });
  $('#ask-search').onclick = doAsk;
  $('#ask-input').onkeydown = e => { if (e.key === 'Enter') doAsk(); };
  // Session vide (hors démo) : prévenir que la recherche portera sur le corpus.
  if (state.sessionEmpty && !state.demoMode) {
    $('#ask-body').innerHTML = `<div class="banner">🔬 Vous n'avez pas encore de reçus personnels. La recherche porte sur le
      <b>corpus de référence CORD</b> (800 reçus indonésiens). Analysez vos propres reçus dans l'onglet Analyser pour interroger VOS dépenses.</div>`;
  }
}

async function doAsk() {
  const q = $('#ask-input').value.trim();
  if (!q) return;
  const body = $('#ask-body');
  body.innerHTML = `<p class="muted">Recherche…</p>`;
  try {
    const d = await API.search(q);
    if (!d.search_available) { body.innerHTML = `<div class="banner">${esc(d.note)}</div>`; return; }
    // Périmètre de recherche affiché clairement, d'après l'état RÉEL renvoyé par
    // le serveur (scope/demo) — jamais un libellé figé (tâche 3 + anti-obsolescence).
    let scopeNote;
    if (d.reference_corpus) {
      scopeNote = `<div class="banner">🔬 Recherche dans le <b>corpus de référence CORD</b>
        (aucun reçu personnel pour l'instant — ce ne sont pas vos dépenses).</div>`;
    } else if (d.demo_mode) {
      scopeNote = `<div class="banner">🔬 <b>Mode démonstration</b> : recherche dans le corpus CORD, pas vos dépenses réelles.</div>`;
    } else {
      const n = d.sources ? d.sources.length : 0;
      scopeNote = `<div class="banner">🔎 Recherche dans <b>vos reçus</b> (${n} résultat${n > 1 ? 's' : ''} le${n > 1 ? 's' : ''} plus pertinent${n > 1 ? 's' : ''}).</div>`;
    }
    const answer = scopeNote + `<div class="card"><div class="section-head"><span class="label-caps">Réponse</span></div>
      <div class="section-body">${d.answer ? esc(d.answer)
        : `D'après les reçus les plus pertinents pour : <i>${esc(q)}</i>.` +
          (state.config.groq_configured ? '' : ` <span class="muted body-sm">(réponse LLM désactivée : aucune clé Groq)</span>`)}</div></div>`;
    const sources = `<div class="card"><div class="section-head"><span class="label-caps">Reçus sources — la réponse est fondée sur eux (RAG)</span></div>
      <div class="section-body stack">${d.sources.map(s => {
        const clickable = s.receipt_id != null;   // reçu présent dans la session -> cliquable
        return `<div class="card${clickable ? ' receipt-open' : ''}"${clickable ? ` data-id="${s.receipt_id}" title="Voir le détail de ce reçu"` : ''}><div class="section-body">
          <span class="score">Pertinence ${(s.score * 100).toFixed(0)}%</span>
          <div class="bar-track" style="margin:6px 0"><span class="bar-fill" style="width:${Math.max(0, Math.min(100, s.score * 100))}%"></span></div>
          ${esc(s.text)}${clickable ? ' <span class="muted body-sm">— cliquer pour le détail</span>' : ''}</div></div>`;
      }).join('')}</div></div>`;
    body.innerHTML = answer + sources;
    // Retour depuis un détail = relancer la recherche (input conservé) -> revient à Ask.
    wireReceiptOpen($('#ask-body'), doAsk);
    state.askHistory.unshift(q);
    renderAskHistory();
  } catch (e) {
    body.innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
  }
}
function renderAskHistory() {
  if (!state.askHistory.length) return;
  $('#ask-history').innerHTML = `<div class="label-caps">Questions précédentes</div>` +
    state.askHistory.slice(0, 10).map(q => `<div class="muted body-sm">• ${esc(q)}</div>`).join('');
}

/* ==========================================================================
   ONGLET 5 — TECHNIQUE
   ========================================================================== */
async function loadTechnical() {
  const body = $('#technical-body');
  body.innerHTML = `<p class="muted">Chargement…</p>`;
  try {
    const d = await API.technical();
    const resultsTable = `<div class="card"><div class="section-head"><span class="label-caps">Donut vs baseline</span></div>
      <table><thead><tr><th>Modèle</th><th class="num">Exactitude</th><th class="num">JSON valide</th><th>Entraîné par moi</th></tr></thead>
        <tbody>${d.results.map(r => `<tr><td>${esc(r.modele)}</td>
          <td class="num">${r.exactitude_total != null ? (r.exactitude_total * 100).toFixed(1) + '%' : '—'}</td>
          <td class="num">${r.json_valide != null ? (r.json_valide * 100).toFixed(1) + '%' : '—'}</td>
          <td>${r.entraine_par_moi ? 'oui' : 'non'}</td></tr>`).join('')}</tbody></table></div>`;

    const of = d.overfitting;
    const ofMetrics = of.length ? `<div class="card"><div class="section-head"><span class="label-caps">Sur-apprentissage (baseline maison)</span></div>
      <div class="section-body kpi-grid">
        <div class="kpi"><div class="label-caps">Écart sans régularisation</div><div class="value">${(of[0].ecart * 100).toFixed(1)}%</div></div>
        <div class="kpi kpi--alert"><div class="label-caps">Écart avec régularisation</div><div class="value">${(of[of.length - 1].ecart * 100).toFixed(1)}%</div></div>
        <div class="kpi"><div class="label-caps">Train (régularisé)</div><div class="value">${(of[of.length - 1].train * 100).toFixed(1)}%</div></div>
        <div class="kpi"><div class="label-caps">Validation (régularisé)</div><div class="value">${(of[of.length - 1].validation * 100).toFixed(1)}%</div></div>
      </div>
      <table><thead><tr><th>Config</th><th class="num">Train</th><th class="num">Validation</th><th class="num">Écart</th></tr></thead>
        <tbody>${of.map(r => `<tr><td>${esc(r.config)}</td><td class="num">${(r.train * 100).toFixed(1)}%</td>
          <td class="num">${(r.validation * 100).toFixed(1)}%</td><td class="num">${(r.ecart * 100).toFixed(1)}%</td></tr>`).join('')}</tbody></table></div>` : '';

    const loss = `<div class="card"><div class="section-head"><span class="label-caps">Courbe de perte (entraînement baseline)</span></div>
      <div class="section-body">${lossCurveSvg(d.loss_curve)}</div></div>`;

    const methodo = `<div class="card"><div class="section-body">
      <div class="label-caps">Méthodologie : drapeau binaire plutôt que pourcentage de confiance</div>
      <p class="body-sm">Un champ est marqué <b>« à vérifier »</b> (booléen) s'il est absent, nul, ou s'il fait échouer une règle.
      Nous n'affichons <b>volontairement aucun pourcentage de confiance</b> : un score comme « 85 % » laisse croire à une
      fiabilité mesurée alors qu'il ne reflète que la confiance interne du modèle, pas l'exactitude réelle du champ.
      Le binaire évite ce faux sentiment de certitude et pousse à la vérification humaine.</p></div></div>`;

    body.innerHTML = resultsTable + ofMetrics + loss + methodo;
  } catch (e) {
    body.innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
  }
}

// petite courbe SVG maison (pas de librairie)
function lossCurveSvg(points) {
  if (!points || !points.length) return `<p class="muted">Pas de données de perte.</p>`;
  const W = 600, H = 200, pad = 30;
  const xs = points.map(p => p.iteration), ys = points.map(p => p.loss);
  const xmin = Math.min(...xs), xmax = Math.max(...xs), ymin = Math.min(...ys), ymax = Math.max(...ys);
  const sx = i => pad + (i - xmin) / (xmax - xmin || 1) * (W - 2 * pad);
  const sy = l => H - pad - (l - ymin) / (ymax - ymin || 1) * (H - 2 * pad);
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${sx(p.iteration).toFixed(1)},${sy(p.loss).toFixed(1)}`).join(' ');
  return `<svg class="loss" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <line x1="${pad}" y1="${H - pad}" x2="${W - pad}" y2="${H - pad}" stroke="var(--outline-variant)"/>
    <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${H - pad}" stroke="var(--outline-variant)"/>
    <path d="${path}" fill="none" stroke="var(--primary-container)" stroke-width="2"/>
    <text x="${pad}" y="${pad - 8}" font-size="11" fill="var(--on-surface-variant)">perte ${ymax.toFixed(2)} → ${ymin.toFixed(2)}</text>
  </svg>`;
}

/* ==========================================================================
   RÉGLAGES (panneau)
   ========================================================================== */
function wireSettings() {
  const open = () => { $('#overlay').classList.add('open'); $('#panel').classList.add('open'); renderSettings(); };
  const close = () => { $('#overlay').classList.remove('open'); $('#panel').classList.remove('open'); };
  $('#btn-settings').onclick = open;
  $('#panel-close').onclick = close;
  $('#overlay').onclick = close;
}
function renderSettings() {
  const c = state.config;
  const taxes = Object.entries(c.countries).map(([k, r]) =>
    `<div class="muted body-sm">${k} : ${(r * 100).toFixed(0)} %</div>`).join('');
  const accounts = Object.entries(c.chart_of_accounts).map(([code, lbl]) =>
    `<tr><td>${code}</td><td>${esc(lbl)}</td></tr>`).join('');
  $('#panel-body').innerHTML = `
    <div class="card"><div class="section-head"><span class="label-caps">Pays et taux de TVA</span></div>
      <div class="section-body">${taxes}</div></div>

    <div class="card"><div class="section-head"><span class="label-caps">Clés API</span></div>
      <div class="section-body stack">
        <div>
          <label class="field" for="in-groq-key">Clé Groq</label>
          <input id="in-groq-key" type="password" autocomplete="off" placeholder="gsk_…" />
          <div id="groq-status" class="body-sm muted" style="margin-top:var(--xs)">Vérification de l'état…</div>
        </div>
        <div class="btn-row">
          <button class="btn" id="btn-key-test">Tester la connexion</button>
          <button class="btn btn--primary" id="btn-key-save">Enregistrer</button>
          <button class="btn" id="btn-key-clear">Effacer</button>
        </div>
        <div id="key-test-result" class="body-sm"></div>
        <div class="btn-row"><button class="btn" id="btn-key-models">Voir les modèles disponibles</button></div>
        <div id="models-result" class="body-sm"></div>
        <p class="muted body-sm">🔒 Obtenez une clé gratuite sur <b>console.groq.com</b>.
          Elle sert au fallback vision, à l'extraction marchand/date et aux réponses du RAG.
          La clé reste <b>en mémoire</b> (jamais écrite sur disque, jamais renvoyée par le serveur).</p>
      </div></div>

    <div class="card"><div class="section-head"><span class="label-caps">Données de démonstration</span></div>
      <div class="section-body stack">
        <p class="body-sm">Peuple le tableau de bord et la comptabilité avec le <b>corpus CORD</b>
          (≈800 reçus indonésiens) pour une démonstration, sans déposer de reçus. Un bandeau permanent
          le signale. Ce ne sont <b>pas</b> vos dépenses réelles.</p>
        <div class="btn-row">
          <button class="btn btn--primary" id="btn-demo-on">Charger les données de démonstration</button>
          <button class="btn" id="btn-demo-off">Vider mes données de session</button>
        </div>
        <div id="demo-result" class="body-sm muted"></div>
      </div></div>

    <div class="card"><div class="section-head"><span class="label-caps">Plan de comptes (SYSCOHADA)</span></div>
      <table><thead><tr><th>Compte</th><th>Libellé</th></tr></thead><tbody>${accounts}</tbody></table></div>
    <p class="muted body-sm">ℹ️ ${esc(c.disclaimer)}</p>`;
  wireApiKeys();
  wireDemo();
  refreshKeyStatus();
}

function wireDemo() {
  const result = $('#demo-result');
  const setState = (d) => {
    state.demoMode = !!d.demo_mode;
    state.sessionEmpty = !!d.empty;
    $('#demo-banner').classList.toggle('hidden', !state.demoMode);
    result.textContent = state.demoMode
      ? `🔬 Mode démonstration actif — ${d.n_receipts} reçus du corpus CORD.`
      : (d.n_receipts ? `${d.n_receipts} reçu(s) dans votre session.` : 'Session vide.');
  };
  API.session().then(setState).catch(() => {});
  $('#btn-demo-on').onclick = async () => {
    result.textContent = 'Chargement du corpus…';
    try { setState(await API.setDemo(true)); toast('🔬 Données de démonstration chargées'); }
    catch (e) { result.textContent = 'Échec : ' + e.message; }
  };
  $('#btn-demo-off').onclick = async () => {
    try { setState(await API.clearSession()); toast('Session vidée'); }
    catch (e) { result.textContent = 'Échec : ' + e.message; }
  };
}

// Clé mémorisée dans sessionStorage (effacée à la fermeture de l'onglet),
// JAMAIS localStorage. Sert uniquement à re-fournir la clé au serveur si son
// process a redémarré pendant la session du navigateur.
const GROQ_SS_KEY = 'copilote.groqKey';

const KEY_STATUS_LABEL = {
  env: "✅ Configurée (variable d'environnement) — saisissez une clé pour la remplacer",
  session: '✅ Configurée (session)',
  none: '➖ Non configurée — recherche sémantique seule',
};

async function refreshKeyStatus() {
  const el = $('#groq-status'), input = $('#in-groq-key');
  if (!el) return;
  try {
    let s = await API.keyStatus();
    let src = s.groq.source;
    // Si le serveur ne connaît aucune clé mais que le navigateur en garde une
    // (redémarrage serveur), on la re-transmet une fois puis on relit l'état.
    if (src === 'none') {
      const saved = sessionStorage.getItem(GROQ_SS_KEY);
      if (saved) {
        try { await API.setKey('groq', saved); s = await API.keyStatus(); src = s.groq.source; }
        catch (e) { sessionStorage.removeItem(GROQ_SS_KEY); }
      }
    }
    el.textContent = KEY_STATUS_LABEL[src] || src;
    state.config.groq_configured = src !== 'none';
    // Aucun verrouillage : une clé de session peut toujours remplacer l'env,
    // et « Effacer » retire l'éventuelle clé de session (retour à l'env/none).
    input.disabled = false;
    input.placeholder = 'gsk_…';
    $('#btn-key-save').disabled = false;
    $('#btn-key-clear').disabled = false;
  } catch (e) {
    el.textContent = 'État indisponible.';
  }
}

function wireApiKeys() {
  $('#btn-key-save').onclick = async () => {
    const key = $('#in-groq-key').value.trim();
    try {
      await API.setKey('groq', key);
      sessionStorage.setItem(GROQ_SS_KEY, key);
      $('#in-groq-key').value = '';
      $('#key-test-result').textContent = '';
      toast('✅ Clé Groq enregistrée (session)');
      refreshKeyStatus();
    } catch (e) {
      toast('Clé refusée : ' + e.message);
    }
  };

  $('#btn-key-clear').onclick = async () => {
    try { await API.clearKey('groq'); } catch (e) { /* on efface côté nav quoi qu'il arrive */ }
    sessionStorage.removeItem(GROQ_SS_KEY);
    $('#in-groq-key').value = '';
    $('#key-test-result').textContent = '';
    toast('Clé effacée');
    refreshKeyStatus();
  };

  $('#btn-key-test').onclick = async () => {
    const res = $('#key-test-result');
    const typed = $('#in-groq-key').value.trim();
    res.className = 'body-sm muted';
    res.textContent = 'Test en cours…';
    try {
      // Une clé saisie mais non encore enregistrée est d'abord posée en session.
      if (typed) {
        await API.setKey('groq', typed);
        sessionStorage.setItem(GROQ_SS_KEY, typed);
        $('#in-groq-key').value = '';
      }
      const d = await API.testKey('groq');
      res.className = 'body-sm';
      res.textContent = '✅ ' + (d.message || 'Connexion réussie.');
      refreshKeyStatus();
    } catch (e) {
      res.className = 'body-sm';
      res.textContent = '❌ ' + e.message + (e.detail ? ' — ' + e.detail : '');
      refreshKeyStatus();
    }
  };

  // Liste des modèles réellement disponibles pour la clé (corrige le 404 vision :
  // le modèle vision est choisi parmi ceux-ci, plus jamais codé en dur).
  $('#btn-key-models').onclick = async () => {
    const res = $('#models-result');
    res.className = 'body-sm muted';
    res.textContent = 'Interrogation des modèles…';
    try {
      const d = await API.models();
      const visionLine = d.vision_available
        ? `✅ Vision utilisable : <b>${esc(d.vision_selected)}</b>`
        : `⚠️ Aucun modèle vision accessible avec cette clé — le fallback vision est indisponible.`;
      res.className = 'body-sm';
      res.innerHTML = `${visionLine}
        <div class="muted" style="margin-top:var(--xs)">Vision (${d.vision.length}) : ${d.vision.map(esc).join(', ') || '—'}</div>
        <div class="muted">Texte (${d.text.length}) : ${d.text.slice(0, 8).map(esc).join(', ')}${d.text.length > 8 ? '…' : ''}</div>`;
    } catch (e) {
      res.className = 'body-sm';
      res.textContent = '❌ ' + e.message + (e.detail ? ' — ' + e.detail : '');
    }
  };
}

document.addEventListener('DOMContentLoaded', init);
