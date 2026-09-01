import { useEffect, useState } from "react";
import API from "../api.js";
import { money } from "../utils.js";
import { receiptLabel } from "../helpers.jsx";
import { Icon } from "../Icons.jsx";
import { ReceiptList } from "./ReceiptList.jsx";
import { ReceiptDetail } from "./ReceiptDetail.jsx";

const PERIODS = ["Mois en cours", "Trimestre en cours", "Personnalisée"];
const PERIOD_SHORT = { "Mois en cours": "Mois", "Trimestre en cours": "Trimestre", "Personnalisée": "Personnalisé" };

function todayIso() { return new Date().toISOString().slice(0, 10); }
function daysAgoIso(n) { return new Date(Date.now() - n * 86400000).toISOString().slice(0, 10); }

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
  const [dateFrom, setDateFrom] = useState(daysAgoIso(30));
  const [dateTo, setDateTo] = useState(todayIso());
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [reasonFilter, setReasonFilter] = useState(null);

  async function load() {
    setError(null);
    try {
      const data = await API.accounting(period, payment, country,
        period === "Personnalisée" ? dateFrom : null,
        period === "Personnalisée" ? dateTo : null);
      onSessionChange({ demoMode: !!data.demo_mode });
      setD(data);
    } catch (e) {
      setError(e.message);
    }
  }

  useEffect(() => { if (active) load(); }, [active, period, payment, country, refreshToken, dateFrom, dateTo]); // eslint-disable-line react-hooks/exhaustive-deps

  if (openId != null) {
    return (
      <ReceiptDetail id={openId} country={demoMode ? "ID" : country} demoMode={demoMode}
        onBack={() => setOpenId(null)}
        onEdit={(id) => onEditReceipt(id)}
        onDeleted={() => { setOpenId(null); load(); }} />
    );
  }

  return (
    <>
      <div className="toolbar-row">
        <div className="period-tabs">
          {PERIODS.map((p) => (
            <button key={p} className={`period-tab${period === p ? " active" : ""}`} onClick={() => setPeriod(p)}>{PERIOD_SHORT[p]}</button>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {period === "Personnalisée" && (
            <>
              <input type="date" value={dateFrom} max={dateTo} onChange={(e) => setDateFrom(e.target.value)} style={{ width: 150 }} />
              <span className="muted">→</span>
              <input type="date" value={dateTo} min={dateFrom} max={todayIso()} onChange={(e) => setDateTo(e.target.value)} style={{ width: 150 }} />
            </>
          )}
          {d && !d.empty && (
            <button className="btn" onClick={() => exportJournalCsv(d.journal)}><Icon name="download" className="icon" style={{ width: 15, height: 15 }} />Exporter</button>
          )}
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}
      {!error && !d && <p className="muted">Chargement…</p>}

      {d && d.empty && (
        <div className="card"><div className="empty-state">
          <div className="empty-icon"><Icon name="ledger" className="icon" style={{ width: 32, height: 32 }} /></div>
          <p className="headline-sm">Aucune écriture sur cette période</p>
          <p className="muted">Le journal comptable et la TVA se construisent à partir de vos reçus validés.</p>
          <div className="btn-row" style={{ justifyContent: "center", marginTop: "var(--md)" }}>
            <button className="btn btn--primary" onClick={onGoAnalyze}><Icon name="camera" className="icon" style={{ width: 16, height: 16 }} />Analyser un reçu</button>
          </div>
          <p className="muted body-sm" style={{ marginTop: "var(--md)" }}>Ou activez le mode démonstration dans Paramètres.</p>
        </div></div>
      )}

      {d && !d.empty && reasonFilter && (
        <>
          <div className="btn-row">
            <button className="btn" onClick={() => setReasonFilter(null)}><Icon name="arrow-left" className="icon" style={{ width: 15, height: 15 }} />Retour à la comptabilité</button>
          </div>
          <div className="card"><div className="card-body">
            <b>Reçus, motif :</b> {reasonFilter} <span className="muted">({(d.receipts || []).filter((r) => r.vat_reason === reasonFilter).length})</span>
          </div></div>
          <ReceiptList receipts={(d.receipts || []).filter((r) => r.vat_reason === reasonFilter)} title="Reçus concernés" onOpen={setOpenId} />
        </>
      )}

      {d && !d.empty && !reasonFilter && (() => {
        const v = d.vat, rep = d.report;
        const reasons = Object.entries(v.non_recoverable_reasons || {});
        return (
          <>
            <div className="banner">{d.disclaimer}</div>
            <div className="vat-panel">
              <div className="vat-col ok">
                <div className="vat-col-head">TVA récupérable</div>
                <div className="vat-amount num">{money(v.recoverable_total)}</div>
                <div className="vat-reason"><span>Fournisseur identifié, facture conforme</span></div>
              </div>
              <div className="vat-col warn">
                <div className="vat-col-head">TVA non récupérable</div>
                <div className="vat-amount num">{money(v.non_recoverable_total)}</div>
                {reasons.map(([reason, det]) => {
                  const isSupplier = /fournisseur/i.test(reason);
                  const text = isSupplier
                    ? "Fournisseur non identifié : le nom n'apparaît pas sur ces reçus, ce qui empêche la déduction fiscale de la TVA. Demandez une facture nominative pour la récupérer."
                    : reason;
                  return (
                    <div className="vat-reason reason-link" key={reason} title="Voir les reçus concernés" onClick={() => setReasonFilter(reason)}>
                      <span>{text}</span><span className="num">{det.count} reçus</span>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="card"><div className="card-head"><span className="card-head-label">Note de frais agrégée</span></div>
              <div className="card-body kpi-grid" style={{ padding: 18 }}>
                <div className="kpi"><div className="label-caps">Total HT</div><div className="value">{money(rep.total_ht)}</div></div>
                <div className="kpi"><div className="label-caps">Total TVA</div><div className="value">{money(rep.total_tax)}</div></div>
                <div className="kpi"><div className="label-caps">Total TTC</div><div className="value">{money(rep.total_ttc)}</div></div>
              </div>
            </div>

            <div className="card">
              <div className="card-head"><span className="card-head-label">Journal général, groupé par reçu</span></div>
              <table>
                <thead><tr>
                  <th>Reçu</th><th>Compte</th><th>Libellé</th>
                  <th className="num" title="Débit = ce qui sort (une charge pour vous)">Débit</th>
                  <th className="num" title="Crédit = ce qui entre / la contrepartie (caisse, banque, fournisseur)">Crédit</th>
                  <th>Statut</th>
                </tr></thead>
                <tbody>
                  {d.journal.slice(0, 100).map((g) => g.lines.map((l, i) => (
                    <tr key={g.receipt_id + "-" + i} className={g.balanced ? "" : "unbalanced"}>
                      {i === 0 && (
                        <td rowSpan={g.lines.length} className="receipt-open" title="Voir le détail du reçu" onClick={() => setOpenId(g.receipt_id)}>
                          <b>{receiptLabel(g)}</b>
                        </td>
                      )}
                      <td>{l.account}</td><td>{l.label}</td>
                      <td className="num">{money(l.debit)}</td><td className="num">{money(l.credit)}</td>
                      {i === 0 && (
                        <td rowSpan={g.lines.length}>
                          <span className={`status-chip ${g.balanced ? "ok" : "warn"}`}>
                            <Icon name={g.balanced ? "check" : "warn"} className="icon" style={{ width: 11, height: 11 }} />
                            {g.balanced ? "Équilibré" : "Déséquilibré"}
                          </span>
                        </td>
                      )}
                    </tr>
                  )))}
                </tbody>
              </table>
              {d.journal.length > 100 && <div className="foot-note">Affichage des 100 premiers reçus sur {d.journal.length}.</div>}
              <div className="foot-note">Affectation comptable indicative, générée automatiquement à partir de règles simples. À valider par un professionnel (expert-comptable) avant toute utilisation officielle.</div>
            </div>
          </>
        );
      })()}
    </>
  );
}
