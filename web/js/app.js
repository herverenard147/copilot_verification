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
  file: null,          // File courant (pour l'aperçu image)
  result: null,        // dernier /api/extract
  askHistory: [],
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

// chip 3 états : true=✅ / false=❌ / null=➖ (gris NEUTRE, jamais alarmant)
function chip(label, value) {
  const map = { true: ['chip--ok', '✅'], false: ['chip--bad', '❌'], null: ['chip--neutral', '➖'] };
  const key = value === true ? 'true' : value === false ? 'false' : 'null';
  const [cls, icon] = map[key];
  return `<span class="chip ${cls}">${icon} ${esc(label)}</span>`;
}

function engineBadge(engine) {
  if (engine === 'llm_fallback')
    return `<span class="badge badge--fallback">🛰️ Moteur : LLM vision (fallback)</span>`;
  return `<span class="badge badge--donut">🍩 Moteur : Donut</span>`;
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
  renderAnalyzeEmpty();
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
    const data = await API.extract(file, state.country, state.payment);
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
  paintAudit(data.audit, data.journal, data.balanced, data.vat, r.tax);
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
    country: state.country, payment_mode: state.payment, persist: false,
  };
}

// recalcul LIVE : /api/validate persist=false → met à jour chips + écriture
async function recompute() {
  const payload = readReceiptFromDOM();
  try {
    const data = await API.validate(payload);
    paintAudit(data.audit, data.journal, data.balanced, data.vat, payload.tax);
    updateVerifyTag(data.receipt);
  } catch (e) {
    toast('Recalcul impossible : ' + e.message);
  }
}

function paintAudit(audit, journal, balanced, vat, receiptTax) {
  const a = audit || {};
  $('#chips').innerHTML =
    chip('Lignes / sous-total', a.line_sum_ok ?? null) +
    chip('Sous-total + taxe / total', a.total_ok ?? null) +
    chip('Taux de taxe plausible', a.tax_ok ?? null) +
    chip("Équilibre de l'écriture", balanced ?? null);

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
  const vatNote = (vat && vat.recoverable === 0 && receiptTax)
    ? `<div class="banner" style="margin-top:var(--sm)">⚠️ TVA non récupérable — ${esc(vat.reason)}. Elle est réintégrée dans la charge.</div>`
    : '';
  jf.innerHTML = `<div class="tabular">Total débit : ${money(td)} · Total crédit : ${money(tc)} ·
    ${balanced ? '✅ équilibré' : '❌ déséquilibré'}</div>${vatNote}`;
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
      toast('✅ Reçu #' + data.receipt_id + ' enregistré dans les dépenses');
      loadedOnce.dashboardStale = true;
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
    if (d.empty) { body.innerHTML = `<div class="card"><div class="section-body muted">Aucun reçu analysé pour l'instant. Rendez-vous dans l'onglet <b>Analyser</b>.</div></div>`; return; }
    const k = d.kpis;
    const kpis = `<div class="kpi-grid">
      <div class="kpi"><div class="label-caps">Reçus analysés</div><div class="value">${money(k.n_receipts)}</div></div>
      <div class="kpi"><div class="label-caps">Articles</div><div class="value">${money(k.n_items)}</div></div>
      <div class="kpi"><div class="label-caps">Dépense totale</div><div class="value">${money(k.total_spend)}</div></div>
      <div class="kpi ${k.n_anomalies ? 'kpi--alert' : ''}"><div class="label-caps">Anomalies</div><div class="value">${money(k.n_anomalies)}</div></div>
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

    const anomalies = d.anomalies.length ? `<div class="card">
      <div class="section-head"><span class="label-caps">Anomalies actives (${d.anomalies.length})</span></div>
      <div class="section-body stack">${d.anomalies.slice(0, 30).map(a => `
        <div class="card"><div class="section-body">
          <b>Reçu #${a.receipt_id}</b> — ${esc(a.rule)}
          ${a.a_label ? `<div class="muted body-sm tabular">${esc(a.a_label)} : ${money(a.a_value)} · ${esc(a.b_label)} : ${money(a.b_value)}
            · Écart : ${money(Math.abs((a.b_value || 0) - (a.a_value || 0)))}</div>` : ''}
        </div></div>`).join('')}
        ${d.anomalies.length > 30 ? `<p class="muted body-sm">… et ${d.anomalies.length - 30} autres.</p>` : ''}
      </div></div>` : '';

    body.innerHTML = kpis + `<div class="grid-2">${cats}${dist}</div>` + anomalies;
  } catch (e) {
    body.innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
  }
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
    if (d.empty) { body.innerHTML = `<div class="card"><div class="section-body muted">Aucun reçu à comptabiliser.</div></div>`; return; }
    const v = d.vat, rep = d.report;
    const reasons = Object.entries(v.non_recoverable_reasons || {}).map(([r, det]) =>
      `<div class="muted body-sm">• ${esc(r)} : ${det.count} reçu(s), ${money(det.amount)}</div>`).join('');

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
        ${i === 0 ? `<td rowspan="${g.lines.length}"><b>#${g.receipt_id}</b> ${g.balanced ? '✅' : '❌'}</td>` : ''}
        <td>${esc(l.account)}</td><td>${esc(l.label)}</td>
        <td class="num">${money(l.debit)}</td><td class="num">${money(l.credit)}</td></tr>`).join('')).join('');
    const journalCard = `<div class="card"><div class="section-head"><span class="label-caps">Journal général, groupé par reçu</span>
      <button class="btn" id="export-journal">📥 Export CSV</button></div>
      <table><thead><tr><th>Reçu</th><th>Compte</th><th>Libellé</th><th class="num">Débit</th><th class="num">Crédit</th></tr></thead>
        <tbody>${rows}</tbody></table>
      ${d.journal.length > 100 ? `<div class="section-body muted body-sm">Affichage des 100 premiers reçus sur ${d.journal.length}.</div>` : ''}</div>`;

    const disclaimer = `<p class="muted body-sm">ℹ️ ${esc(d.disclaimer)}</p>`;
    body.innerHTML = vatCard + reportCard + journalCard + disclaimer;
    $('#export-journal').onclick = () => exportJournalCsv(d.journal);
  } catch (e) {
    body.innerHTML = `<div class="error-box">${esc(e.message)}</div>`;
  }
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
}

async function doAsk() {
  const q = $('#ask-input').value.trim();
  if (!q) return;
  const body = $('#ask-body');
  body.innerHTML = `<p class="muted">Recherche…</p>`;
  try {
    const d = await API.search(q);
    if (!d.search_available) { body.innerHTML = `<div class="banner">${esc(d.note)}</div>`; return; }
    const answer = `<div class="card"><div class="section-head"><span class="label-caps">Réponse</span></div>
      <div class="section-body">${d.answer ? esc(d.answer)
        : `D'après les reçus les plus pertinents pour : <i>${esc(q)}</i>.` +
          (state.config.groq_configured ? '' : ` <span class="muted body-sm">(réponse LLM désactivée : aucune clé Groq)</span>`)}</div></div>`;
    const sources = `<div class="card"><div class="section-head"><span class="label-caps">Reçus sources — la réponse est fondée sur eux (RAG)</span></div>
      <div class="section-body stack">${d.sources.map(s => `
        <div class="card"><div class="section-body">
          <span class="score">Pertinence ${(s.score * 100).toFixed(0)}%</span>
          <div class="bar-track" style="margin:6px 0"><span class="bar-fill" style="width:${Math.max(0, Math.min(100, s.score * 100))}%"></span></div>
          ${esc(s.text)}</div></div>`).join('')}</div></div>`;
    body.innerHTML = answer + sources;
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
        <p class="muted body-sm">🔒 Obtenez une clé gratuite sur <b>console.groq.com</b>.
          Elle sert au fallback vision, à l'extraction marchand/date et aux réponses du RAG.
          La clé reste <b>en mémoire</b> (jamais écrite sur disque, jamais renvoyée par le serveur).</p>
      </div></div>

    <div class="card"><div class="section-head"><span class="label-caps">Plan de comptes (SYSCOHADA)</span></div>
      <table><thead><tr><th>Compte</th><th>Libellé</th></tr></thead><tbody>${accounts}</tbody></table></div>
    <p class="muted body-sm">ℹ️ ${esc(c.disclaimer)}</p>`;
  wireApiKeys();
  refreshKeyStatus();
}

// Clé mémorisée dans sessionStorage (effacée à la fermeture de l'onglet),
// JAMAIS localStorage. Sert uniquement à re-fournir la clé au serveur si son
// process a redémarré pendant la session du navigateur.
const GROQ_SS_KEY = 'copilote.groqKey';

const KEY_STATUS_LABEL = {
  env: '✅ Configurée (env)',
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
    const envLocked = src === 'env';
    input.disabled = envLocked;
    input.placeholder = envLocked ? "Fournie par l'environnement (prioritaire)" : 'gsk_…';
    $('#btn-key-save').disabled = envLocked;
    $('#btn-key-clear').disabled = envLocked;
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
}

document.addEventListener('DOMContentLoaded', init);
