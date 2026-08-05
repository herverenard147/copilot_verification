import { useEffect, useState } from "react";
import API from "../api.js";
import { money } from "../utils.js";
import { receiptLabel } from "../helpers.jsx";
import { ReceiptList } from "./ReceiptList.jsx";
import { ReceiptDetail } from "./ReceiptDetail.jsx";

function exportJournalCsv(journal) {
  const lines = [["receipt_id", "account", "label", "debit", "credit", "balanced"]];
  journal.forEach((g) => g.lines.forEach((l) =>
    lines.push([g.receipt_id, l.account, `"${(l.label || "").replace(/"/g, '""')}"`, l.debit, l.credit, g.balanced])));
  const csv = lines.map((r) => r.join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "journal_comptable.csv"; a.click();
}

export default function AccountingTab({ active, refreshToken, country, payment, demoMode, onSessionChange, onEditReceipt, onGoAnalyze }) {
  const [period, setPeriod] = useState("Mois en cours");
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [reasonFilter, setReasonFilter] = useState(null);

  async function load() {
    setError(null);
    try {
      const data = await API.accounting(period, payment, country);
      onSessionChange({ demoMode: !!data.demo_mode });
      setD(data);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => { if (active) load(); }, [active, period, payment, country, refreshToken]); // eslint-disable-line react-hooks/exhaustive-deps

  if (openId != null) {
    return (
      <ReceiptDetail id={openId} country={demoMode ? "ID" : country} demoMode={demoMode}
        onBack={() => setOpenId(null)}
        onEdit={(id) => onEditReceipt(id)}
        onDeleted={() => { setOpenId(null); load(); }} />
    );
  }

  return (
    <div>
      <div className="row" style={{ marginBottom: "var(--lg)" }}>
        <div>
          <label className="field" htmlFor="sel-period">Période</label>
          <select id="sel-period" value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option>Mois en cours</option>
            <option>Trimestre en cours</option>
            <option>Personnalisée</option>
          </select>
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}
      {!error && !d && <p className="muted">Chargement…</p>}

      {d && d.empty && (
        <div className="card"><div className="empty-state">
          <div className="empty-icon">🧮</div>
          <p className="headline-sm">Aucune écriture — analysez un reçu pour commencer</p>
          <p className="muted">Le journal comptable et la TVA se construisent à partir de vos reçus validés.</p>
          <div className="btn-row" style={{ justifyContent: "center", marginTop: "var(--md)" }}>
            <button className="btn btn--primary" onClick={onGoAnalyze}>📷 Analyser un reçu</button>
          </div>
          <p className="muted body-sm" style={{ marginTop: "var(--md)" }}>💡 Ou activez le mode démonstration dans ⚙️ Réglages.</p>
        </div></div>
      )}

      {d && !d.empty && reasonFilter && (
        <div>
          <div className="btn-row" style={{ marginBottom: "var(--md)" }}>
            <button className="btn" onClick={() => setReasonFilter(null)}>← Retour à la comptabilité</button>
          </div>
          <div className="card"><div className="section-body">
            <b>Reçus — motif :</b> {reasonFilter} <span className="muted">({(d.receipts || []).filter((r) => r.vat_reason === reasonFilter).length})</span>
          </div></div>
          <ReceiptList receipts={(d.receipts || []).filter((r) => r.vat_reason === reasonFilter)} title="Reçus concernés" onOpen={setOpenId} />
        </div>
      )}

      {d && !d.empty && !reasonFilter && (() => {
        const v = d.vat, rep = d.report;
        const reasons = Object.entries(v.non_recoverable_reasons || {});
        return (
          <div>
            <div className="banner">ℹ️ {d.disclaimer}</div>
            <div className="card"><div className="section-head"><span className="label-caps">TVA — {d.period}</span></div>
              <div className="section-body vat-diagram">
                <div className="vat-col vat-col--ok">
                  <div className="vat-col-head">🧾 Fournisseur identifié <span className="flow-arrow-txt">→</span> ✅ TVA récupérable</div>
                  <div className="label-caps">Récupérable</div><div className="headline-sm tabular">{money(v.recoverable_total)}</div>
                </div>
                <div className="vat-col vat-col--bad">
                  <div className="vat-col-head">❔ Fournisseur non identifié <span className="flow-arrow-txt">→</span> ⚠️ TVA non récupérable</div>
                  <div className="label-caps">Non récupérable</div><div className="headline-sm tabular">{money(v.non_recoverable_total)}</div>
                  {reasons.map(([reason, det]) => {
                    const isSupplier = /fournisseur/i.test(reason);
                    const text = isSupplier
                      ? `${det.count} reçus — TVA non récupérable : le nom du fournisseur n'apparaît pas sur ces reçus, ce qui empêche la déduction fiscale de la TVA. Pour récupérer la TVA, demandez une facture nominative au fournisseur.`
                      : `${reason} : ${det.count} reçu(s), ${money(det.amount)}`;
                    return (
                      <div key={reason} className="body-sm reason-link" title="Voir les reçus concernés" onClick={() => setReasonFilter(reason)}>
                        • {text} →
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="card"><div className="section-head"><span className="label-caps">Note de frais agrégée</span></div>
              <div className="section-body kpi-grid">
                <div className="kpi"><div className="label-caps">Total HT</div><div className="value">{money(rep.total_ht)}</div></div>
                <div className="kpi"><div className="label-caps">Total TVA</div><div className="value">{money(rep.total_tax)}</div></div>
                <div className="kpi"><div className="label-caps">Total TTC</div><div className="value">{money(rep.total_ttc)}</div></div>
              </div>
            </div>

            <div className="card">
              <div className="section-head"><span className="label-caps">Journal général, groupé par reçu</span>
                <button className="btn" onClick={() => exportJournalCsv(d.journal)}>📥 Export CSV</button></div>
              <table>
                <thead><tr>
                  <th>Reçu</th><th>Compte</th><th>Libellé</th>
                  <th className="num" title="Débit = ce qui sort (une charge pour vous)">Débit</th>
                  <th className="num" title="Crédit = ce qui entre / la contrepartie (caisse, banque, fournisseur)">Crédit</th>
                </tr></thead>
                <tbody>
                  {d.journal.slice(0, 100).map((g) => g.lines.map((l, i) => (
                    <tr key={g.receipt_id + "-" + i} className={g.balanced ? "" : "unbalanced"}>
                      {i === 0 && (
                        <td rowSpan={g.lines.length} className="receipt-open" title="Voir le détail du reçu" onClick={() => setOpenId(g.receipt_id)}>
                          <b>{receiptLabel(g)}</b> {g.balanced ? "✅" : "❌"}
                        </td>
                      )}
                      <td>{l.account}</td><td>{l.label}</td>
                      <td className="num">{money(l.debit)}</td><td className="num">{money(l.credit)}</td>
                    </tr>
                  )))}
                </tbody>
              </table>
              {d.journal.length > 100 && <div className="section-body muted body-sm">Affichage des 100 premiers reçus sur {d.journal.length}.</div>}
            </div>
          </div>
        );
      })()}
    </div>
  );
}
