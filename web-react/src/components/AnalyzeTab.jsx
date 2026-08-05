import { useEffect, useRef, useState } from "react";
import API from "../api.js";
import { money } from "../utils.js";
import { toast } from "../toast.jsx";
import {
  ControlsPanel, EngineBadge, FlowDiagram, ImageOrPlaceholder, ReviewBanner,
  reviewPoints,
} from "../helpers.jsx";

const STEPS = [
  "📥 Préparation et redressement de l'image",
  "🧠 Chargement du modèle Donut (au 1er lancement)",
  "🔍 Lecture du reçu",
  "🧮 Vérification des règles comptables",
];

function emptyItem() { return { name: "", quantity: "", unit_price: "", line_price: "" }; }

export default function AnalyzeTab({ country, payment, docType, config, pendingEdit, onConsumeEdit, onSaved }) {
  const [file, setFile] = useState(null);
  const [phase, setPhase] = useState("empty"); // empty | loading | error | result
  const [stepIndex, setStepIndex] = useState(0);
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
    if (phase !== "loading") return;
    setStepIndex(0);
    const t = setInterval(() => setStepIndex((i) => Math.min(i + 1, STEPS.length - 1)), 4000);
    return () => clearInterval(t);
  }, [phase]);

  function reset() {
    setFile(null); setExtracted(null); setEditingId(null); setAccountOverrides({});
    setItems([emptyItem()]); setSubtotal(""); setTax(""); setTotal(""); setInvoiceNumber("");
    setComputed(null); setPhase("empty"); setError(null);
  }

  async function handleFile(f) {
    setFile(f); setEditingId(null); setAccountOverrides({});
    setPhase("loading"); setError(null);
    try {
      const data = await API.extract(f, country, payment, docType);
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
        toast("💾 Reçu #" + editingId + " mis à jour");
        await onSaved();
        reset();
      } else {
        const data = await API.validate(payload);
        if (data.persisted) {
          toast("✅ Reçu #" + data.receipt_id + " enregistré dans vos dépenses");
          await onSaved();
          reset();
        } else {
          toast("Enregistré côté calcul mais non persisté.");
        }
      }
    } catch (e) {
      toast("Enregistrement impossible : " + e.message);
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
      <div>
        <div
          className={`dropzone${dragRef.current ? " drag" : ""}`}
          onClick={() => document.getElementById("react-file-input").click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]); }}
        >
          <div style={{ fontSize: 40 }}>📤</div>
          <p className="headline-sm">Déposer une photo de reçu</p>
          <p className="muted">Cliquez ou glissez une image (JPG, PNG). L'analyse tourne en local.</p>
          <input id="react-file-input" type="file" accept="image/*" className="hidden"
                 onChange={(e) => { if (e.target.files[0]) handleFile(e.target.files[0]); }} />
        </div>
        <p className="muted body-sm" style={{ marginTop: "var(--md)" }}>
          💡 Astuce : une photo nette, à plat et bien éclairée améliore nettement l'extraction.
        </p>
      </div>
    );
  }

  if (phase === "loading") {
    return (
      <div className="card"><div className="loader">
        <div className="spinner"></div>
        <p className="headline-sm">Analyse du reçu en cours…</p>
        <p className="muted">L'inférence tourne sur le processeur : comptez <b>30 à 60 secondes</b>. Ne fermez pas la page.</p>
        <ul className="steps">
          {STEPS.map((s, i) => (
            <li key={i} className={i < stepIndex ? "done" : i === stepIndex ? "active" : ""}>{s}</li>
          ))}
        </ul>
      </div></div>
    );
  }

  if (phase === "error") {
    const title = error?.message || "Impossible de lire ce reçu";
    const detail = error?.detail || "";
    const suggestions = error?.suggestions?.length ? error.suggestions
      : ["Réessayer avec une photo plus nette", "Saisir les données manuellement"];
    return (
      <div className="card"><div className="section-body">
        <div className="error-box"><b>{title}</b>{detail && <><br />{detail}</>}</div>
        <div style={{ marginTop: "var(--md)" }}>
          <div className="label-caps">Suggestions</div>
          <ul className="muted body-sm">{suggestions.map((s, i) => <li key={i}>{s}</li>)}</ul>
        </div>
        <div className="btn-row" style={{ marginTop: "var(--md)" }}>
          <button className="btn btn--primary" onClick={reset}>📷 Essayer une autre image</button>
          <button className="btn" onClick={manualEntry}>✏️ Saisir les données manuellement</button>
        </div>
      </div></div>
    );
  }

  // phase === "result"
  const r = computed?.receipt || {};
  const banner = country === "CI" && (
    <div className="banner">⚠️ <b>Mode expérimental</b> : l'extraction est entraînée sur des reçus indonésiens (CORD),
      les résultats sur reçus ivoiriens sont dégradés. Les règles comptables SYSCOHADA, elles, restent fonctionnelles.</div>
  );
  const charge = config?.charge_accounts || ["601", "605", "6181", "627", "628", "638"];
  const labels = config?.chart_of_accounts || {};
  let ci = -1;
  const journal = computed?.journal;
  const td = journal ? journal.reduce((s, l) => s + (l.debit || 0), 0) : 0;
  const tc = journal ? journal.reduce((s, l) => s + (l.credit || 0), 0) : 0;
  const vatNote = computed?.vat && computed.vat.recoverable === 0 && r.tax
    ? <div className="banner" style={{ marginTop: "var(--sm)" }}>TVA non récupérable — {computed.vat.reason}. Elle est réintégrée dans la charge.</div>
    : null;

  return (
    <div>
      {banner}
      <div style={{ marginBottom: "var(--md)" }}>
        <EngineBadge engine={extracted?.engine} />
        {extracted?.fallback_note && <span className="muted body-sm" style={{ marginLeft: "var(--sm)" }}>{extracted.fallback_note}</span>}
        {editingId != null && <span className="badge badge--review" style={{ marginLeft: "var(--sm)" }}>✏️ Modification du reçu #{editingId}</span>}
      </div>
      <p className="muted body-sm" style={{ marginBottom: "var(--md)" }}>💡 Vous pouvez modifier chaque montant dans le tableau. Les contrôles et l'écriture comptable se mettent à jour en temps réel.</p>
      <div className="analyze-grid">
        <div><ImageOrPlaceholder file={file} imageData={extracted?.image_data} /></div>
        <div className="stack">
          {extracted?.doc_type === "facture" && (
            <div className="card"><div className="section-body">
              <label className="field" htmlFor="in-invoice">Numéro de facture (modifiable)</label>
              <input id="in-invoice" type="text" placeholder="ex. 12345" value={invoiceNumber}
                     onChange={(e) => setInvoiceNumber(e.target.value)} />
              <p className="muted body-sm" style={{ marginTop: "var(--xs)" }}>Détecté automatiquement — remplacez-le si besoin. Vide → « Facture #{"{id}"} ».</p>
            </div></div>
          )}
          <div className="card">
            <div className="section-head">
              <span className="label-caps">Articles extraits</span>
              {missingVerify && <span className="tag-verify">⚠️ à vérifier</span>}
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
            <div className="section-body"><button className="btn" onClick={addItemRow}>+ Ajouter une ligne</button></div>
          </div>

          <div className="totals">
            <div className="total-box"><div className="label-caps">Sous-total</div>
              <input className="amount tabular" type="number" step="100" value={subtotal} onChange={(e) => setSubtotal(e.target.value)} /></div>
            <div className="total-box total-box--tax"><div className="label-caps">Taxe</div>
              <input className="amount tabular" type="number" step="100" value={tax} onChange={(e) => setTax(e.target.value)} /></div>
            <div className="total-box total-box--total"><div className="label-caps">Total</div>
              <input className="amount tabular" type="number" step="100" value={total} onChange={(e) => setTotal(e.target.value)}
                     style={{ background: "transparent", color: "#fff", borderColor: "rgba(255,255,255,.3)" }} /></div>
          </div>

          <div className="card">
            <div className="section-head"><span className="label-caps">Contrôles</span></div>
            <div className="section-body">
              <ReviewBanner pts={reviewPoints(computed?.audit, computed?.balanced, r)} editable />
              <ControlsPanel audit={computed?.audit} balanced={computed?.balanced} receipt={r} journal={journal} country={country} />
            </div>
          </div>

          <div className="card">
            <div className="section-head"><span className="label-caps">Écriture comptable proposée</span>
              <span className="muted body-sm">Chaque compte de charge est modifiable</span></div>
            <div className="section-body" style={{ paddingBottom: 0 }}><FlowDiagram /></div>
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
                          {charge.map((a) => <option key={a} value={a}>{a} — {labels[a] || ""}</option>)}
                        </select>
                        {l.manual && <span className="badge badge--review" title="Compte choisi manuellement"> ✏️ modifié</span>}
                      </>
                    );
                  } else {
                    cell = <span style={{ color: "var(--primary)", fontWeight: 500 }}>{l.account}</span>;
                  }
                  return <tr key={i}><td>{cell}</td><td>{l.label}</td><td className="num">{money(l.debit)}</td><td className="num">{money(l.credit)}</td></tr>;
                }) : <tr><td colSpan={4} className="muted">Impossible de proposer une écriture : total, sous-total et lignes sont tous vides.</td></tr>}
              </tbody>
            </table>
            <div className="section-body">
              {journal && (
                <>
                  <div className="tabular">Total débit : {money(td)} · Total crédit : {money(tc)} · {computed.balanced ? "✅ équilibré" : "❌ déséquilibré"}</div>
                  {vatNote}
                  <p className="muted body-sm" style={{ marginTop: "var(--sm)" }}>Cette écriture est une proposition automatique basée sur la catégorie détectée pour chaque article. Elle doit être validée par un comptable avant tout usage officiel. Vous pouvez modifier les montants ci-dessus : les contrôles et l'écriture se recalculeront automatiquement.</p>
                </>
              )}
            </div>
          </div>

          <details>
            <summary>Voir le JSON brut extrait</summary>
            <pre>{JSON.stringify(extracted?.raw_json || {}, null, 2)}</pre>
          </details>

          <div className="btn-row">
            <button className="btn btn--primary" onClick={save}>{editingId != null ? "💾 Enregistrer les modifications" : "✅ Valider et enregistrer dans les dépenses"}</button>
            <button className="btn" onClick={reset}>Annuler</button>
          </div>
        </div>
      </div>
    </div>
  );
}
