import { useEffect, useState } from "react";
import API from "../api.js";
import { money } from "../utils.js";
import { toast } from "../toast.jsx";
import {
  ControlsPanel, ImageOrPlaceholder, ReviewBanner, receiptLabel, reviewPoints,
} from "../helpers.jsx";

export function ReceiptDetail({ id, country, demoMode, onBack, onEdit, onDeleted }) {
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    API.receipt(id, country).then((data) => { if (!cancelled) setD(data); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [id, country]);

  async function handleDelete() {
    if (!window.confirm(`Supprimer définitivement le reçu #${id} ? Cette action est irréversible.`)) return;
    try {
      await API.deleteReceipt(id);
      toast("🗑️ Reçu #" + id + " supprimé");
      onDeleted();
    } catch (e) {
      toast("Suppression impossible : " + e.message);
    }
  }

  if (error) {
    return (
      <div>
        <div className="error-box">{error}</div>
        <div className="btn-row" style={{ marginTop: "var(--md)" }}>
          <button className="btn" onClick={onBack}>← Retour</button>
        </div>
      </div>
    );
  }
  if (!d) return <p className="muted">Chargement du reçu #{id}…</p>;

  const r = d.receipt, a = d.audit || {};
  const items = r.items || [];

  return (
    <div>
      <div className="btn-row" style={{ marginBottom: "var(--md)" }}>
        <button className="btn" onClick={onBack}>← Retour</button>
        {!demoMode && <button className="btn" onClick={() => onEdit(id)}>✏️ Modifier</button>}
        {!demoMode && <button className="btn" onClick={handleDelete}>🗑️ Supprimer</button>}
      </div>
      <ReviewBanner pts={reviewPoints(a, d.balanced, r)} editable={false} />
      <div className="analyze-grid">
        <div><ImageOrPlaceholder file={null} imageData={d.image_data} /></div>
        <div className="stack">
          <div className="card"><div className="section-head">
            <span className="label-caps">
              {receiptLabel({ doc_type: d.doc_type, invoice_number: d.invoice_number, receipt_id: id })}
              {d.category ? ` — ${d.category}` : ""}
            </span>
          </div></div>
          <div className="card">
            <div className="section-head"><span className="label-caps">Articles</span></div>
            <table>
              <thead><tr><th>Article</th><th className="num">Qté</th><th className="num">Prix unit.</th><th className="num">Total ligne</th></tr></thead>
              <tbody>
                {items.length ? items.map((it, i) => (
                  <tr key={i}>
                    <td>{it.name || "—"}</td><td className="num">{it.quantity ?? ""}</td>
                    <td className="num">{money(it.unit_price)}</td><td className="num">{money(it.line_price)}</td>
                  </tr>
                )) : <tr><td colSpan={4} className="muted">Aucun article enregistré.</td></tr>}
              </tbody>
            </table>
            <div className="section-body tabular">
              Sous-total : {money(r.subtotal)} · Taxe : {money(r.tax)} · Total : {money(r.total)}
            </div>
          </div>
          <div className="card">
            <div className="section-head"><span className="label-caps">Contrôles</span></div>
            <div className="section-body">
              <ControlsPanel audit={a} balanced={d.balanced} receipt={r} journal={d.journal} country={country} />
            </div>
          </div>
          <div className="card">
            <div className="section-head"><span className="label-caps">Écriture comptable</span></div>
            <table>
              <thead><tr>
                <th>Compte</th><th>Libellé</th>
                <th className="num" title="Débit = ce qui sort (une charge pour vous)">Débit</th>
                <th className="num" title="Crédit = ce qui entre / la contrepartie (caisse, banque, fournisseur)">Crédit</th>
              </tr></thead>
              <tbody>
                {d.journal ? d.journal.map((l, i) => (
                  <tr key={i}>
                    <td style={{ color: "var(--primary)", fontWeight: 500 }}>
                      {l.account}{l.manual && <span className="badge badge--review" title="Compte choisi manuellement"> ✏️ modifié</span>}
                    </td>
                    <td>{l.label}</td><td className="num">{money(l.debit)}</td><td className="num">{money(l.credit)}</td>
                  </tr>
                )) : <tr><td colSpan={4} className="muted">Écriture impossible : montants insuffisants.</td></tr>}
              </tbody>
            </table>
            <p className="muted body-sm" style={{ margin: "var(--sm) var(--md)" }}>
              ℹ️ Affectation comptable indicative, à valider par un professionnel (expert-comptable) avant tout usage officiel.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
