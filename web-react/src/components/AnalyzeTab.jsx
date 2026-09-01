import { useEffect, useRef, useState } from "react";
import API from "../api.js";
import { money } from "../utils.js";
import { toast } from "../toast.jsx";
import { Icon } from "../Icons.jsx";
import {
  ControlsPanel, EngineBadge, FlowDiagram, ImageOrPlaceholder, ReviewBanner,
  reviewPoints,
} from "../helpers.jsx";

const STEPS = [
  "Préparation et redressement de l'image",
  "Chargement du modèle (au 1er lancement)",
  "Lecture du reçu",
  "Vérification des règles comptables",
];

function emptyItem() { return { name: "", quantity: "", unit_price: "", line_price: "" }; }

export default function AnalyzeTab({ country, payment, docType, config, pendingEdit, onConsumeEdit, onSaved, onRequireAccount }) {
  const [file, setFile] = useState(null);
  const [phase, setPhase] = useState("empty"); // empty | loading | error | result
  const [stepIndex, setStepIndex] = useState(0);
  const [jobStatus, setJobStatus] = useState(null); // "pending" | "running" (statut réel du serveur)
  const [error, setError] = useState(null);
  const [extracted, setExtracted] = useState(null); // dernière réponse /api/extract ou /api/receipt (chargée pour édition)
  const [editingId, setEditingId] = useState(null);
  const [items, setItems] = useState([emptyItem()]);
  const [subtotal, setSubtotal] = useState("");
  const [tax, setTax] = useState("");
  const [total, setTotal] = useState("");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [accountOverrides, setAccountOverrides] = useState({});
  const [computed, setComputed] = useState(null); // { audit, journal, balanced, vat, receipt }
  const dragRef = useRef(false);

  // Reprise d'un reçu ouvert ailleurs pour édition (Dashboard/Comptabilité/Questions).
  useEffect(() => {
    if (!pendingEdit) return;
    const { id, data } = pendingEdit;
    setEditingId(id);
    setFile(null);
    setExtracted(data);
    setItems(data.receipt.items && data.receipt.items.length ? data.receipt.items : [emptyItem()]);
    setSubtotal(data.receipt.subtotal ?? "");
    setTax(data.receipt.tax ?? "");
    setTotal(data.receipt.total ?? "");
    setInvoiceNumber(data.invoice_number || "");
    setAccountOverrides({ ...(data.account_overrides || {}) });
    setComputed({ audit: data.audit, journal: data.journal, balanced: data.balanced, vat: data.vat, receipt: data.receipt });
    setPhase("result");
    onConsumeEdit();
  }, [pendingEdit, onConsumeEdit]);

  useEffect(() => {
    // L'animation des étapes n'avance que pendant "running" (le calcul a
    // réellement commencé côté serveur) : si une autre extraction est en
    // cours, ce job reste "pending" et l'affichage le dit honnêtement,
    // plutôt que de faire semblant d'avancer pendant une vraie attente.
    if (phase !== "loading" || jobStatus !== "running") return;
    setStepIndex(0);
    const t = setInterval(() => setStepIndex((i) => Math.min(i + 1, STEPS.length - 1)), 4000);
    return () => clearInterval(t);
  }, [phase, jobStatus]);

  function reset() {
    setFile(null); setExtracted(null); setEditingId(null); setAccountOverrides({});
    setItems([emptyItem()]); setSubtotal(""); setTax(""); setTotal(""); setInvoiceNumber("");
    setComputed(null); setPhase("empty"); setError(null);
  }

  async function handleFile(f) {
    setFile(f); setEditingId(null); setAccountOverrides({});
    setPhase("loading"); setError(null); setJobStatus("pending");
    try {
      // L'extraction (30-60s) tourne en tâche de fond côté serveur
      // (voir src/jobs.py) : on soumet puis on interroge le statut réel
      // jusqu'au résultat, plutôt que d'attendre une seule grosse réponse.
      const data = await API.extractAndWait(f, country, payment, docType, setJobStatus);
      setExtracted(data);
      setItems(data.receipt.items && data.receipt.items.length ? data.receipt.items : [emptyItem()]);
      setSubtotal(data.receipt.subtotal ?? "");
      setTax(data.receipt.tax ?? "");
      setTotal(data.receipt.total ?? "");
      setInvoiceNumber(data.invoice_number || "");
      setComputed({ audit: data.audit, journal: data.journal, balanced: data.balanced, vat: data.vat, receipt: data.receipt });
      setPhase("result");
    } catch (e) {
      setError(e);
      setPhase("error");
    }
  }

  function manualEntry() {
    const empty = {
      engine: "donut", receipt: { items: [], subtotal: null, tax: null, total: null, merchant: null },
      audit: {}, journal: null, balanced: null, vat: {}, raw_json: {}, fallback_note: null,
    };
    setFile(null);
    setExtracted(empty);
    setItems([emptyItem()]); setSubtotal(""); setTax(""); setTotal(""); setInvoiceNumber("");
    setComputed({ audit: {}, journal: null, balanced: null, vat: {}, receipt: empty.receipt });
    setPhase("result");
  }

  function buildPayload(persist) {
    const cleanItems = items
      .map((it) => ({
        name: it.name || null,
        quantity: it.quantity === "" || it.quantity == null ? null : Number(it.quantity),
        unit_price: it.unit_price === "" || it.unit_price == null ? null : Number(it.unit_price),
        line_price: it.line_price === "" || it.line_price == null ? null : Number(it.line_price),
      }))
      .filter((r) => r.name || r.line_price != null);
    const payload = {
      items: cleanItems,
      subtotal: subtotal === "" ? null : Number(subtotal),
      tax: tax === "" ? null : Number(tax),
      total: total === "" ? null : Number(total),
      account_overrides: accountOverrides,
      merchant: extracted?.receipt?.merchant ?? null,
      country, payment_mode: payment,
      doc_type: extracted?.doc_type ?? docType,
      invoice_number: invoiceNumber.trim() || null,
      image_data: extracted?.image_data ?? null,
      persist,
    };
    if (persist && extracted?.raw_json && Object.keys(extracted.raw_json).length) {
      payload.raw_json = extracted.raw_json;
      payload.engine = extracted.engine ?? null;
    }
    return payload;
  }

  // Recalcul live (debounced) : chips + écriture, sans persister.
  useEffect(() => {
    if (phase !== "result") return;
    const t = setTimeout(async () => {
      try {
        const data = await API.validate(buildPayload(false));
        setComputed({ audit: data.audit, journal: data.journal, balanced: data.balanced, vat: data.vat, receipt: data.receipt });
      } catch (e) {
        toast("Recalcul impossible : " + e.message);
      }
    }, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, subtotal, tax, total, accountOverrides, country, payment, invoiceNumber, phase]);

  async function save() {
    try {
      const payload = buildPayload(true);
      if (editingId != null) {
        await API.updateReceipt(editingId, payload);
        toast("Reçu #" + editingId + " mis à jour");
        await onSaved();
        reset();
      } else {
        const data = await API.validate(payload);
        if (data.persisted) {
          toast("Reçu #" + data.receipt_id + " enregistré dans vos dépenses");
          await onSaved();
          reset();
        } else {
          toast("Enregistré côté calcul mais non persisté.");
        }
      }
    } catch (e) {
      if (e.status === 403 && e.engine === "auth" && onRequireAccount) {
        toast(e.message);
        onRequireAccount();
      } else {
        toast("Enregistrement impossible : " + e.message);
      }
    }
  }

  function updateItem(i, key, value) {
    setItems((arr) => arr.map((it, idx) => (idx === i ? { ...it, [key]: value } : it)));
  }
  function addItemRow() { setItems((arr) => [...arr, emptyItem()]); }

  const missingVerify = !computed?.receipt || computed.receipt.subtotal == null
    || computed.receipt.tax == null || computed.receipt.total == null || computed.receipt.subtotal === 0;

  if (phase === "empty") {
    return (
      <>
        <div
          className={`dropzone${dragRef.current ? " drag" : ""}`}
          onClick={() => document.getElementById("react-file-input").click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]); }}
        >
          <div className="dropzone-icon"><Icon name="upload" className="icon" /></div>
          <p className="headline-md">Déposez une photo ou un PDF de reçu</p>
          <p className="muted body-lg">Cliquez ou glissez un fichier. L'extraction tourne principalement en local ; une image n'est envoyée à un tiers que si le modèle spécialisé ne suffit pas (lecture de secours, toujours indiquée à l'écran).</p>
          <div className="dropzone-formats">
            <span className="badge badge--nodata">JPG</span>
            <span className="badge badge--nodata">PNG</span>
            <span className="badge badge--nodata">PDF</span>
          </div>
          <input id="react-file-input" type="file" accept="image/*,application/pdf,.pdf" className="hidden"
                 onChange={(e) => { if (e.target.files[0]) handleFile(e.target.files[0]); }} />
        </div>
        <div className="tip-row">
          <Icon name="info" className="icon" style={{ color: "var(--accent-deco)" }} />
          <span className="muted body-sm">Une photo nette, à plat et bien éclairée améliore nettement l'extraction.</span>
        </div>
      </>
    );
  }

  if (phase === "loading") {
    return (
      <div className="card"><div className="loader">
        <div className="spinner"></div>
        <p className="headline-sm">Analyse du reçu en cours…</p>
        <span className={`loading-status${jobStatus === "running" ? " loading-status--running" : ""}`}>
          {jobStatus === "pending"
            ? "En file d'attente, une autre analyse est en cours"
            : "Inférence en cours sur le processeur"}
        </span>
        <p className="muted body-sm">
          {jobStatus === "pending"
            ? "La vôtre commencera juste après."
            : <>Comptez <b>30 à 60 secondes</b>, pas de GPU sur ce plan gratuit. Ne fermez pas la page.</>}
        </p>
        <ul className="steps">
          {STEPS.map((s, i) => (
            <li key={i} className={i < stepIndex ? "done" : i === stepIndex ? "active" : ""}>
              <span className="dot" />{s}
            </li>
          ))}
        </ul>
      </div></div>
    );
  }

  if (phase === "error") {
    const title = error?.message || "Impossible de lire ce reçu";
    const detail = error?.detail || "";
    const suggestions = error?.suggestions?.length ? error.suggestions
      : ["Réessayer avec une photo plus nette, à plat, bien éclairée", "Saisir les données manuellement"];
    return (
      <div className="card"><div className="error-state">
        <div className="error-icon"><Icon name="warn" className="icon" /></div>
        <p className="headline-sm" style={{ margin: "var(--md) 0 0" }}>{title}</p>
        {detail && <p className="muted body-sm" style={{ marginTop: "var(--xs)" }}>{detail}</p>}
        <div className="label-caps" style={{ marginTop: "var(--lg)" }}>Causes probables</div>
        <ul className="error-causes">{suggestions.map((s, i) => <li key={i}>{s}</li>)}</ul>
        <div className="btn-row" style={{ marginTop: "var(--md)" }}>
          <button className="btn btn--primary" onClick={reset}><Icon name="camera" className="icon" style={{ width: 16, height: 16 }} />Essayer une autre image</button>
          <button className="btn" onClick={manualEntry}>Saisir les données manuellement</button>
        </div>
      </div></div>
    );
  }

  // phase === "result"
  const r = computed?.receipt || {};
  const banner = country === "CI" && (
    <div className="banner">
      <Icon name="warn" className="icon-lg" />
      <div>
        <div className="banner-title">Mode expérimental : reçus ivoiriens</div>
        <div className="banner-body">L'extraction est entraînée sur un corpus international de reçus : les résultats sur un reçu ivoirien peuvent être dégradés, vérifiez-les avant validation. Les règles comptables SYSCOHADA, elles, restent pleinement fonctionnelles quels que soient les montants extraits.</div>
      </div>
    </div>
  );
  const charge = config?.charge_accounts || ["601", "605", "6181", "627", "628", "638"];
  const labels = config?.chart_of_accounts || {};
  let ci = -1;
  const journal = computed?.journal;
  const td = journal ? journal.reduce((s, l) => s + (l.debit || 0), 0) : 0;
  const tc = journal ? journal.reduce((s, l) => s + (l.credit || 0), 0) : 0;
  const vatNote = computed?.vat && computed.vat.recoverable === 0 && r.tax
    ? <div className="banner" style={{ marginTop: "var(--sm)" }}>TVA non récupérable : {computed.vat.reason}. Elle est réintégrée dans la charge.</div>
    : null;

  return (
    <>
      {banner}

      <div className="status-row">
        <EngineBadge engine={extracted?.engine} />
        {extracted?.fallback_note && <span className="muted body-sm">{extracted.fallback_note}</span>}
        {editingId != null && <span className="badge badge--review">Modification du reçu #{editingId}</span>}
      </div>

      {/* Niveau 1 — panneau principal : ce qui a été lu, éditable */}
      <div className="analyze-grid">
        <div><ImageOrPlaceholder file={file} imageData={extracted?.image_data} /></div>
        <div className="stack">
          {extracted?.doc_type === "facture" && (
            <div className="card"><div className="card-body">
              <label className="field" htmlFor="in-invoice">Numéro de facture (modifiable)</label>
              <input id="in-invoice" type="text" placeholder="ex. 12345" value={invoiceNumber}
                     onChange={(e) => setInvoiceNumber(e.target.value)} />
              <p className="muted body-sm" style={{ marginTop: "var(--xs)" }}>Détecté automatiquement, remplacez-le si besoin. Vide : « Facture #{"{id}"} ».</p>
            </div></div>
          )}
          <div className="card">
            <div className="card-head">
              <span className="card-head-label">Articles extraits <span className="count">({items.length})</span></span>
              {missingVerify && <span className="tag-verify"><Icon name="warn" className="icon" style={{ width: 13, height: 13 }} />À vérifier</span>}
            </div>
            <table className="editable">
              <thead><tr><th>Article</th><th className="num">Qté</th><th className="num">Prix unit.</th><th className="num">Total ligne</th></tr></thead>
              <tbody>
                {items.map((it, i) => (
                  <tr key={i}>
                    <td><input value={it.name ?? ""} onChange={(e) => updateItem(i, "name", e.target.value)} style={{ border: "none", padding: 0, background: "transparent" }} /></td>
                    <td className="num"><input type="number" value={it.quantity ?? ""} onChange={(e) => updateItem(i, "quantity", e.target.value)} style={{ border: "none", padding: 0, background: "transparent", textAlign: "right" }} /></td>
                    <td className="num"><input type="number" value={it.unit_price ?? ""} onChange={(e) => updateItem(i, "unit_price", e.target.value)} style={{ border: "none", padding: 0, background: "transparent", textAlign: "right" }} /></td>
                    <td className="num"><input type="number" value={it.line_price ?? ""} onChange={(e) => updateItem(i, "line_price", e.target.value)} style={{ border: "none", padding: 0, background: "transparent", textAlign: "right" }} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="card-body"><button className="btn" onClick={addItemRow}><Icon name="plus" className="icon" style={{ width: 14, height: 14 }} />Ajouter une ligne</button></div>
          </div>

          <div className="totals">
            <div className="total-box"><div className="label-caps">Sous-total</div>
              <input className="amount tabular" type="number" step="100" value={subtotal} onChange={(e) => setSubtotal(e.target.value)} /></div>
            <div className="total-box"><div className="label-caps">Taxe</div>
              <input className="amount tabular" type="number" step="100" value={tax} onChange={(e) => setTax(e.target.value)} /></div>
            <div className="total-box total-box--total"><div className="label-caps" style={{ color: "rgba(255,255,255,.75)" }}>Total</div>
              <input className="amount tabular" type="number" step="100" value={total} onChange={(e) => setTotal(e.target.value)}
                     style={{ background: "transparent", color: "#fff", borderColor: "rgba(255,255,255,.3)" }} /></div>
          </div>

          <p className="muted body-sm">Vous pouvez modifier chaque montant ci-dessus : les contrôles et l'écriture comptable ci-dessous se mettent à jour en temps réel.</p>
        </div>
      </div>

      {/* Niveau 2 — panneau secondaire : contrôles + écriture, teinté pour marquer un cran en dessous du résultat principal */}
      <div className="panel-tinted">
        <div className="card">
          <div className="card-head"><span className="card-head-label">Contrôles</span></div>
          <div className="card-body">
            <ReviewBanner pts={reviewPoints(computed?.audit, computed?.balanced, r)} editable />
            <ControlsPanel audit={computed?.audit} balanced={computed?.balanced} receipt={r} journal={journal} country={country} />
          </div>
        </div>

        <div className="card">
          <div className="card-head"><span className="card-head-label">Écriture comptable proposée</span>
            <span className="muted body-sm">Chaque compte de charge est modifiable</span></div>
          <div className="card-body" style={{ paddingBottom: 0 }}><FlowDiagram /></div>
          <table>
            <thead><tr>
              <th>Compte</th><th>Libellé</th>
              <th className="num" title="Débit = ce qui sort (une charge pour vous)">Débit</th>
              <th className="num" title="Crédit = ce qui entre / la contrepartie (caisse, banque, fournisseur)">Crédit</th>
            </tr></thead>
            <tbody>
              {journal ? journal.map((l, i) => {
                const isCharge = l.debit > 0 && l.account !== "4452";
                let cell;
                if (isCharge) {
                  ci += 1;
                  const myCi = ci;
                  cell = (
                    <>
                      <select className="journal-account" value={accountOverrides[myCi] ?? l.account}
                              onChange={(e) => setAccountOverrides((o) => ({ ...o, [myCi]: e.target.value }))}>
                        {charge.map((a) => <option key={a} value={a}>{a} : {labels[a] || ""}</option>)}
                      </select>
                      {l.manual && <span className="badge badge--review" title="Compte choisi manuellement" style={{ marginLeft: 6 }}>modifié</span>}
                    </>
                  );
                } else {
                  cell = <span style={{ color: "var(--accent)", fontWeight: 500 }}>{l.account}</span>;
                }
                return <tr key={i}><td>{cell}</td><td>{l.label}</td><td className="num">{money(l.debit)}</td><td className="num">{money(l.credit)}</td></tr>;
              }) : <tr><td colSpan={4} className="muted">Impossible de proposer une écriture : total, sous-total et lignes sont tous vides.</td></tr>}
            </tbody>
          </table>
          <div className="card-body">
            {journal && (
              <>
                <div className="tabular">Total débit : {money(td)} · Total crédit : {money(tc)} · {computed.balanced ? "équilibré" : "déséquilibré"}</div>
                {vatNote}
                <p className="muted body-sm" style={{ marginTop: "var(--sm)" }}>Cette écriture est une proposition automatique basée sur la catégorie détectée pour chaque article. Elle doit être validée par un comptable avant tout usage officiel.</p>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Niveau 3 — détail technique, discret et replié par défaut */}
      <details className="raw-details">
        <summary>Voir le JSON brut extrait</summary>
        <pre>{JSON.stringify(extracted?.raw_json || {}, null, 2)}</pre>
      </details>

      <div className="btn-row">
        <button className="btn btn--primary" onClick={save}>
          <Icon name="check" className="icon" style={{ width: 16, height: 16 }} />
          {editingId != null ? "Enregistrer les modifications" : "Valider et enregistrer dans les dépenses"}
        </button>
        <button className="btn" onClick={reset}>Annuler</button>
      </div>
    </>
  );
}
